from datetime import UTC, datetime

from app import db
from app.config import settings
from app.providers import market_data


class Services:
    async def refresh_quotes(self) -> dict[str, str]:
        results = {}
        symbols = sorted(set(settings.symbols + [holding.symbol for holding in db.get_holdings()]))
        for symbol in symbols:
            result = await market_data.quote(symbol)
            if result.value is not None:
                db.upsert_quote(symbol, result.value, result.source)
                results[symbol] = f"ok:{result.source}"
            else:
                results[symbol] = f"unavailable:{result.error}"
        db.set_metric("last_quote_refresh", datetime.now(UTC).isoformat())
        return results

    async def refresh_macro(self) -> dict[str, str]:
        results = {}
        for series_id, name in {"FEDFUNDS": "fed_funds", "DGS10": "ust10y",
                                "DTWEXBGS": "usd_broad"}.items():
            result = await market_data.fred_latest(series_id)
            if result.value is None:
                results[name] = f"unavailable:{result.error}"
                continue
            db.set_metric(f"fred_{name}", str(result.value))
            db.set_metric(f"fred_{name}_as_of", result.as_of.isoformat() if result.as_of else "unknown")
            results[name] = "ok"
        db.set_metric("last_macro_refresh", datetime.now(UTC).isoformat())
        return results
