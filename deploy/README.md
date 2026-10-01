# Running on an always-on Mac

The bot needs an always-on Mac (Mac mini, iMac or a laptop that stays awake); it is the
only runtime host (SPEC.md section 19A). The daemon uses launchd, so this guide is macOS
only; Linux or cloud hosting is an idea in IDEAS.md. The Telegram host runs as
a LaunchDaemon so it starts without a user session; the MCP server is not a daemon and
is spawned over stdio by the Telegram host, Codex or Claude Code on demand.

## Machine

- macOS with `uv` installed (`brew install uv`); `uv` fetches Python 3.13 itself.
- System Settings > Energy: never sleep, wake for network access, start up
  automatically after a power failure.
- Tailscale only if you want the optional shortcut endpoint or remote MCP access.
  Nothing else is exposed to the network; long polling makes outbound HTTPS calls only.

## First install

```bash
git clone https://github.com/DHJ2019/recipe-mcp.git /path/to/recipe-mcp
cd /path/to/recipe-mcp
make setup
```

Fill in `.env` (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS`,
`TELEGRAM_GROUP_CHAT_ID`, model key) and `.private/members.yaml`, then:

```bash
make doctor
```

## Daemon

`make install-daemon` (run as your normal user, not with sudo) renders two plists from
`deploy/` with the repository path, the `uv` binary, your user name and home directory
filled in, writes them to `.private/`, and prints the `sudo` commands to create
`/Library/Logs/recipe-mcp/`, copy them to `/Library/LaunchDaemons` and bootstrap them:

- `com.recipe-mcp.telegram.plist`: the bot, started at boot and kept running.
- `com.recipe-mcp.backup.plist`: the nightly database backup (see "Backups" below).

It is a LaunchDaemon, so it starts at boot without anyone logging in, but the plist's
`UserName` makes it run as you. That keeps `data/recipes.db`, the `uv` cache and the
Claude Code login owned by your account; running it as root would leave root-owned
database files that your own Claude Code sessions could no longer write.
`KeepAlive` restarts the host if it exits; `RunAtLoad` starts it at boot.

**Claude Code authentication at boot.** Claude Code keeps its login in the macOS
keychain, which stays locked until you log in. So that the bot works straight after a
reboot, create a long-lived token once and put it in `.env`:

```bash
claude setup-token
```

Paste the printed token into `.env` as `CLAUDE_CODE_OAUTH_TOKEN=...`. `uv run --env-file
.env` exports it to the headless `claude -p` runs. `make doctor` shows it as set or unset.

Useful commands:

```bash
sudo launchctl print system/com.recipe-mcp.telegram
```

```bash
sudo launchctl kickstart -k system/com.recipe-mcp.telegram
```

```bash
tail -f /Library/Logs/recipe-mcp/telegram.log
```

The plist's `PATH` includes `/opt/homebrew/bin`; if `claude` lives elsewhere set
`CLAUDE_CODE_BIN` in `.env` to its full path.

If you already installed an older plist that ran as root, remove it first and give the
database back to your user:

```bash
sudo launchctl bootout system/com.recipe-mcp.telegram
```

```bash
sudo chown -R "$(whoami)" data .venv
```

## NYT session

`make nyt-login` is a one-time headed browser sign-in whose session lives in
`NYT_BROWSER_PROFILE_PATH` under `.private/`. No password is stored; `make doctor`
reports the expiry date and warns once the cookie has lapsed.

It needs a desktop session, so run it over screen sharing rather than SSH, and re-run it
whenever `doctor` reports the session as expired. The daemon itself never opens a browser
window: it reuses the stored profile headlessly, and falls back to it only when an
anonymous fetch comes back without recipe data.

## Operations

- `make doctor` after any change or reboot.
- `make smoke` for live checks (model, NYT, and a test message to the Telegram group).
- Backups: see "Backups" below.
- Classifying older recipes: new links are classified as they are shared; for recipes
  saved before that, run `make classify-backlog ARGS=--dry-run`, then
  `make classify-backlog ARGS="--limit 5"`, then without a limit. It can run while the
  bot is up.
- Planned restarts with FileVault on: `sudo fdesetup authrestart` (see the main README).
- Upgrades: `git pull`, `uv sync`, `make test`, then kickstart the daemon.

## Backups

`com.recipe-mcp.backup` runs `recipe-mcp backup` every night at 03:17 as your user. It
copies `data/recipes.db` with SQLite's online backup API, which is safe while the bot is
running, to `.private/backups/recipes-YYYY-MM-DD.db` (mode 600), checks the copy's
integrity before keeping it, and keeps the newest 14 (`BACKUP_DIR` and `BACKUP_KEEP` in
`.env`). `make backup` runs the same thing by hand. `make doctor` warns when there is no
backup or the newest is more than 36 hours old; the job's output goes to
`/Library/Logs/recipe-mcp/backup.log`.

If you installed the bot before the backup job existed, add just the backup job:

```bash
make install-daemon
sudo cp .private/com.recipe-mcp.backup.plist /Library/LaunchDaemons/
sudo launchctl bootstrap system /Library/LaunchDaemons/com.recipe-mcp.backup.plist
```

To test it straight away: `sudo launchctl kickstart system/com.recipe-mcp.backup`.

The backups sit on the same disk as the database, so they cover mistakes and a damaged
database file, not a failed disk. Let Time Machine (or another off-machine copy) include
`.private/backups/`; the copies hold the whole household collection, so keep that
destination private too.

**Restoring.** Stop the bot, put the backup in place of the database (removing the old
`-wal` and `-shm` files with it), then start the bot again:

```bash
sudo launchctl bootout system/com.recipe-mcp.telegram
mv data/recipes.db data/recipes.db.broken
rm -f data/recipes.db-wal data/recipes.db-shm
cp .private/backups/recipes-YYYY-MM-DD.db data/recipes.db
chmod 600 data/recipes.db
sudo launchctl bootstrap system /Library/LaunchDaemons/com.recipe-mcp.telegram.plist
make doctor
```
