# DoubleM Financial

Telegram-first, self-hosted portfolio and market-risk assistant. Python, PostgreSQL and systemd. No web frontend, container runtime, Coolify or brokerage execution is required.

## Included

- Telegram commands for a manually maintained portfolio, quotes, macro data, refresh and status.
- PostgreSQL persistence for holdings, current quotes and macro metrics.
- Optional connectors: FRED, Twelve Data and Finnhub. Missing keys or exhausted quota are reported as unavailable.
- Daily risk-feature foundation. Probabilities remain disabled until a model is trained and validated walk-forward.
- Native Ubuntu deployment with systemd, SSH-based updates, journald logs and PostgreSQL backups.
- Docker Compose remains available only as an optional legacy/local deployment; it is not used by the SSH installation.
- No automated trading, order submission or portfolio rebalancing.

## Deploy on an Ubuntu 24.04 VPS over SSH

Connect to the VPS as a sudo-capable user. The installer requires root privileges and installs Python, PostgreSQL and Git. It creates a dedicated `doublem` system user, a local PostgreSQL database, a Python virtual environment and a systemd unit. It does not install Coolify, Docker, a web server or expose an inbound port.

```bash
sudo apt-get update
sudo apt-get install -y git
sudo git clone --branch main https://github.com/lmworkod/doubleMfinancial.git /opt/doublemfinancial
sudo bash /opt/doublemfinancial/scripts/install-ubuntu.sh
```

Edit the environment file on the VPS (do not commit or share it):

```bash
sudo nano /etc/doublemfinancial/doublem.env
```

Set at least:
- `TELEGRAM_BOT_TOKEN`: token from [@BotFather](https://t.me/BotFather).
- `TELEGRAM_ALLOWED_USER_IDS`: your numeric Telegram user ID(s), comma-separated. All users are denied when empty.
- `DATABASE_URL`: keep the local socket URL created by the installer unless you intentionally use another database.
- `FRED_API_KEY`: optional free key for macro data.
- `TWELVE_DATA_API_KEY`, `FINNHUB_API_KEY`: optional market sources.

The installer creates the service but does not start it until credentials are configured. Then run:

```bash
sudo systemctl start doublem
sudo systemctl status doublem --no-pager
sudo journalctl -u doublem -n 100 --no-pager
```

## SSH operations

```bash
# Follow logs
sudo journalctl -u doublem -f

# Restart / stop / start
sudo systemctl restart doublem
sudo systemctl stop doublem
sudo systemctl start doublem

# Check service and PostgreSQL
sudo systemctl is-active doublem
sudo systemctl is-active postgresql

# Deploy latest main (fast-forward only, installs dependencies and restarts)
sudo bash /opt/doublemfinancial/scripts/deploy.sh

# Back up PostgreSQL to /var/backups/doublemfinancial
sudo bash /opt/doublemfinancial/scripts/backup.sh
```

The deployment script refuses to proceed if the working tree has local modifications and uses `git pull --ff-only`. It does not delete data or perform destructive database migrations. Take a backup before upgrades and test restoration periodically. For a manual rollback, check out a known-good commit and reinstall it before restarting the service.

## Local development

```bash
cp .env.example .env
# Set credentials and a suitable DATABASE_URL
pip install -e '.[dev]'
ruff check .
pytest -q
```

## Telegram commands

`/start`, `/help`, `/portfolio`, `/add SYMBOL QUANTITY [AVERAGE_COST]`, `/remove SYMBOL`, `/analyze SYMBOL`, `/watchlist`, `/opportunities`, `/risk`, `/macro`, `/refresh`, `/status`.

Positions are entered manually; there is no broker connection. Valuation includes only positions with a stored quote and excludes cash, FX conversion and fees.

## Data and model limits

Free APIs have changing quotas, market coverage and usage terms. Provider timestamps and market entitlements are authoritative; HTTP success alone does not prove data is real-time. The request budget is conservative but process-local.

This initial release has no approved historical training dataset or fitted SP500-VRM coefficients. It deliberately reports an uncalibrated model instead of fabricating probabilities. Risk features are a foundation, not an investment signal. No financial action is executed automatically.

## Operations and security

The bot uses Telegram long polling and needs no public inbound port. The health endpoint listens on localhost only. Credentials live in `/etc/doublemfinancial/doublem.env`, outside the repository, with restricted permissions. The systemd service runs as the unprivileged `doublem` user and logs to journald. Missing or stale data is never interpreted as zero risk.
