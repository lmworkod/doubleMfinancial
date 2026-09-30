from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.digest import build_daily_digest, human_age


def test_human_age_uses_minutes_hours_and_days():
    now = datetime(2026, 9, 28, 21, tzinfo=UTC)
    assert human_age(now - timedelta(minutes=12), now) == "hace 12 min"
    assert human_age(now - timedelta(hours=3), now) == "hace 3 h"
    assert human_age(now - timedelta(days=2), now) == "hace 2 días"
    assert human_age(None, now) == "pendiente"


def test_digest_reports_empty_inventory(monkeypatch):
    from app import digest

    monkeypatch.setattr(digest, "portfolio_snapshot", lambda: ([], 0.0, 0.0))
    monkeypatch.setattr(digest.db, "get_metric", lambda key: None)
    result = build_daily_digest(datetime(2026, 9, 28, 21, 0, tzinfo=UTC))
    assert "Inventario: no hay posiciones registradas." in result
    assert "P/L del día" not in result
    assert "Variación diaria" not in result
    assert "SP500-VRM permanece" in result


def test_digest_shows_cost_pnl_arrow_and_missing_period_history(monkeypatch):
    from app import digest
    from app.portfolio import PortfolioLine

    line = PortfolioLine("SPY", 2, 500.0, "USD", 900.0, 450.0, 90.0)
    monkeypatch.setattr(digest, "portfolio_snapshot", lambda: ([line], 900.0, 1.0))
    monkeypatch.setattr(digest.db, "get_metric", lambda key: None)
    monkeypatch.setattr(digest.db, "portfolio_snapshot_before", lambda cutoff, fingerprint: None)
    monkeypatch.setattr(digest.db, "record_portfolio_snapshot", lambda *args, **kwargs: None)
    result = build_daily_digest(datetime(2026, 9, 28, 21, 0, tzinfo=UTC))
    assert "Valor conocido: 900.00 EUR" in result
    assert "🟢⬆️ SPY (SPY): 2 × 500.0000 USD" in result
    assert "P/L desde coste: +90.00 EUR" in result
    assert "P/L del día: no disponible" in result
    assert "P/L acumulado de la semana: no disponible" in result
    assert "Variación diaria" not in result


def test_digest_marks_flat_and_loss_positions(monkeypatch):
    from app import digest
    from app.portfolio import PortfolioLine

    lines = [
        PortfolioLine("FLAT", 1, 100, "EUR", 100, 100, 0.0),
        PortfolioLine("LOSS", 1, 90, "EUR", 90, 100, -10.0),
    ]
    monkeypatch.setattr(digest, "portfolio_snapshot", lambda: (lines, 190.0, 1.0))
    monkeypatch.setattr(digest.db, "get_metric", lambda key: None)
    monkeypatch.setattr(digest.db, "portfolio_snapshot_before", lambda cutoff, fingerprint: None)
    monkeypatch.setattr(digest.db, "record_portfolio_snapshot", lambda *args, **kwargs: None)
    result = build_daily_digest(datetime(2026, 9, 28, 21, 0, tzinfo=UTC))
    assert "⚪ FLAT (FLAT):" in result
    assert "🔴⬇️ LOSS (LOSS):" in result


def test_macro_digest_formats_age_and_trends(monkeypatch):
    from app import digest

    now = datetime(2026, 9, 28, 21, tzinfo=UTC)

    def metric(key):
        if key == "fred_fed_funds":
            return SimpleNamespace(value="3.5", observed_at=now - timedelta(hours=2))
        if key == "fred_fed_funds_as_of":
            return SimpleNamespace(value=(now - timedelta(hours=2)).isoformat())
        return None

    monkeypatch.setattr(digest.db, "get_metric", metric)
    monkeypatch.setattr(
        digest.db,
        "metric_history_at_or_before",
        lambda key, cutoff: SimpleNamespace(value=3.0)
        if key == "fred_fed_funds" else None,
    )
    result = digest._macro_line("fed_funds", "Fed Funds", now, (7, 30, 365))
    assert "actualizado hace 2 h" in result
    assert "WoW: +16.67%" in result
    assert "MoM: +16.67%" in result
    assert "YoY: +16.67%" in result
