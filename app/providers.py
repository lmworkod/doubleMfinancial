import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from app.config import settings
from app.instruments import resolve_exchange, resolve_symbol

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
                        # Quota limits are generally account-wide. Don't waste
                        # further credits retrying the same provider here.
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
                # Log only exception type: httpx exception strings can include
                # full request URLs and query-string API credentials.
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                    continue
                logger.warning("%s network request failed: %s", provider, type(exc).__name__)
                return None, "network_error"
        return None, "request_failed"

    async def quote(self, symbol: str) -> ProviderResult:
        errors: list[str] = []
        twelve_symbol = resolve_symbol(symbol, "twelve_data")
        finnhub_symbol = resolve_symbol(symbol, "finnhub")
        if twelve_symbol is None and finnhub_symbol is None:
            return ProviderResult(None, "none", None, "unmapped_isin")

        # Finnhub's regular quote endpoint is US-equity focused. Do not issue
        # predictable failing requests for mapped European ETF/ETC listings.
        # It remains a fallback for regular symbols supplied by the user.
        is_known_isin = symbol.strip().upper().startswith("IE") and len(symbol.strip()) == 12
        providers: list[tuple[str, str, str]] = []
        if settings.twelve_data_api_key and twelve_symbol:
            providers.append(("twelve_data", twelve_symbol, "https://api.twelvedata.com/quote"))
        if settings.finnhub_api_key and finnhub_symbol and not is_known_isin:
            providers.append(("finnhub", finnhub_symbol, "https://finnhub.io/api/v1/quote"))

        if not providers:
            return ProviderResult(None, "none", None, "no_eligible_provider_configured")

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
                # A transient provider outage or throttling should allow a
                # different eligible provider to be tried.
                continue

            if provider == "twelve_data":
                # /quote exposes close and provider metadata. Require its
                # returned exchange to agree with the requested listing when
                # both are present, and don't silently use another venue.
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
                    # Don't call another provider for a permanent error that
                    # indicates account-wide authentication/entitlement.
                    if reason in {"unauthorized", "not_entitled", "rate_limit"}:
                        continue
                    continue
                return ProviderResult(price, provider, datetime.now(UTC))

            price = _positive_price(payload.get("c"))
            if price is not None:
                return ProviderResult(price, provider, datetime.now(UTC))
            errors.append(f"{provider}:quote_unavailable")
            logger.info("%s returned no current price for %s", provider, symbol)

        return ProviderResult(None, "none", None, "; ".join(errors) or "quote_unavailable")

    async def fx_usd_per_eur(self) -> ProviderResult:
        """Fetch the latest ECB daily reference rate (USD per EUR)."""
        if not self.budget.consume():
            return ProviderResult(None, "ecb", None, "daily_request_budget_exhausted")
        try:
            response = await self.client.get(
                "https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A",
                params={"lastNObservations": 1, "format": "csvdata"},
                headers={"Accept": "text/csv"},
            )
            if response.is_error:
                return ProviderResult(None, "ecb", None, _safe_http_error(response))
            import csv
            from io import StringIO

            rows = list(csv.DictReader(StringIO(response.text)))
            if not rows or not rows[-1].get("OBS_VALUE"):
                return ProviderResult(None, "ecb", None, "no_observation")
            row = rows[-1]
            observed = datetime.fromisoformat(row["TIME_PERIOD"]).replace(tzinfo=UTC)
            rate = _positive_price(row["OBS_VALUE"])
            if rate is None:
                return ProviderResult(None, "ecb", None, "invalid_rate")
            return ProviderResult(rate, "ecb", observed)
        except httpx.RequestError as exc:
            logger.warning("ECB request failed: %s", type(exc).__name__)
            return ProviderResult(None, "ecb", None, "network_error")
        except (ValueError, KeyError, TypeError):
            return ProviderResult(None, "ecb", None, "invalid_response")

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


market_data = MarketData()
