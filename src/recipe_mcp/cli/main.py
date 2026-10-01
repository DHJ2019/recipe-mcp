"""``recipe-mcp`` command-line interface (argparse, no extra dependencies)."""

from __future__ import annotations

import argparse
import getpass
import json
import logging
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from recipe_mcp import __version__
from recipe_mcp.domain import dietary, staples
from recipe_mcp.domain.models import Member, RecommendationRequest, RecommendationResult, Sentiment
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.providers.agent_brain import Brain
from recipe_mcp.services import fixtures
from recipe_mcp.services.container import AppContext, build_context
from recipe_mcp.settings import MissingConfigError, Settings, env_file_problems, load_settings

Handler = Callable[[argparse.Namespace, Settings], int]
REPO_ROOT = Path(__file__).resolve().parents[3]
DAEMON_PLIST = REPO_ROOT / "deploy" / "com.recipe-mcp.telegram.plist"
BACKUP_PLIST = REPO_ROOT / "deploy" / "com.recipe-mcp.backup.plist"


def _ctx(settings: Settings) -> AppContext:
    return build_context(settings)


# httpx logs every request URL at INFO, and Telegram Bot API URLs embed the bot token.
QUIET_LOGGERS = ("httpx", "httpcore")


def configure_logging(level: str) -> None:
    """Configure root logging and keep HTTP client loggers from ever logging request URLs."""
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


# -- commands ---------------------------------------------------------------


def cmd_init_db(args: argparse.Namespace, settings: Settings) -> int:
    ctx = _ctx(settings)
    try:
        print(f"database ready: {settings.database_url}")
        print(f"household: {ctx.household.name} (id {ctx.household_id})")
        members = ctx.members.list_for_household(ctx.household_id)
        if members:
            print("members: " + ", ".join(m.member_key for m in members))
        return 0
    finally:
        ctx.close()


def exposed_to_others(path: Path, root: Path | None = None) -> bool:
    """True when another account could read ``path``: it has group or other permission
    bits and no folder above it (up to ``root``, default the filesystem root) is private
    (mode 700) to its owner."""
    try:
        if path.stat().st_mode & 0o077 == 0:
            return False
        parents: list[Path] = list(path.resolve().parents)
        if root is not None:
            top = root.resolve()
            parents = [p for p in parents if p == top or top in p.parents]
        return not any(parent.stat().st_mode & 0o077 == 0 for parent in parents)
    except OSError:
        return False


def private_paths(settings: Settings) -> list[Path]:
    """Files and folders holding secrets or household data. Only modes are checked."""
    paths = [
        Path(".env"),
        Path(".private"),
        settings.members_path,
        settings.private_evals_path,
        settings.nyt_browser_profile_path,
        settings.whatsapp_export_path,
        settings.temp_media_dir,
        settings.backup_dir,
        BRAIN_WORKDIR,
        BRAIN_WORKDIR / "mcp.json",
    ]
    if settings.database_path is not None:
        db = settings.database_path
        paths += [db.parent, db, db.with_name(db.name + "-wal"), db.with_name(db.name + "-shm")]
    unique: dict[Path, None] = {}
    for path in paths:
        if path.exists():
            unique.setdefault(path, None)
    return list(unique)


