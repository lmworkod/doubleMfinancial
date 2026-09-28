from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from app.config import settings


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
        self.day = datetime.now(timezone.utc).date()

    def consume(self) -> bool:
        today = datetime.now(timezone.utc).date()
        if today != self.day:
            self.day, self.used = today, 0
        if self.used >= self.limit:
            return False
        self.used += 1
        return True


class MarketData:
    def __init__(self) -> None:
        self.budget = DailyBudget(settings.provider_daily_budget)
        self.client = httpx.AsyncClient(timeout=settings.http_timeout_seconds)

    async def close(self) -> None:
        await self.client.aclose()

    async def quote(self, symbol: str) -> ProviderResult:
        errors = []
        if settings.twelve_data_api_key and self.budget.consume():
            try:
                response = await self.client.get("https://api.twelvedata.com/price",
                    params={"symbol": symbol, "apikey": settings.twelve_data_api_key})
                response.raise_for_status()
                payload = response.json()
                if payload.get("price") is not None:
                    return ProviderResult(float(payload["price"]), "twelve_data", datetime.now(timezone.utc))
                errors.append(f"Twelve Data: {payload.get('message', 'price unavailable')}")
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                errors.append(f"Twelve Data: {exc}")
        if settings.finnhub_api_key and self.budget.consume():
            try:
                response = await self.client.get("https://finnhub.io/api/v1/quote",
                    params={"symbol": symbol, "token": settings.finnhub_api_key})
                response.raise_for_status()
                price = float(response.json().get("c") or 0)
                if price > 0:
                    return ProviderResult(price, "finnhub", datetime.now(timezone.utc))
                errors.append("Finnhub: quote unavailable")
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                errors.append(f"Finnhub: {exc}")
        return ProviderResult(None, "none", None, "; ".join(errors) or "No provider configured or budget exhausted")

    async def fred_latest(self, series_id: str) -> ProviderResult:
        if not settings.fred_api_key:
            return ProviderResult(None, "fred", None, "FRED_API_KEY not configured")
        if not self.budget.consume():
            return ProviderResult(None, "fred", None, "Daily request budget exhausted")
        try:
            response = await self.client.get("https://api.stlouisfed.org/fred/series/observations",
                params={"series_id": series_id, "api_key": settings.fred_api_key,
                        "file_type": "json", "sort_order": "desc", "limit": 10})
            response.raise_for_status()
            observations = response.json().get("observations", [])
            for item in observations:
                value = item.get("value")
                if value not in (None, "", "."):
                    as_of = datetime.fromisoformat(item["date"]).replace(tzinfo=timezone.utc)
                    return ProviderResult(float(value), "fred", as_of)
            return ProviderResult(None, "fred", None, "No valid observations")
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            return ProviderResult(None, "fred", None, str(exc))


market_data = MarketData()
