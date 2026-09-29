from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class Holding(Base):
    __tablename__ = "holdings"
    symbol: Mapped[str] = mapped_column(String(24), primary_key=True)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    average_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")


class Quote(Base):
    __tablename__ = "quotes"
    symbol: Mapped[str] = mapped_column(String(24), primary_key=True)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Metric(Base):
    __tablename__ = "metrics"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DailyPrice(Base):
    """Persisted daily close keyed by instrument and market session."""
    __tablename__ = "daily_prices"
    symbol: Mapped[str] = mapped_column(String(24), primary_key=True)
    session_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


async def init_db() -> None:
    Base.metadata.create_all(engine)


def get_holdings() -> list[Holding]:
    with SessionLocal() as session:
        return list(session.scalars(select(Holding).order_by(Holding.symbol)))


def set_holding(symbol: str, quantity: float, average_cost: float | None = None) -> None:
    with SessionLocal.begin() as session:
        item = session.get(Holding, symbol.upper())
        if item is None:
            session.add(Holding(symbol=symbol.upper(), quantity=quantity, average_cost=average_cost))
        else:
            item.quantity, item.average_cost = quantity, average_cost


def delete_holding(symbol: str) -> bool:
    with SessionLocal.begin() as session:
        item = session.get(Holding, symbol.upper())
        if item is None:
            return False
        session.delete(item)
        return True


def quote_for(symbol: str) -> Quote | None:
    with SessionLocal() as session:
        return session.get(Quote, symbol.upper())


def upsert_quote(symbol: str, price: float, source: str, observed_at: datetime | None = None) -> None:
    observed_at = observed_at or datetime.now(UTC)
    with SessionLocal.begin() as session:
        item = session.get(Quote, symbol.upper())
        if item is None:
            session.add(Quote(symbol=symbol.upper(), price=price, source=source, observed_at=observed_at))
        else:
            item.price, item.source, item.observed_at = price, source, observed_at


def set_metric(key: str, value: str) -> None:
    now = datetime.now(UTC)
    with SessionLocal.begin() as session:
        item = session.get(Metric, key)
        if item is None:
            session.add(Metric(key=key, value=value, observed_at=now))
        else:
            item.value, item.observed_at = value, now


class PortfolioSnapshot(Base):
    """Immutable portfolio valuation snapshot used for daily/weekly P&L."""
    __tablename__ = "portfolio_snapshots"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    value_eur: Mapped[float] = mapped_column(Float, nullable=False)
    coverage: Mapped[float] = mapped_column(Float, nullable=False)
    holdings_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)


class MetricHistory(Base):
    __tablename__ = "metric_history"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


def get_metric(key: str) -> Metric | None:
    with SessionLocal() as session:
        return session.get(Metric, key)


def record_portfolio_snapshot(value_eur: float, coverage: float, holdings_fingerprint: str,
                              captured_at: datetime | None = None) -> None:
    captured_at = captured_at or datetime.now(UTC)
    with SessionLocal.begin() as session:
        session.add(PortfolioSnapshot(captured_at=captured_at, value_eur=value_eur,
                                      coverage=coverage,
                                      holdings_fingerprint=holdings_fingerprint))


def portfolio_snapshot_before(cutoff: datetime, fingerprint: str) -> PortfolioSnapshot | None:
    with SessionLocal() as session:
        return session.scalar(select(PortfolioSnapshot)
                              .where(PortfolioSnapshot.captured_at <= cutoff,
                                     PortfolioSnapshot.holdings_fingerprint == fingerprint)
                              .order_by(PortfolioSnapshot.captured_at.desc()).limit(1))


def record_metric_history(key: str, value: float, observed_at: datetime) -> None:
    with SessionLocal.begin() as session:
        item = session.scalar(select(MetricHistory).where(
            MetricHistory.key == key, MetricHistory.observed_at == observed_at))
        if item is None:
            session.add(MetricHistory(key=key, value=value, observed_at=observed_at))
        else:
            item.value = value


def metric_history_at_or_before(key: str, cutoff: datetime) -> MetricHistory | None:
    with SessionLocal() as session:
        return session.scalar(select(MetricHistory).where(
            MetricHistory.key == key, MetricHistory.observed_at <= cutoff)
            .order_by(MetricHistory.observed_at.desc()).limit(1))


def daily_prices_for(symbol: str, limit: int = 500) -> list[DailyPrice]:
    """Return the most recent persisted sessions in chronological order."""
    with SessionLocal() as session:
        rows = list(session.scalars(
            select(DailyPrice).where(DailyPrice.symbol == symbol.upper())
            .order_by(DailyPrice.session_date.desc()).limit(max(1, min(limit, 500)))
        ))
        return list(reversed(rows))


def upsert_daily_prices(symbol: str, rows: list[tuple[datetime, float]], source: str) -> int:
    """Insert valid daily closes without replacing a known close for that session."""
    inserted = 0
    with SessionLocal.begin() as session:
        for observed_at, close in rows:
            if not isinstance(close, (int, float)) or close <= 0:
                continue
            session_date = observed_at.replace(hour=0, minute=0, second=0, microsecond=0)
            item = session.get(DailyPrice, (symbol.upper(), session_date))
            if item is None:
                session.add(DailyPrice(symbol=symbol.upper(), session_date=session_date,
                                       close=float(close), source=source))
                inserted += 1
    return inserted
