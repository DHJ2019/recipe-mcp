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

`make install-daemon` (run as your normal user, not with sudo) renders
`deploy/com.recipe-mcp.telegram.plist` with the repository path, the `uv` binary, your
user name and home directory filled in, writes it to `.private/`, and prints the `sudo`
commands to create `/Library/Logs/recipe-mcp/`, copy the plist to `/Library/LaunchDaemons`
and bootstrap it.

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
- Backups: an automatic nightly backup is not built yet (see IDEAS.md). Until then:
  `sqlite3 data/recipes.db ".backup .private/backups/recipes-$(date +%F).db"`.
- Planned restarts with FileVault on: `sudo fdesetup authrestart` (see the main README).
- Upgrades: `git pull`, `uv sync`, `make test`, then kickstart the daemon.
