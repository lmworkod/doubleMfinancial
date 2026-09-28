# DoubleM Financial

Telegram-first, self-hosted portfolio and market-risk assistant. Python, PostgreSQL and Docker Compose. No web frontend and no brokerage execution.

## Included

- Telegram commands for a manually maintained portfolio, quotes, macro data, refresh and status.
- PostgreSQL persistence for holdings, current quotes and macro metrics.
- Optional connectors: FRED, Twelve Data and Finnhub. Missing keys or exhausted quota are reported as unavailable.
- Daily risk-feature foundation. Probabilities remain disabled until a model is trained and validated walk-forward.
- Docker Compose deployment, persistent database volume and local health endpoint.
- No automated trading, order submission or portfolio rebalancing.

## Configure

Create a bot with [@BotFather](https://t.me/BotFather) and request a free [FRED API key](https://fred.stlouisfed.org/docs/api/api_key.html). Twelve Data and Finnhub keys are optional. Never commit credentials.

Configure these variables in Coolify (or copy `.env.example` to `.env` locally):

- `TELEGRAM_BOT_TOKEN`: required.
- `TELEGRAM_ALLOWED_USER_IDS`: numeric Telegram user ID(s), comma-separated. All users are denied when empty.
- `FRED_API_KEY`: free key for macro.
- `TWELVE_DATA_API_KEY`, `FINNHUB_API_KEY`: optional market sources.
- `POSTGRES_PASSWORD`: strong, unique password.

Deploy as a Docker Compose resource. Do not upload `.env` to GitHub. PostgreSQL and the health endpoint are not exposed publicly.

## Local run

```bash
cp .env.example .env
# Edit .env and set strong credentials
pip install -e '.[dev]'
pytest -q
docker compose up -d --build
```

## Telegram commands

`/start`, `/help`, `/portfolio`, `/add SYMBOL QUANTITY [AVERAGE_COST]`, `/remove SYMBOL`, `/analyze SYMBOL`, `/watchlist`, `/opportunities`, `/risk`, `/macro`, `/refresh`, `/status`.

Positions are entered manually; there is no broker connection. Valuation includes only positions with a stored quote and excludes cash, FX conversion and fees.

## Data and model limits

Free APIs have changing quotas, market coverage and usage terms. Provider timestamps and market entitlements are authoritative; HTTP success alone does not prove data is real-time. The request budget is conservative but process-local.

This initial release has no approved historical training dataset or fitted SP500-VRM coefficients. It deliberately reports an uncalibrated model instead of fabricating probabilities. Risk features are a foundation, not an investment signal. No financial action is executed automatically.

## Operations

The bot uses Telegram long polling and needs no public inbound port. `/health` listens on container localhost for Docker's healthcheck. Configure external PostgreSQL backups and test restores before relying on the system. Missing or stale data is never interpreted as zero risk.
