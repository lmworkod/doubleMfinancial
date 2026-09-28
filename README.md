# DoubleM Financial

Telegram-first, self-hosted portfolio and market-risk assistant. Python, PostgreSQL and systemd. No web frontend, container runtime, Coolify or brokerage execution is required.

## Included

- Telegram commands for a manually maintained portfolio, quotes, macro data, refresh and status.
- PostgreSQL persistence for holdings, current quotes and macro metrics.
- Optional connectors: FRED, Twelve Data and Finnhub. Provider failures are classified, transient failures receive bounded retries, and previous valid data is retained when a refresh cannot obtain a new value.
- Free fallback for daily closes of explicitly allowlisted US tickers via Stooq, plus Frankfurter as an unauthenticated FX fallback to the ECB.
- ISIN-to-listed-symbol mapping for selected UCITS ETFs. Provider coverage is checked at runtime; unknown ISINs are not sent as exchange tickers.
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

Positions are entered manually; there is no broker connection. Valuation includes only positions with a stored quote that can be converted to EUR; cash and fees are excluded. USD positions use the latest stored ECB/Frankfurter USD-per-EUR reference rate.

## Instrument mapping

The database keeps the ISIN as the holding identifier; the market-data layer resolves supported ISINs to provider tickers. The mapping lives in `app/instruments.py`. Provider results are not guaranteed by the presence of a mapping: data coverage, symbol syntax and entitlements depend on each provider. Instruments without a verified mapping remain unavailable instead of being queried under an invalid ticker.

The current mapping includes First Trust Clean Smart Infrastructure (IE000J80JTL1, GRID), Global X Copper Miners (IE0003Z9E2Y3, COPX), Global X Silver Miners (IE000UL6CLP7, SILV), VanEck Space Innovators (IE000YU9K6K2, JEDI), WisdomTree Strategic Metals and Rare Earths Miners (IE000KHX9DX6, RARE), iShares Physical Gold ETC (IE00B4ND3602, PPFB on Xetra) and VanEck Uranium and Nuclear Technologies UCITS ETF (IE000M7V94E1, NUKL on Xetra). Only Twelve Data symbols are configured for these mapped ISINs. Finnhub's ordinary quote endpoint is used only for regular tickers; its international real-time data requires higher-tier access.

The Stooq fallback is deliberately restricted to SPY, QQQ and IWM and returns daily bars, not live quotes. It does not guess exchange suffixes for European instruments. Stooq access/quota and redistribution terms can change; validate the provider's terms and current API access before relying on it. Frankfurter provides daily FX reference rates without an API key and is used only when the ECB fetch fails. FX rates are reference rates, not execution rates.

Yahoo Finance/yfinance is not enabled as a production fallback: yfinance warns that it relies on publicly available endpoints and is intended for personal use; confirm permission before incorporating it into a deployed application. Official LBMA gold benchmark data may require a licence for valuation use. For the iShares Physical Gold ETC, the preferred value remains the actual exchange-listed ETC quote rather than a synthetic XAU conversion.

## Data and model limits

Free APIs have changing quotas, market coverage and usage terms. Provider timestamps and market entitlements are authoritative; HTTP success alone does not prove data is real-time. The request budget is conservative but process-local. Refresh retries only transient network, timeout, throttling and server failures a bounded number of times. Authentication, permission and symbol errors are not retried. When a new value cannot be fetched, the last valid value is kept and reported as stale rather than being overwritten.

This initial release has no approved historical training dataset or fitted SP500-VRM coefficients. It deliberately reports an uncalibrated model instead of fabricating probabilities. Risk features are a foundation, not an investment signal. No financial action is executed automatically.

## Operations and security

The bot uses Telegram long polling and needs no public inbound port. The health endpoint listens on localhost only. Credentials live in `/etc/doublemfinancial/doublem.env`, outside the repository, with restricted permissions. The systemd service runs as the unprivileged `doublem` user and logs to journald. Missing or stale data is never interpreted as zero risk.