def cmd_doctor(args: argparse.Namespace, settings: Settings) -> int:
    ok = True
    print(f"recipe-mcp {__version__}")
    print("\nConfiguration (secrets shown as set/unset):")
    for key, value in settings.redacted_summary().items():
        print(f"  {key:36} {value}")
    if not Path(".env").exists():
        print("\n  note: no .env file found; run `make setup` to create one from .env.example")
    else:
        bad_lines = env_file_problems(".env")
        if bad_lines:
            ok = False
            numbers = ", ".join(str(n) for n in bad_lines)
            print(
                f"\n  FAIL .env line(s) {numbers} are not KEY=VALUE. A pasted secret probably "
                "wrapped onto a new line; join it onto the line above so the value is complete."
            )

    print("\nDatabase:")
    try:
        ctx = _ctx(settings)
    except Exception as exc:  # pragma: no cover - diagnostic path
        print(f"  FAIL cannot open database: {exc.__class__.__name__}: {exc}")
        return 1
    try:
        from recipe_mcp.db.migrations import applied_migrations

        print(f"  ok   {settings.database_url}")
        print(f"  ok   migrations applied: {', '.join(applied_migrations(ctx.db))}")
        print(f"  ok   recipes stored: {ctx.recipes.count(ctx.household_id)}")
        members = ctx.members.list_for_household(ctx.household_id)
        keys = ", ".join(m.member_key for m in members) or "none"
        print(f"  ok   members: {keys} (from {settings.members_path})")
        if settings.default_member and ctx.resolve_member(None) is None:
            ok = False
            print(f"  FAIL DEFAULT_MEMBER {settings.default_member!r} is not a configured member")

        print("\nBrain (agent that does the semantic work):")
        missing = settings.missing_for("brain")
        if missing:
            print(f"  warn {settings.brain}: {', '.join(missing)}")
        else:
            print(f"  ok   {settings.brain} via {settings.claude_code_bin} (uses .mcp.json)")
            if settings.anthropic_api_key is not None:
                print(
                    "  note ANTHROPIC_API_KEY is set in .env; it is removed from the brain's "
                    "environment so replies use your subscription, not per-token API billing"
                )
            auth = (
                "CLAUDE_CODE_OAUTH_TOKEN" if settings.claude_code_oauth_token else "keychain login"
            )
            print(f"  ok   brain authenticates with {auth}")
        print("\nServer-side model provider (optional, Phase 2 comparison):")
        if settings.model_provider == "none":
            print(
                "  ok   none: MCP client agents parse and classify; the server stays deterministic"
            )
        else:
            missing = settings.missing_for("model")
            if missing:
                print(
                    f"  warn {settings.model_provider} selected but missing: {', '.join(missing)}"
                )
            else:
                print(f"  ok   {settings.model_provider} / {settings.effective_model_name}")

        print("\nFixtures:")
        for path in (
            fixtures.SYNTHETIC_RECIPES,
            fixtures.TUNA_FIXTURE,
            fixtures.INITIAL_QUERIES,
            staples.DEFAULT_STAPLES_FILE,
        ):
            exists = path.exists()
            ok = ok and exists
            print(f"  {'ok  ' if exists else 'FAIL'} {path.relative_to(fixtures.REPO_ROOT)}")

        print("\nMCP server:")
        import anyio

        from recipe_mcp.adapters.mcp import TOOL_NAMES, build_server

        server = build_server(ctx)
        tools = anyio.run(server.list_tools)
        names = sorted(t.name for t in tools)
        if names == sorted(TOOL_NAMES):
            print(f"  ok   tools: {', '.join(names)}")
        else:
            ok = False
            print(f"  FAIL unexpected tools: {names}")

        print("\nOptional integrations:")
        for feature in ("telegram", "shortcut", "nyt_browser", "whatsapp_export", "private_evals"):
            missing = settings.missing_for(feature)
            state = "configured" if not missing else "skip, missing " + ", ".join(missing)
            print(f"  {feature}: {state}")
        if not settings.missing_for("nyt_browser"):
            from recipe_mcp.adapters.nyt.browser import session_status

            status = session_status(settings.nyt_browser_profile_path)
            print(f"       {'ok  ' if status.ok else 'warn'} {status.summary()}")
        if not settings.missing_for("telegram"):
            print("       (Telegram token validity is checked by `make smoke`)")

        print("\nBackups:")
        if settings.database_path is None:
            print("  ok   in-memory database; nothing to back up")
        else:
            from datetime import UTC, datetime

            from recipe_mcp.services.backups import STALE_AFTER, newest_backup_age

            age = newest_backup_age(settings.backup_dir, datetime.now(UTC))
            if age is None:
                print(
                    f"  warn no backups in {settings.backup_dir}; run `make backup`, and "
                    "`make install-daemon` for the nightly job"
                )
            elif age > STALE_AFTER:
                hours = int(age.total_seconds() // 3600)
                print(
                    f"  warn newest backup is {hours} hours old; check the nightly job "
                    "(/Library/Logs/recipe-mcp/backup.log)"
                )
            else:
                print(f"  ok   newest backup is {int(age.total_seconds() // 3600)} hours old")

        print("\nFile permissions (modes only, never contents):")
        exposed: list[Path] = []
        for path in private_paths(settings):
            # Fixing a folder protects everything inside it, so name only the folder.
            covered = any(e.resolve() in path.resolve().parents for e in exposed)
            if not covered and exposed_to_others(path):
                exposed.append(path)
        for path in exposed:
            mode = path.stat().st_mode & 0o777
            fix = "700" if path.is_dir() else "600"
            print(
                f"  warn {path} is readable by other accounts (mode {mode:o}); chmod {fix} {path}"
            )
        if not exposed:
            print("  ok   secrets and household data are private to this account")
    finally:
        ctx.close()
    print("\n" + ("All core checks passed." if ok else "Some core checks failed."))
    return 0 if ok else 1


def _print_results(results: list[RecommendationResult]) -> None:
    for n, r in enumerate(results, start=1):
        time = f"{r.total_minutes} min" if r.total_minutes else "time unknown"
        facets = r.classifications
        tags = " · ".join(
            vs[0]
            for key in ("dietary_suitability", "cuisine", "dish_type", "character")
            if (vs := facets.get(key))
        )
        print(f"{n}. {r.title} ({time})")
        print(f"   {tags}")
        if r.ingredients_missing and r.ingredients_available:
            print(f"   missing: {', '.join(r.ingredients_missing)}")
        print(f"   why: {'; '.join(r.reasons)}")
        if r.source_url:
            print(f"   {r.source_url}")


def cmd_demo(args: argparse.Namespace, settings: Settings) -> int:
    ctx = _ctx(settings)
    try:
        recipes, added = fixtures.seed_demo(ctx)
        print(f"Loaded {len(recipes)} synthetic recipes ({added} demo ratings added).")
        print("\nSample query: something cozy under 45 minutes (household view)\n")
        request = RecommendationRequest(
            character=["cozy"], max_minutes=45, diners=ctx.recommendation.diners_for(None)
        )
        results = ctx.recommendation.recommend(request)
        _print_results(results)
        print("\nTry it from an MCP client next; see README 'Level 1'.")
        return 0 if len(results) == 3 else 1
    finally:
        ctx.close()


def cmd_serve(args: argparse.Namespace, settings: Settings) -> int:
    from recipe_mcp.adapters.mcp import build_server

    ctx = _ctx(settings)
    try:
        build_server(ctx).run("stdio")
        return 0
    finally:
        ctx.close()


BRAIN_WORKDIR = REPO_ROOT / ".private" / "brain"


def write_brain_mcp_config(workdir: Path, repo_root: Path, uv_path: str) -> Path:
    """Write the brain's own MCP config with absolute paths, so `claude -p` can run from
    an empty folder while the recipe server still starts in the repository."""
    workdir.mkdir(parents=True, exist_ok=True)
    workdir.chmod(0o700)
    config = {
        "mcpServers": {
            "recipe-mcp": {
                "command": uv_path,
                "args": [
                    "--directory",
                    str(repo_root),
                    "run",
                    "--env-file",
                    str(repo_root / ".env"),
                    "recipe-mcp",
                    "serve",
                ],
            }
        }
    }
    path = workdir / "mcp.json"
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _build_brain(settings: Settings) -> Brain:
    from recipe_mcp.providers.agent_brain import ClaudeCodeBrain

    uv_path = shutil.which("uv") or "uv"
    mcp_config = write_brain_mcp_config(BRAIN_WORKDIR, REPO_ROOT, uv_path)
    return ClaudeCodeBrain(
        binary=settings.claude_code_bin,
        repo_root=REPO_ROOT,
        mcp_config=mcp_config,
        workdir=BRAIN_WORKDIR,
        model=settings.brain_model,
        timeout_seconds=settings.brain_timeout_seconds,
        max_turns=settings.brain_max_turns,
        env=settings.brain_child_env(),
    )


def cmd_serve_telegram(args: argparse.Namespace, settings: Settings) -> int:
    missing = settings.missing_for("telegram") + settings.missing_for("brain")
    if missing:
        print(f"Telegram host cannot start; missing: {', '.join(missing)}", file=sys.stderr)
        return 2
    from recipe_mcp.adapters.telegram import HttpTelegramApi, TelegramHost

    configure_logging(settings.log_level)
    assert settings.telegram_bot_token is not None
    ctx = _ctx(settings)
    try:
        host = TelegramHost(
            ctx,
            HttpTelegramApi(settings.telegram_bot_token.get_secret_value()),
            _build_brain(settings),
        )
        host.run_forever()
        return 0
    except KeyboardInterrupt:
        return 0
    finally:
        ctx.close()


def cmd_nyt_login(args: argparse.Namespace, settings: Settings) -> int:
    """One-time interactive NYT sign-in. No password is read, typed or stored here."""
    from recipe_mcp.adapters.nyt.browser import (
        PlaywrightUnavailableError,
        login,
        session_status,
    )

    path = settings.nyt_browser_profile_path
    existing = session_status(path)
    if existing.ok and not args.force:
        print(f"Already signed in: {existing.summary()}")
        print("Pass --force to sign in again.")
        return 0
    print(f"Opening a browser against {path}.")
    print("Sign in to NYT Cooking in that window; it closes itself once the session lands.")
    try:
        status = login(path, timeout_seconds=args.timeout)
    except PlaywrightUnavailableError as exc:
        print(f"FAIL {exc}")
        return 3
    print(("ok   " if status.ok else "FAIL ") + status.summary())
    return 0 if status.ok else 1


def render_daemon_plist(
    user: str,
    home: Path,
    uv_path: str,
    repo_root: Path = REPO_ROOT,
    template: Path = DAEMON_PLIST,
) -> str:
    """Fill a LaunchDaemon template. The job starts at boot but runs as ``user``, so the
    database, the uv cache and the Claude Code login all stay that user's."""
    return (
        template.read_text(encoding="utf-8")
        .replace("__REPO_ROOT__", str(repo_root))
        .replace("__UV_PATH__", uv_path)
        .replace("__USER__", user)
        .replace("__HOME__", str(home))
    )


def cmd_install_daemon(args: argparse.Namespace, settings: Settings) -> int:
    user = getpass.getuser()
    if user == "root":
        print(
            "Run `make install-daemon` as your normal user, not with sudo: the bot must run "
            "as the account that owns the repository and is logged in to Claude Code.",
            file=sys.stderr,
        )
        return 2
    uv_path = shutil.which("uv") or "/opt/homebrew/bin/uv"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[Path] = []
    for template in (DAEMON_PLIST, BACKUP_PLIST):
        out = out_dir / template.name
        rendered_text = render_daemon_plist(user, Path.home(), uv_path, template=template)
        out.write_text(rendered_text, encoding="utf-8")
        rendered.append(out)
    print(f"Rendered LaunchDaemon plists to {out_dir} (both run as {user}):")
    print(f"  {rendered[0].name}: the Telegram bot, started at boot")
    print(f"  {rendered[1].name}: the nightly database backup at 03:17")
    if settings.claude_code_oauth_token is None:
        print(
            "\nwarning: CLAUDE_CODE_OAUTH_TOKEN is not set in .env. Before anyone logs in "
            "after a reboot the macOS keychain is locked, so `claude -p` cannot read your "
            "login. Run `claude setup-token` and put the token in .env."
        )
    print("\nInstall them with (requires sudo; see deploy/README.md):")
    print("  sudo mkdir -p /Library/Logs/recipe-mcp")
    print(f"  sudo chown {user} /Library/Logs/recipe-mcp")
    for out in rendered:
        target = Path("/Library/LaunchDaemons") / out.name
        print(f"  sudo cp {out} {target}")
        print(f"  sudo launchctl bootstrap system {target}")
    print("(If one is already installed, `sudo launchctl bootout system/<label>` it first.)")
    return 0


def cmd_backup(args: argparse.Namespace, settings: Settings) -> int:
    from datetime import date

    from recipe_mcp.db.backup import BackupError
    from recipe_mcp.services.backups import run_backup

    if settings.database_path is None:
        print("The database is in memory; there is nothing to back up.", file=sys.stderr)
        return 2
    try:
        result = run_backup(
            settings.database_path, settings.backup_dir, settings.backup_keep, date.today()
        )
    except BackupError as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 1
    print(f"Backed up {settings.database_path} to {result.path} ({result.size_bytes:,} bytes)")
    for old in result.removed:
        print(f"  removed {old.name} (keeping {settings.backup_keep})")
    return 0


def cmd_eval(args: argparse.Namespace, settings: Settings) -> int:
    from recipe_mcp.services.evals import run_evals

    private = settings.private_evals_path
    if private.exists():
        ctx = _ctx(settings)
        try:
            report = run_evals(live_ctx=ctx, private_path=private)
        finally:
            ctx.close()
    else:
        report = run_evals()
    print(report.render())
    return 0 if report.passed else 1


def cmd_smoke(args: argparse.Namespace, settings: Settings) -> int:
    """Opt-in live checks. Each reports missing configuration by name and skips."""
    failures = 0
    ran = 0
    print("Live smoke tests (opt-in):")
    missing = settings.missing_for("model")
    if missing:
        print(f"  skip model: missing {', '.join(missing)}")
    else:
        ran += 1
        try:
            from recipe_mcp.providers.base import RecipeClassificationInput
            from recipe_mcp.providers.factory import build_model_client

            client = build_model_client(settings)
            data = fixtures.load_yaml(fixtures.TUNA_FIXTURE)
            response = client.classify_recipe(
                RecipeClassificationInput(
                    title="Tuna Quinoa Salad", ingredients=data["expected"]["ingredients"]
                )
            )
            print(
                f"  ok   model classification via {response.provider}/{response.model} "
                f"in {response.latency_ms} ms: dish={response.output.dish_type}"
            )
        except Exception as exc:  # pragma: no cover - live path
            failures += 1
            print(f"  FAIL model: {exc.__class__.__name__}: {exc}")
    if args.nyt_url:
        ran += 1
        try:
            from recipe_mcp.adapters.nyt import HttpRecipeFetcher, parse_recipe_jsonld

            fetched = HttpRecipeFetcher().fetch(args.nyt_url)
            parsed = parse_recipe_jsonld(fetched.html)
            if parsed is None:
                raise RuntimeError("no JSON-LD recipe found (authentication may be required)")
            print(f"  ok   nyt fetch: {parsed.title} ({len(parsed.ingredients)} ingredients)")
        except Exception as exc:  # pragma: no cover - live path
            failures += 1
            print(f"  FAIL nyt: {exc.__class__.__name__}: {exc}")
    else:
        print("  skip nyt: pass --nyt-url to test a live fetch")
    missing = settings.missing_for("telegram")
    if missing:
        print(f"  skip telegram: missing {', '.join(missing)}")
    else:
        ran += 1
        try:
            from recipe_mcp.adapters.telegram import HttpTelegramApi

            assert settings.telegram_bot_token is not None
            api = HttpTelegramApi(settings.telegram_bot_token.get_secret_value())
            me = api.get_me()
            api.send_message(
                settings.telegram_group_chat_id or 0,
                "recipe-mcp smoke test: the bot can reach this group.",
            )
            print(f"  ok   telegram: @{me.get('username')} posted to the household group")
        except Exception as exc:  # pragma: no cover - live path
            failures += 1
            print(f"  FAIL telegram: {exc.__class__.__name__}: {exc}")
    missing = settings.missing_for("brain")
    if missing:
        print(f"  skip brain: missing {', '.join(missing)}")
    elif args.brain:
        ran += 1
        from recipe_mcp.providers.agent_brain import BrainRequest

        reply = _build_brain(settings).reply(
            BrainRequest(
                chat_id="smoke",
                member_key=settings.default_member or None,
                display_name="smoke test",
                text="Recommend something cozy under 45 minutes.",
            )
        )
        if reply.error:
            failures += 1
            print(f"  FAIL brain: {reply.error}")
            # Your own terminal, not the daemon log, so the details are safe to show here.
            if reply.diagnostic:
                print(f"       {reply.diagnostic}")
        else:
            print(
                f"  ok   brain replied in {reply.duration_ms} ms, recipes {reply.recipe_ids}: "
                f"{reply.text[:120]!r}"
            )
    else:
        print("  skip brain: pass --brain to run one headless Claude Code reply")
    if ran == 0:
        print("\nNothing ran: add credentials to .env to enable live checks.")
        return 1
    return 1 if failures else 0


def cmd_import_whatsapp(args: argparse.Namespace, settings: Settings) -> int:
    path = Path(args.path) if args.path else settings.whatsapp_export_path
    if not path.exists():
        print(f"export not found: {path} (set WHATSAPP_EXPORT_PATH or pass --path)")
        return 1
    ctx = _ctx(settings)
    try:
        if args.dry_run:
            for entry in ctx.whatsapp_import.plan(path):
                who = f" ({entry.member_key})" if entry.member_key else ""
                print(f"{entry.status:20} {entry.canonical_url}{who}")
            return 0
        report = ctx.whatsapp_import.run(path)
        out = Path(args.report) if args.report else Path(".private/import-report.md")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report.to_markdown(), encoding="utf-8")
        for status, n in sorted(report.counts().items()):
            print(f"{status}: {n}")
        print(f"report written to {out}")
        return 0
    finally:
        ctx.close()


