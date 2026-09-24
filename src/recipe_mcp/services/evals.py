"""Fixture-based offline evaluation of recommendation and personal-recipe parsing."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from recipe_mcp.domain.models import RecommendationRequest
from recipe_mcp.domain.taxonomy import Facet
from recipe_mcp.providers.fake import FakeModelClient
from recipe_mcp.services import fixtures
from recipe_mcp.services.container import AppContext, build_context
from recipe_mcp.settings import load_settings


@dataclass
class QueryResult:
    query_id: str
    text: str
    passed: bool
    skipped: bool = False
    reason: str = ""
    top: list[str] = field(default_factory=list)
    constraint_mismatches: list[str] = field(default_factory=list)


@dataclass
class PrivateEvalReport:
    """Results for the household's private evaluation set (never committed)."""

    path: Path
    queries: list[QueryResult] = field(default_factory=list)
    corrections_checked: int = 0
    corrections_failed: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.corrections_failed and all(q.passed for q in self.queries if not q.skipped)


@dataclass
class EvalReport:
    queries: list[QueryResult] = field(default_factory=list)
    draft_passed: bool = False
    draft_issues: list[str] = field(default_factory=list)
    private: PrivateEvalReport | None = None

    @property
    def passed(self) -> bool:
        core = self.draft_passed and all(q.passed for q in self.queries if not q.skipped)
        return core and (self.private is None or self.private.passed)

    def render(self) -> str:
        lines = ["Synthetic evaluation set (public)", ""]
        lines.append("Recommendation queries (typed constraints, expected recipe in top 3):")
        for q in self.queries:
            if q.skipped:
                lines.append(f"  SKIP {q.query_id}: {q.text} ({q.reason})")
                continue
            mark = "PASS" if q.passed else "FAIL"
            lines.append(f"  {mark} {q.query_id}: {q.text}")
            lines.append(f"       top: {', '.join(q.top) or '(none)'}")
            for m in q.constraint_mismatches:
                lines.append(f"       constraint extraction (fake model): {m}")
        hits = sum(1 for q in self.queries if q.passed and not q.skipped)
        total = sum(1 for q in self.queries if not q.skipped)
        lines.append(f"  {hits}/{total} queries returned an expected recipe in the top three")
        lines.append("")
        lines.append("Personal recipe draft (tuna quinoa salad):")
        lines.append("  PASS" if self.draft_passed else "  FAIL")
        for issue in self.draft_issues:
            lines.append(f"    - {issue}")
        lines.append("")
        if self.private is None:
            lines.append("Private evaluation set: not present (PRIVATE_EVALS_PATH), skipped")
        else:
            p = self.private
            lines.append(f"Private evaluation set ({p.path})")
            for q in p.queries:
                mark = "PASS" if q.passed else "FAIL"
                lines.append(f"  {mark} {q.query_id}: {q.text}")
            lines.append(
                f"  corrections replayed: {p.corrections_checked}, "
                f"regressions: {len(p.corrections_failed)}"
            )
            for failure in p.corrections_failed:
                lines.append(f"    - {failure}")
        return "\n".join(lines)


def _eval_context() -> AppContext:
    settings = load_settings(
        env_file=None, database_url="sqlite:///:memory:", model_provider="fake"
    )
    return build_context(settings, model=FakeModelClient())


def _resolve_diners(ctx: AppContext, spec: Any) -> list[int]:
    if spec == "household":
        return [m.id for m in ctx.members.list_for_household(ctx.household_id) if m.id]
    if isinstance(spec, list):
        out: list[int] = []
        for name in spec:
            member = ctx.members.by_name(ctx.household_id, str(name))
            if member and member.id:
                out.append(member.id)
        return out
    return []


def run_queries(
    ctx: AppContext, queries_path: Path = fixtures.INITIAL_QUERIES
) -> list[QueryResult]:
    results: list[QueryResult] = []
    fake = FakeModelClient()
    for q in fixtures.load_yaml(queries_path)["queries"]:
        if q.get("skip"):
            results.append(
                QueryResult(
                    query_id=q["id"], text=q["text"], passed=True, skipped=True, reason=q["skip"]
                )
            )
            continue
        constraints = dict(q.get("constraints", {}))
        diners = _resolve_diners(ctx, constraints.pop("diners", None))
        request = RecommendationRequest(**constraints, diners=diners)
        recs = ctx.recommendation.recommend(request)
        top = [r.title for r in recs]
        expected = q.get("expected_any", [])
        passed = bool(set(top) & set(expected)) if expected else len(top) > 0
        mismatches: list[str] = []
        extracted = fake.interpret_query(q["text"]).output
        for key, want in q.get("expected_constraints", {}).items():
            got = getattr(extracted, key, None)
            if isinstance(want, list):
                if sorted(map(str, want)) != sorted(map(str, got or [])):
                    mismatches.append(f"{key}: expected {want}, got {got}")
            elif got != want:
                mismatches.append(f"{key}: expected {want!r}, got {got!r}")
        results.append(
            QueryResult(
                query_id=q["id"],
                text=q["text"],
                passed=passed,
                top=top,
                constraint_mismatches=mismatches,
            )
        )
    return results


