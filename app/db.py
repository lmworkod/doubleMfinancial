from datetime import datetime, timezone

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


def upsert_quote(symbol: str, price: float, source: str) -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as session:
        item = session.get(Quote, symbol.upper())
        if item is None:
            session.add(Quote(symbol=symbol.upper(), price=price, source=source, observed_at=now))
        else:
            item.price, item.source, item.observed_at = price, source, now


def set_metric(key: str, value: str) -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal.begin() as session:
        item = session.get(Metric, key)
        if item is None:
            session.add(Metric(key=key, value=value, observed_at=now))
        else:
            item.value, item.observed_at = value, now


def get_metric(key: str) -> Metric | None:
    with SessionLocal() as session:
        return session.get(Metric, key)