def cmd_categorize(args: argparse.Namespace, settings: Settings) -> int:
    ctx = _ctx(settings)
    try:
        changed = ctx.recipes.refresh_staples(staples.reload())
        if changed:
            print(f"staples re-applied: {changed} ingredient(s) changed")
        outcomes = ctx.categorization.categorize_uncategorized(ctx.household_id)
        for o in outcomes:
            flag = " (review)" if o.needs_review else ""
            print(f"{o.recipe.id}: {o.recipe.title}{flag}")
            for w in o.warnings:
                print(f"    warning: {w}")
        print(f"categorized {len(outcomes)} recipe(s)")
        return 0
    except MissingConfigError as exc:
        print(str(exc))
        return 1
    finally:
        ctx.close()


def cmd_refresh_dietary(args: argparse.Namespace, settings: Settings) -> int:
    ctx = _ctx(settings)
    try:
        changes = ctx.categorization.refresh_dietary(ctx.household_id, apply=not args.dry_run)
        for c in changes:
            diet = (
                f"{dietary.strictest(c.before)} -> {dietary.strictest(c.after)}"
                if c.dietary_changed
                else f"{dietary.strictest(c.after)} (unchanged)"
            )
            print(f"{c.recipe_id}: {c.title} — {diet}")
            for name in c.removed:
                print(f"    - {name}")
            for name in c.added:
                print(f"    + {name}")
        changed = sum(1 for c in changes if c.dietary_changed)
        verb = "would change" if args.dry_run else "changed"
        print(
            f"dietary {verb} for {changed} recipe(s); "
            f"ingredients re-parsed for {len(changes)} recipe(s)"
        )
        return 0
    finally:
        ctx.close()


