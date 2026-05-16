"""pwa integration schema changes

Revision ID: 20260514_0006
Revises: 20260506_0005
Create Date: 2026-05-14

Adds, in one revision:
  1. bookings.client_request_id (nullable VARCHAR(64)) + Postgres partial unique index.
  2. bookings.source (VARCHAR(16) NOT NULL DEFAULT 'whatsapp') + Postgres CHECK +
     ix_bookings_source for split-counter admin queries.
  3. customer_tokens table (token_hash → customer phone, opaque PWA read auth).
  4. ix_bookings_customer_phone_created_at composite index for the
     GET /api/v1/bookings list query.
  5. data_erasure_audit table (privacy-preserving deletion log — stores phone_hash,
     never raw phone).
  6. ON UPDATE CASCADE on the bookings.customer_phone FK so the GDPR / Loi 09-08
     anonymization path can update customers.phone in a single UPDATE.

The migration follows the defensive pattern established in 0001-0005:
introspect first, only emit DDL for what's missing, and skip Postgres-only
constructs (partial indexes, CHECK constraints, FK redefinition) on SQLite —
the SQLite test path relies on the model declarations that ship in
ewash-6pa.1.3 / 1.4 / 1.5.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "20260514_0006"
down_revision = "20260506_0005"
branch_labels = None
depends_on = None


SOURCE_CHECK_CONSTRAINT_NAME = "ck_bookings_source"
SOURCE_CHECK_CLAUSE = "source IN ('whatsapp','api','admin')"

PARTIAL_UQ_CLIENT_REQUEST_ID = "ix_bookings_client_request_id_partial"
COMPOSITE_IDX_PHONE_CREATED_AT = "ix_bookings_customer_phone_created_at"
SOURCE_IDX = "ix_bookings_source"

TOKENS_TABLE = "customer_tokens"
ERASURE_TABLE = "data_erasure_audit"

BOOKINGS_FK_NAME = "bookings_customer_phone_fkey"


def _is_offline() -> bool:
    return bool(op.get_context().as_sql)


def _inspector():
    return inspect(op.get_bind())


def _tables() -> set[str]:
    if _is_offline():
        return set()
    return set(_inspector().get_table_names())


def _columns(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {column["name"] for column in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {index["name"] for index in _inspector().get_indexes(table)}


def _checks(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {constraint["name"] for constraint in _inspector().get_check_constraints(table)}


def _foreign_keys(table: str) -> list[dict]:
    if table not in _tables():
        return []
    return list(_inspector().get_foreign_keys(table))


def _bookings_customer_phone_fk_name() -> str | None:
    for fk in _foreign_keys("bookings"):
        cols = fk.get("constrained_columns") or []
        if "customer_phone" in cols:
            return fk.get("name") or BOOKINGS_FK_NAME
    return None


def upgrade() -> None:
    if _is_offline():
        return

    bind = op.get_bind()
    is_postgres = bind.dialect.name.startswith("postgresql")

    # 1. bookings.client_request_id ---------------------------------------------------
    if "bookings" in _tables() and "client_request_id" not in _columns("bookings"):
        op.add_column(
            "bookings",
            sa.Column("client_request_id", sa.String(length=64), nullable=True),
        )

    if is_postgres and "bookings" in _tables() and PARTIAL_UQ_CLIENT_REQUEST_ID not in _indexes("bookings"):
        # Partial unique index — only enforces uniqueness when the column is set.
        # NULL values stay unconstrained so legacy / WhatsApp bookings (which won't
        # carry a client_request_id) don't collide with each other.
        op.execute(sa.text(
            "CREATE UNIQUE INDEX ix_bookings_client_request_id_partial "
            "ON bookings (client_request_id) WHERE client_request_id IS NOT NULL"
        ))

    # 2. bookings.source --------------------------------------------------------------
    if "bookings" in _tables() and "source" not in _columns("bookings"):
        op.add_column(
            "bookings",
            sa.Column(
                "source",
                sa.String(length=16),
                nullable=False,
                server_default="whatsapp",
            ),
        )

    if is_postgres and "bookings" in _tables() and SOURCE_CHECK_CONSTRAINT_NAME not in _checks("bookings"):
        op.create_check_constraint(SOURCE_CHECK_CONSTRAINT_NAME, "bookings", SOURCE_CHECK_CLAUSE)

    if "bookings" in _tables() and SOURCE_IDX not in _indexes("bookings"):
        op.create_index(SOURCE_IDX, "bookings", ["source"])

    # 3. customer_tokens --------------------------------------------------------------
    if TOKENS_TABLE not in _tables():
        op.create_table(
            TOKENS_TABLE,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column(
                "customer_phone",
                sa.String(length=32),
                sa.ForeignKey("customers.phone", onupdate="CASCADE", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("token_hash", name="uq_customer_tokens_token_hash"),
        )
        op.create_index("ix_customer_tokens_phone", TOKENS_TABLE, ["customer_phone"])
        op.create_index("ix_customer_tokens_last_used", TOKENS_TABLE, ["last_used_at"])

    # 4. composite index for the bookings-list query ---------------------------------
    if "bookings" in _tables() and COMPOSITE_IDX_PHONE_CREATED_AT not in _indexes("bookings"):
        op.create_index(
            COMPOSITE_IDX_PHONE_CREATED_AT,
            "bookings",
            ["customer_phone", sa.text("created_at DESC")],
        )

    # 5. data_erasure_audit -----------------------------------------------------------
    if ERASURE_TABLE not in _tables():
        op.create_table(
            ERASURE_TABLE,
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("phone_hash", sa.String(length=64), nullable=False),
            sa.Column("actor", sa.String(length=64), nullable=False),
            sa.Column("deleted_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("anonymized_bookings", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "performed_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.create_index(
            "ix_data_erasure_audit_performed_at",
            ERASURE_TABLE,
            [sa.text("performed_at DESC")],
        )

    # 6. bookings.customer_phone FK → ON UPDATE CASCADE -------------------------------
    # SQLite ALTER cannot redefine FK actions, so we only redefine on Postgres.
    # Tests run on SQLite without ON UPDATE CASCADE; the anonymize helper uses
    # the manual two-step pattern. Production Postgres benefits from CASCADE.
    if is_postgres and "bookings" in _tables():
        fk_name = _bookings_customer_phone_fk_name()
        if fk_name:
            op.drop_constraint(fk_name, "bookings", type_="foreignkey")
        op.create_foreign_key(
            BOOKINGS_FK_NAME,
            "bookings",
            "customers",
            ["customer_phone"],
            ["phone"],
            onupdate="CASCADE",
            ondelete="RESTRICT",
        )

    # 7. backfill --------------------------------------------------------------------
    # No-op given DEFAULT 'whatsapp' but emit explicit UPDATE for clarity / safety.
    if "bookings" in _tables():
        op.execute(sa.text("UPDATE bookings SET source = 'whatsapp' WHERE source IS NULL"))


def downgrade() -> None:
    if _is_offline():
        return

    bind = op.get_bind()
    is_postgres = bind.dialect.name.startswith("postgresql")

    # Reverse order of upgrade() ------------------------------------------------------

    # 6. bookings FK: drop the CASCADE variant, restore the plain FK.
    if is_postgres and "bookings" in _tables():
        fk_name = _bookings_customer_phone_fk_name()
        if fk_name:
            op.drop_constraint(fk_name, "bookings", type_="foreignkey")
        op.create_foreign_key(
            BOOKINGS_FK_NAME,
            "bookings",
            "customers",
            ["customer_phone"],
            ["phone"],
        )

    # 5. data_erasure_audit
    if ERASURE_TABLE in _tables():
        if "ix_data_erasure_audit_performed_at" in _indexes(ERASURE_TABLE):
            op.drop_index("ix_data_erasure_audit_performed_at", table_name=ERASURE_TABLE)
        op.drop_table(ERASURE_TABLE)

    # 4. composite index
    if "bookings" in _tables() and COMPOSITE_IDX_PHONE_CREATED_AT in _indexes("bookings"):
        op.drop_index(COMPOSITE_IDX_PHONE_CREATED_AT, table_name="bookings")

    # 3. customer_tokens
    if TOKENS_TABLE in _tables():
        for idx_name in ("ix_customer_tokens_phone", "ix_customer_tokens_last_used"):
            if idx_name in _indexes(TOKENS_TABLE):
                op.drop_index(idx_name, table_name=TOKENS_TABLE)
        op.drop_table(TOKENS_TABLE)

    # 2. bookings.source
    if "bookings" in _tables() and SOURCE_IDX in _indexes("bookings"):
        op.drop_index(SOURCE_IDX, table_name="bookings")

    if is_postgres and "bookings" in _tables() and SOURCE_CHECK_CONSTRAINT_NAME in _checks("bookings"):
        op.drop_constraint(SOURCE_CHECK_CONSTRAINT_NAME, "bookings", type_="check")

    if "bookings" in _tables() and "source" in _columns("bookings"):
        op.drop_column("bookings", "source")

    # 1. bookings.client_request_id
    if is_postgres and "bookings" in _tables() and PARTIAL_UQ_CLIENT_REQUEST_ID in _indexes("bookings"):
        op.execute(sa.text("DROP INDEX IF EXISTS ix_bookings_client_request_id_partial"))

    if "bookings" in _tables() and "client_request_id" in _columns("bookings"):
        op.drop_column("bookings", "client_request_id")