def run_draft_check(
    ctx: AppContext, fixture_path: Path = fixtures.TUNA_FIXTURE
) -> tuple[bool, list[str]]:
    data = fixtures.load_yaml(fixture_path)
    result = ctx.ingestion.save_personal(data["input"])
    recipe = result.recipe
    expected = data["expected"]
    issues: list[str] = []
    got_ingredients = sorted(i.canonical_name for i in recipe.ingredients)
    if got_ingredients != sorted(expected["ingredients"]):
        issues.append(
            f"ingredients: expected {sorted(expected['ingredients'])}, got {got_ingredients}"
        )
    if recipe.total_minutes != expected.get("total_minutes"):
        issues.append(
            f"total_minutes: expected {expected.get('total_minutes')}, got {recipe.total_minutes}"
        )
    if recipe.status.value != expected["status"]:
        issues.append(f"status: expected {expected['status']}, got {recipe.status.value}")
    for word in expected.get("title_contains", []):
        if word.lower() not in recipe.title.lower():
            issues.append(f"title should mention {word!r}: got {recipe.title!r}")
    diets = recipe.facet_values(Facet.DIETARY)
    for diet in expected.get("dietary_suitability", []):
        if diet not in diets:
            issues.append(f"dietary should include {diet}: got {diets}")
    for diet in expected.get("dietary_not", []):
        if diet in diets:
            issues.append(f"dietary must not include {diet}")
    if expected.get("dish_type") and expected["dish_type"] not in recipe.facet_values(
        Facet.DISH_TYPE
    ):
        issues.append(
            f"dish_type: expected {expected['dish_type']}, "
            f"got {recipe.facet_values(Facet.DISH_TYPE)}"
        )
    for note in expected.get("notes_contain", []):
        if not any(note.lower() in n.lower() for n in recipe.notes):
            issues.append(f"notes should mention {note!r}: got {recipe.notes}")
    for forbidden in expected.get("must_not_contain", []):
        blob = " ".join([recipe.title, *recipe.notes, *(i.raw_text for i in recipe.ingredients)])
        if forbidden.lower() in blob.lower():
            issues.append(f"invented detail present: {forbidden!r}")
    return (not issues), issues


def run_private_evals(ctx: AppContext, path: Path) -> PrivateEvalReport:
    """Replay the household's private queries and corrections against the live database.

    ``queries.yaml`` uses the same format as the synthetic set. ``corrections.jsonl``
    is appended by ``correct_recipe``; each case must still hold in the database.
    """
    report = PrivateEvalReport(path=path)
    queries_file = path / "queries.yaml"
    if queries_file.exists():
        report.queries = run_queries(ctx, queries_file)
    corrections_file = path / "corrections.jsonl"
    if corrections_file.exists():
        for line in corrections_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            case = json.loads(line)
            report.corrections_checked += 1
            recipe = ctx.recipes.get(int(case["recipe_id"]))
            if recipe is None:
                report.corrections_failed.append(f"recipe {case['recipe_id']} missing")
                continue
            expected = case.get("expected", {})
            for facet_name, values in expected.get("facets", {}).items():
                got = recipe.facet_values(Facet(facet_name))
                if sorted(got) != sorted(values):
                    report.corrections_failed.append(
                        f"recipe {recipe.id} {facet_name}: expected {values}, got {got}"
                    )
            if "total_minutes" in expected and recipe.total_minutes != expected["total_minutes"]:
                report.corrections_failed.append(
                    f"recipe {recipe.id} total_minutes: expected {expected['total_minutes']}, "
                    f"got {recipe.total_minutes}"
                )
    return report


def run_evals(live_ctx: AppContext | None = None, private_path: Path | None = None) -> EvalReport:
    """Run the synthetic set in an isolated in-memory context; run the private set, when
    present, against the real database passed as ``live_ctx``."""
    ctx = _eval_context()
    try:
        fixtures.seed_demo(ctx)
        report = EvalReport(queries=run_queries(ctx))
        report.draft_passed, report.draft_issues = run_draft_check(ctx)
    finally:
        ctx.close()
    if live_ctx is not None and private_path is not None and private_path.exists():
        report.private = run_private_evals(live_ctx, private_path)
    return report
