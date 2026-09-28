import asyncio
import csv
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO

import httpx

from app.config import settings
from app.instruments import INSTRUMENTS, resolve_exchange, resolve_symbol

logger = logging.getLogger(__name__)


@dataclass
class ProviderResult:
    value: float | None
    source: str
    as_of: datetime | None
    error: str | None = None


class DailyBudget:
    """A conservative in-process request budget, reset at UTC midnight."""
    def __init__(self, limit: int = 700):
        self.limit, self.used = max(0, limit), 0
        self.day = datetime.now(UTC).date()

    def consume(self) -> bool:
        today = datetime.now(UTC).date()
        if today != self.day:
            self.day, self.used = today, 0
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


def _positive_price(value: object) -> float | None:
    """Accept finite, strictly positive numeric market prices only."""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


def _safe_http_error(response: httpx.Response) -> str:
    """Return a bounded diagnostic without request URLs or credentials."""
    status = response.status_code
    if status == 401:
        return "unauthorized"
    if status == 403:
        return "forbidden_or_not_entitled"
    if status == 404:
        return "symbol_or_resource_not_found"
    if status == 429:
        return "rate_limit"
    if status >= 500:
        return f"provider_server_error_{status}"
    return f"http_error_{status}"


class MarketData:
    def __init__(self) -> None:
        self.budget = DailyBudget(settings.provider_daily_budget)
        self.client = httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "DoubleMFinancial/0.1 (market-data fallback)"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def _get_json(
        self, url: str, params: dict[str, str], provider: str
    ) -> tuple[dict | None, str | None]:
        """Request JSON with bounded retries for transient failures only."""
        for attempt in range(3):
            if not self.budget.consume():
                return None, "daily_request_budget_exhausted"
            try:
                response = await self.client.get(url, params=params)
                if response.status_code == 429 or response.status_code >= 500:
                    reason = _safe_http_error(response)
                    if response.status_code == 429:
                        logger.warning("%s request throttled", provider)
                        return None, reason
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    logger.warning("%s request failed: %s", provider, reason)
                    return None, reason
                if response.is_error:
                    reason = _safe_http_error(response)
                    logger.info("%s request failed: %s", provider, reason)
                    return None, reason
                try:
                    payload = response.json()
                except ValueError:
                    logger.warning("%s returned invalid JSON", provider)
                    return None, "invalid_json"
                if not isinstance(payload, dict):
                    return None, "unexpected_response"
                return payload, None
            except httpx.TimeoutException:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                logger.warning("%s request timed out after retries", provider)
                return None, "timeout"
            except httpx.RequestError as exc:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                logger.warning("%s network request failed: %s", provider, type(exc).__name__)
                return None, "network_error"
        return None, "request_failed"

    async def _get_text(self, url: str, params: dict[str, str], provider: str):
        """Request text/CSV with the same quota and retry protections."""
        for attempt in range(3):
            if not self.budget.consume():
                return None, None, "daily_request_budget_exhausted"
            try:
                response = await self.client.get(url, params=params)
                if response.status_code == 429:
                    logger.warning("%s request throttled", provider)
                    return None, None, "rate_limit"
                if response.status_code >= 500:
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
                        continue
                    return None, None, _safe_http_error(response)
                if response.is_error:
                    return None, None, _safe_http_error(response)
                return response.text, response.headers.get("content-type", ""), None
            except httpx.TimeoutException:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                return None, None, "timeout"
            except httpx.RequestError as exc:
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                logger.warning("%s network request failed: %s", provider, type(exc).__name__)
                return None, None, "network_error"
        return None, None, "request_failed"

    async def _stooq_quote(self, symbol: str) -> ProviderResult:
        """Fetch the last daily close for a pre-verified Stooq symbol.

        This fallback is restricted to configured US symbols and uses daily
        bars only. It is not advertised as an intraday quote.
        """
        ticker = STOOQ_SYMBOLS.get(symbol.strip().upper())
        if not ticker:
            return ProviderResult(None, "stooq", None, "symbol_not_configured")
        text, _, error = await self._get_text(
            "https://stooq.com/q/d/l/", {"s": ticker, "i": "d"}, "stooq"
        )
        if error:
            return ProviderResult(None, "stooq", None, error)
        try:
            rows = list(csv.DictReader(StringIO(text or "")))
            for row in reversed(rows):
                price = _positive_price(row.get("Close"))
                observed = datetime.strptime(row["Date"], "%Y-%m-%d").replace(tzinfo=UTC)
                if price is not None:
                    return ProviderResult(price, "stooq_daily", observed)
        except (ValueError, KeyError, TypeError):
            pass
        return ProviderResult(None, "stooq", None, "no_valid_observation")

    async def _yahoo_daily_quote(self, symbol: str) -> ProviderResult:
        """Best-effort daily close; not an official/licensed market-data API."""
        key = symbol.strip().upper()
        ticker = YAHOO_SYMBOLS.get(key)
        if not ticker:
            return ProviderResult(None, "yahoo_chart", None, "symbol_not_configured")
        payload, error = await self._get_json(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
            {"range": "5d", "interval": "1d", "events": "div,splits"},
            "yahoo_chart",
        )
        if error:
            return ProviderResult(None, "yahoo_chart", None, error)
        try:
            result = payload["chart"]["result"][0]
            meta = result["meta"]
            returned_symbol = str(meta.get("symbol", "")).upper()
            if returned_symbol and returned_symbol != ticker.upper():
                return ProviderResult(None, "yahoo_chart", None, "symbol_mismatch")
            currency = str(meta.get("currency", "")).upper()
            expected = INSTRUMENTS[key].quote_currency if key in INSTRUMENTS else "EUR"
            if currency != expected:
                return ProviderResult(None, "yahoo_chart", None, "currency_mismatch")
            timestamps = result.get("timestamp") or []
            closes = result["indicators"]["quote"][0].get("close") or []
            for timestamp, close in reversed(list(zip(timestamps, closes))):
                price = _positive_price(close)
                if isinstance(timestamp, (int, float)) and timestamp > 0 and price is not None:
                    return ProviderResult(price, "yahoo_daily", datetime.fromtimestamp(timestamp, UTC))
        except (KeyError, IndexError, TypeError, ValueError):
            pass
        return ProviderResult(None, "yahoo_chart", None, "no_valid_observation")

    async def quote(self, symbol: str) -> ProviderResult:
        errors: list[str] = []
        twelve_symbol = resolve_symbol(symbol, "twelve_data")
        finnhub_symbol = resolve_symbol(symbol, "finnhub")
        is_known_isin = symbol.strip().upper().startswith("IE") and len(symbol.strip()) == 12
        if twelve_symbol is None and finnhub_symbol is None and not is_known_isin:
            return ProviderResult(None, "none", None, "unmapped_isin")

        providers: list[tuple[str, str, str]] = []
        if settings.twelve_data_api_key and twelve_symbol:
            providers.append(("twelve_data", twelve_symbol, "https://api.twelvedata.com/quote"))
        if settings.finnhub_api_key and finnhub_symbol and not is_known_isin:
            providers.append(("finnhub", finnhub_symbol, "https://finnhub.io/api/v1/quote"))

        for provider, ticker, url in providers:
            params = {"symbol": ticker}
            exchange = resolve_exchange(symbol, provider)
            if exchange:
                params["exchange"] = exchange
            params["apikey" if provider == "twelve_data" else "token"] = (
                settings.twelve_data_api_key if provider == "twelve_data"
                else settings.finnhub_api_key
            )
            payload, error = await self._get_json(url, params, provider)
            if error:
                errors.append(f"{provider}:{error}")
                continue

            if provider == "twelve_data":
                returned_exchange = str(payload.get("mic_code") or "").upper()
                expected_exchange = (exchange or "").upper()
                if expected_exchange and returned_exchange and returned_exchange != expected_exchange:
                    errors.append(f"{provider}:exchange_mismatch")
                    logger.warning("%s returned a different exchange for %s", provider, symbol)
                    continue
                price = _positive_price(payload.get("close"))
                if price is None:
                    api_status = str(payload.get("status", "")).lower()
                    message = str(payload.get("message", "")).lower()
                    code = str(payload.get("code", ""))
                    if code == "401" or "apikey" in message or "api key" in message:
                        reason = "unauthorized"
                    elif code == "403" or "permission" in message or "plan" in message:
                        reason = "not_entitled"
                    elif code == "429" or "run out of api credits" in message or "limit" in message:
                        reason = "rate_limit"
                    elif api_status == "error":
                        reason = "symbol_unavailable"
                    else:
                        reason = "invalid_price"
                    errors.append(f"{provider}:{reason}")
                    logger.info("%s quote rejected: %s", provider, reason)
                    continue
                # Provider quote endpoint's datetime field is the observation
                # date. If omitted, mark retrieval time as best-effort only.
                as_of = _parse_provider_datetime(payload.get("datetime")) or datetime.now(UTC)
                return ProviderResult(price, provider, as_of)

            price = _positive_price(payload.get("c"))
            if price is not None:
                timestamp = payload.get("t")
                as_of = datetime.fromtimestamp(timestamp, UTC) if isinstance(timestamp, (int, float)) and timestamp > 0 else datetime.now(UTC)
                return ProviderResult(price, provider, as_of)
            errors.append(f"{provider}:quote_unavailable")

        # Free, unauthenticated daily close fallback for regular US symbols.
        stooq = await self._stooq_quote(symbol)
        if stooq.value is not None:
            return stooq
        if stooq.error and stooq.error != "symbol_not_configured":
            errors.append(f"stooq:{stooq.error}")

        yahoo = await self._yahoo_daily_quote(symbol)
        if yahoo.value is not None:
            return yahoo
        if yahoo.error and yahoo.error != "symbol_not_configured":
            errors.append(f"yahoo:{yahoo.error}")
        return ProviderResult(None, "none", None, "; ".join(errors) or "quote_unavailable")

    async def fx_usd_per_eur(self) -> ProviderResult:
        """Fetch ECB's latest daily reference; use Frankfurter if ECB fails."""
        if self.budget.consume():
            try:
                response = await self.client.get(
                    "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A",
                    params={"lastNObservations": 1, "format": "csvdata"},
                    headers={"Accept": "text/csv"},
                )
                if not response.is_error:
                    rows = list(csv.DictReader(StringIO(response.text)))
                    if rows and rows[-1].get("OBS_VALUE"):
                        row = rows[-1]
                        rate = _positive_price(row["OBS_VALUE"])
                        if rate is not None:
                            observed = datetime.fromisoformat(row["TIME_PERIOD"]).replace(tzinfo=UTC)
                            return ProviderResult(rate, "ecb", observed)
            except (httpx.RequestError, ValueError, KeyError, TypeError) as exc:
                logger.info("ECB unavailable: %s", type(exc).__name__)
        else:
            return ProviderResult(None, "ecb", None, "daily_request_budget_exhausted")

        payload, error = await self._get_json(
            "https://api.frankfurter.dev/v2/rate/eur/usd", {}, "frankfurter"
        )
        if error:
            return ProviderResult(None, "none", None, f"ecb_and_frankfurter:{error}")
        rate = _positive_price(payload.get("rate"))
        if rate is None:
            return ProviderResult(None, "frankfurter", None, "invalid_rate")
        observed_raw = payload.get("date")
        try:
            observed = datetime.fromisoformat(observed_raw).replace(tzinfo=UTC)
        except (ValueError, TypeError):
            observed = datetime.now(UTC)
        return ProviderResult(rate, "frankfurter", observed)

    async def fred_latest(self, series_id: str) -> ProviderResult:
        if not settings.fred_api_key:
            return ProviderResult(None, "fred", None, "fred_api_key_not_configured")
        payload, error = await self._get_json(
            "https://api.stlouisfed.org/fred/series/observations",
            {"series_id": series_id, "api_key": settings.fred_api_key,
             "file_type": "json", "sort_order": "desc", "limit": "10"},
            "fred",
        )
        if error:
            return ProviderResult(None, "fred", None, error)
        for item in payload.get("observations", []):
            value = item.get("value")
            if value not in (None, "", "."):
                try:
                    as_of = datetime.fromisoformat(item["date"]).replace(tzinfo=UTC)
                    number = float(value)
                    if not math.isfinite(number):
                        continue
                    return ProviderResult(number, "fred", as_of)
                except (ValueError, TypeError, KeyError):
                    continue
        return ProviderResult(None, "fred", None, "no_valid_observations")


def _parse_provider_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except ValueError:
        return None


# Explicit allowlist: no inferred or user-controlled Stooq ticker construction.
YAHOO_SYMBOLS = {
    "IE000J80JTL1": "GRID.MI",
    "IE0003Z9E2Y3": "COPX.L",
    "IE000UL6CLP7": "SILV.L",
    "IE000YU9K6K2": "JEDI.L",
    "IE000KHX9DX6": "RARE.L",
    "IE00B4ND3602": "PPFB.DE",
    "IE000M7V94E1": "NUKL.DE",
    "XAU-EUR": "XAUEUR=X",
}


STOOQ_SYMBOLS = {
    "SPY": "spy.us",
    "QQQ": "qqq.us",
    "IWM": "iwm.us",
}

market_data = MarketData()
