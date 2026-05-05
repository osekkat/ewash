"""Database engine/session helpers for Ewash v0.3 persistence."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import re

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base, CustomerVehicle, VehicleColor, VehicleModel


def normalize_database_url(database_url: str) -> str:
    """Normalize provider URLs for SQLAlchemy 2.

    Railway and Heroku-style Postgres URLs often start with `postgres://`, which
    SQLAlchemy does not treat as a dialect. Prefer psycopg v3 explicitly.
    """
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def make_engine(database_url: str | None = None) -> Engine:
    """Create a SQLAlchemy engine.

    Tests pass an explicit SQLite URL. Production uses `DATABASE_URL` from the
    environment once Railway Postgres is provisioned.
    """
    raw_url = database_url or settings.database_url
    if not raw_url:
        raise RuntimeError("DATABASE_URL is not configured")
    url = normalize_database_url(raw_url)

    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)


def init_db(engine: Engine) -> None:
    """Create all v0.3 tables. Alembic can replace this after MVP."""
    Base.metadata.create_all(bind=engine)
    _ensure_customer_bot_stage_columns(engine)
    _ensure_customer_vehicle_reference_columns(engine)
    _backfill_vehicle_reference_data(engine)


def _ensure_customer_bot_stage_columns(engine: Engine) -> None:
    """Add WhatsApp funnel-stage columns for customer rows created before this slice."""
    inspector = inspect(engine)
    if "customers" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("customers")}
    statements: list[str] = []
    if "last_bot_stage" not in columns:
        statements.append("ALTER TABLE customers ADD COLUMN last_bot_stage VARCHAR(60) DEFAULT ''")
    if "last_bot_stage_label" not in columns:
        statements.append("ALTER TABLE customers ADD COLUMN last_bot_stage_label VARCHAR(160) DEFAULT ''")
    if "last_bot_stage_at" not in columns:
        statements.append(f"ALTER TABLE customers ADD COLUMN last_bot_stage_at {_datetime_column_sql(engine)}")
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _datetime_column_sql(engine: Engine) -> str:
    if engine.dialect.name == "postgresql":
        return "TIMESTAMP WITH TIME ZONE"
    return "DATETIME"


def _normalize_reference_value(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def _get_or_create_vehicle_model(session: Session, *, category: str, model: str) -> VehicleModel | None:
    normalized = _normalize_reference_value(model)
    if not normalized:
        return None
    existing = session.query(VehicleModel).filter_by(category=category, normalized_name=normalized).first()
    if existing is not None:
        return existing
    row = VehicleModel(category=category, name=model.strip(), normalized_name=normalized, active=True)
    session.add(row)
    session.flush()
    return row


def _get_or_create_vehicle_color(session: Session, *, color: str) -> VehicleColor | None:
    normalized = _normalize_reference_value(color)
    if not normalized:
        return None
    existing = session.query(VehicleColor).filter_by(normalized_name=normalized).first()
    if existing is not None:
        return existing
    row = VehicleColor(name=color.strip(), normalized_name=normalized, active=True)
    session.add(row)
    session.flush()
    return row


def _backfill_vehicle_reference_data(engine: Engine) -> None:
    with Session(engine, expire_on_commit=False, future=True) as session:
        vehicles = session.query(CustomerVehicle).all()
        changed = False
        for vehicle in vehicles:
            if vehicle.category == "MOTO":
                continue
            if vehicle.model and vehicle.model_id is None:
                model = _get_or_create_vehicle_model(session, category=vehicle.category or "", model=vehicle.model)
                if model is not None:
                    vehicle.model_id = model.id
                    changed = True
            if vehicle.color and vehicle.color_id is None:
                color = _get_or_create_vehicle_color(session, color=vehicle.color)
                if color is not None:
                    vehicle.color_id = color.id
                    changed = True
        if changed:
            session.commit()


def _ensure_customer_vehicle_reference_columns(engine: Engine) -> None:
    """Add normalized vehicle FK columns for DBs created before this schema slice.

    `create_all()` creates the columns for fresh databases, but does not alter
    existing Railway Postgres tables. Keep this deliberately tiny/idempotent
    until the project needs Alembic.
    """
    inspector = inspect(engine)
    if "customer_vehicles" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("customer_vehicles")}
    statements: list[str] = []
    if "model_id" not in columns:
        statements.append("ALTER TABLE customer_vehicles ADD COLUMN model_id INTEGER")
    if "color_id" not in columns:
        statements.append("ALTER TABLE customer_vehicles ADD COLUMN color_id INTEGER")
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Provide a transactional session that commits or rolls back."""
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
