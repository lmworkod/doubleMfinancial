from datetime import UTC, datetime

from app.digest import build_daily_digest


def test_digest_reports_empty_inventory(monkeypatch):
    from app import digest

    monkeypatch.setattr(digest, "portfolio_snapshot", lambda: ([], 0.0, 0.0))
    monkeypatch.setattr(digest.db, "get_metric", lambda key: None)
    result = build_daily_digest(datetime(2026, 9, 28, 21, 0, tzinfo=UTC))
    assert "Inventario: no hay posiciones registradas." in result
    assert "Variación diaria" not in result


def test_digest_marks_daily_change_unavailable(monkeypatch):
    from app import digest
    from app.portfolio import PortfolioLine

    line = PortfolioLine("SPY", 2, 500.0, "USD", 900.0, 450.0, 90.0)
    monkeypatch.setattr(digest, "portfolio_snapshot", lambda: ([line], 900.0, 1.0))
    monkeypatch.setattr(digest.db, "get_metric", lambda key: None)
    result = build_daily_digest(datetime(2026, 9, 28, 21, 0, tzinfo=UTC))
    assert "Valor conocido: 900.00 EUR" in result
    assert "SPY: 2 × 500.0000 USD" in result
    assert "Variación diaria: no calculable de forma fiable" in result
    assert "no calibradas" in result