def cmd_categorization_report(args: argparse.Namespace, settings: Settings) -> int:
    ctx = _ctx(settings)
    try:
        text = ctx.categorization.report(ctx.household_id)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            print(f"report written to {args.out}")
        else:
            print(text)
        return 0
    finally:
        ctx.close()


def cmd_correct(args: argparse.Namespace, settings: Settings) -> int:
    ctx = _ctx(settings)
    try:
        member = ctx.resolve_member(args.member)
        result = ctx.corrections.correct(
            args.recipe_id,
            facet_corrections={args.facet: args.values},
            member_id=member.id if member else None,
        )
        for change in result.changes:
            print(change)
        return 0
    finally:
        ctx.close()


def cmd_save(args: argparse.Namespace, settings: Settings) -> int:
    ctx = _ctx(settings)
    try:
        member = ctx.resolve_member(args.member)
        result = ctx.ingestion.save(
            args.text, notes=args.notes, member_id=member.id if member else None
        )
        print(result.confirmation())
        for w in result.warnings:
            print(f"warning: {w}")
        return 0
    except MissingConfigError as exc:
        print(str(exc))
        return 1
    finally:
        ctx.close()


def cmd_recommend(args: argparse.Namespace, settings: Settings) -> int:
    ctx = _ctx(settings)
    try:
        member = ctx.resolve_member(args.member)
        request, results = ctx.recommendation.recommend_from_text(
            args.text, member.id if member else None
        )
        print(f"constraints: {json.dumps(request.model_dump(exclude_defaults=True))}\n")
        _print_results(results)
        return 0
    except MissingConfigError as exc:
        print(str(exc))
        return 1
    finally:
        ctx.close()


