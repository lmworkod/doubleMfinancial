import logging
from datetime import UTC, datetime

from app import db
from app.config import settings
from app.providers import market_data

logger = logging.getLogger(__name__)


class Services:
    async def refresh_quotes(self) -> dict[str, str]:
        results: dict[str, str] = {}
        symbols = sorted(set(settings.symbols + [holding.symbol for holding in db.get_holdings()]))
        for symbol in symbols:
            result = await market_data.quote(symbol)
            if result.value is not None:
                db.upsert_quote(symbol, result.value, result.source, result.as_of)
                results[symbol] = f"ok:{result.source}:{result.as_of.isoformat() if result.as_of else 'unknown'}"
            else:
                # Preserve the last known quote. Never replace it with zero,
                # NaN, or a fabricated value when providers are unavailable.
                previous = db.quote_for(symbol)
                results[symbol] = (
                    f"stale:{result.error or 'quote_unavailable'}:{previous.observed_at.isoformat() if previous else 'unknown'}"
                    if previous is not None
                    else f"unavailable:{result.error or 'quote_unavailable'}"
                )
                logger.warning("Quote refresh failed for %s: %s", symbol, result.error or "unavailable")
        fx = await market_data.fx_usd_per_eur()
        if fx.value is not None:
            db.set_metric("fx_usd_per_eur", str(fx.value))
            db.set_metric("fx_usd_per_eur_as_of", fx.as_of.isoformat() if fx.as_of else "unknown")
            results["FX_USD_EUR"] = f"ok:{fx.source}:{fx.as_of.isoformat() if fx.as_of else 'unknown'}"
        else:
            previous_fx = db.get_metric("fx_usd_per_eur")
            results["FX_USD_EUR"] = (
                f"stale:{fx.error or 'rate_unavailable'}:{db.get_metric('fx_usd_per_eur_as_of').value if db.get_metric('fx_usd_per_eur_as_of') else 'unknown'}"
                if previous_fx is not None
                else f"unavailable:{fx.error or 'rate_unavailable'}"
            )
            logger.warning("FX refresh failed: %s", fx.error or "unavailable")
        db.set_metric("last_quote_refresh", datetime.now(UTC).isoformat())
        return results

    async def refresh_macro(self) -> dict[str, str]:
        results: dict[str, str] = {}
        for series_id, name in {"FEDFUNDS": "fed_funds", "DGS10": "ust10y",
                                "DTWEXBGS": "usd_broad"}.items():
            result = await market_data.fred_latest(series_id)
            if result.value is None:
                previous = db.get_metric(f"fred_{name}")
                results[name] = (
                    f"stale:{result.error or 'data_unavailable'}:{db.get_metric(f'fred_{name}_as_of').value if db.get_metric(f'fred_{name}_as_of') else 'unknown'}"
                    if previous is not None
                    else f"unavailable:{result.error or 'data_unavailable'}"
                )
                logger.warning("Macro refresh failed for %s: %s", name, result.error or "unavailable")
                continue
            db.set_metric(f"fred_{name}", str(result.value))
            db.set_metric(f"fred_{name}_as_of", result.as_of.isoformat() if result.as_of else "unknown")
            results[name] = f"ok:fred:{result.as_of.isoformat() if result.as_of else 'unknown'}"
        db.set_metric("last_macro_refresh", datetime.now(UTC).isoformat())
        return results