def cmd_add_member(args: argparse.Namespace, settings: Settings) -> int:
    ctx = _ctx(settings)
    try:
        member = ctx.members.upsert(
            Member(
                household_id=ctx.household_id,
                member_key=args.key,
                display_name=args.name or args.key.capitalize(),
                telegram_user_id=args.telegram_user_id,
                whatsapp_export_name=args.export_name,
            )
        )
        print(f"member {member.member_key} ({member.display_name}) ready, id {member.id}")
        print(f"tip: declare members in {settings.members_path} so they survive a fresh database")
        return 0
    finally:
        ctx.close()


def cmd_rate(args: argparse.Namespace, settings: Settings) -> int:
    ctx = _ctx(settings)
    try:
        member = ctx.resolve_member(args.member)
        if member is None or member.id is None:
            print(f"unknown member {args.member}")
            return 1
        summary = ctx.feedback_service.rate(args.recipe_id, member.id, Sentiment(args.sentiment))
        print(json.dumps(summary.model_dump(), indent=2))
        return 0
    finally:
        ctx.close()


def cmd_list(args: argparse.Namespace, settings: Settings) -> int:
    ctx = _ctx(settings)
    try:
        for r in ctx.recipes.list_for_household(ctx.household_id):
            time = f"{r.total_minutes} min" if r.total_minutes else "?"
            kind = r.source_type.value if r.is_recommendable else "link"
            print(f"{r.id:4}  {r.title[:45]:45} {time:>8}  {r.status.value:8} {kind}")
        return 0
    finally:
        ctx.close()


# -- parser -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="recipe-mcp", description="Household recipe assistant")
    parser.add_argument("--version", action="version", version=f"recipe-mcp {__version__}")
    parser.add_argument("--env-file", default=".env", help="path to .env (default: .env)")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str, fn: Handler) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(fn=fn)
        return p

    add("init-db", "create the database and apply migrations", cmd_init_db)
    add("doctor", "diagnose configuration without printing secrets", cmd_doctor)
    add("demo", "load synthetic recipes and run a sample query", cmd_demo)
    add("serve", "run the MCP server over stdio", cmd_serve)
    add("serve-telegram", "run the Telegram long-polling host", cmd_serve_telegram)
    nyt = add("nyt-login", "one-time interactive NYT Cooking sign-in", cmd_nyt_login)
    nyt.add_argument(
        "--timeout", type=float, default=300.0, help="seconds to wait for sign-in (default: 300)"
    )
    nyt.add_argument("--force", action="store_true", help="sign in again even if a session exists")
    daemon = add("install-daemon", "render the launchd plists for the Mac mini", cmd_install_daemon)
    daemon.add_argument("--out-dir", default=".private", help="where to write the rendered plists")
    add("backup", "back up the database and keep the newest BACKUP_KEEP copies", cmd_backup)
    add("eval", "run the synthetic (and private, if present) evaluation sets", cmd_eval)
    smoke = add("smoke", "opt-in live smoke tests", cmd_smoke)
    smoke.add_argument("--nyt-url", help="NYT Cooking recipe URL to fetch live")
    smoke.add_argument("--brain", action="store_true", help="run one headless Claude Code reply")

    imp = add("import-whatsapp", "import recipe links from a WhatsApp export", cmd_import_whatsapp)
    imp.add_argument("--path", help="export file (default: WHATSAPP_EXPORT_PATH)")
    imp.add_argument("--report", help="where to write the Markdown report")
    imp.add_argument("--dry-run", action="store_true", help="list links without importing")

    add("categorize", "re-apply staples and categorize uncategorized recipes", cmd_categorize)
    rdiet = add(
        "refresh-dietary",
        "re-parse stored ingredients and re-run the dietary rules",
        cmd_refresh_dietary,
    )
    rdiet.add_argument("--dry-run", action="store_true", help="report changes without writing")
    rep = add("categorization-report", "Markdown review report", cmd_categorization_report)
    rep.add_argument("--out", help="write to a file instead of stdout")

    cor = add("correct", "record a classification correction", cmd_correct)
    cor.add_argument("recipe_id", type=int)
    cor.add_argument("facet", choices=[f.value for f in Facet if f != Facet.DIETARY])
    cor.add_argument("values", nargs="+")
    cor.add_argument("--member", help="member key (defaults to DEFAULT_MEMBER)")

    save = add("save", "save a recipe from a URL or description", cmd_save)
    save.add_argument("text")
    save.add_argument("--notes")
    save.add_argument("--member", help="member key (defaults to DEFAULT_MEMBER)")

    rec = add("recommend", "recommend from a natural-language request", cmd_recommend)
    rec.add_argument("text")
    rec.add_argument("--member", help="member key; omit for the household view")

    mem = add("add-member", "add or update a household member", cmd_add_member)
    mem.add_argument("key", help="short member key, e.g. alex")
    mem.add_argument("--name", help="display name")
    mem.add_argument("--telegram-user-id", type=int, help="numeric Telegram user id")
    mem.add_argument("--export-name", help="sender name as it appears in the WhatsApp export")

    rate = add("rate", "rate a recipe as a member", cmd_rate)
    rate.add_argument("recipe_id", type=int)
    rate.add_argument("member")
    rate.add_argument("sentiment", choices=[s.value for s in Sentiment])

    add("list", "list stored recipes", cmd_list)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_file = args.env_file if Path(args.env_file).exists() else None
    settings = load_settings(env_file=env_file)
    handler: Handler = args.fn
    try:
        return handler(args, settings)
    except MissingConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
