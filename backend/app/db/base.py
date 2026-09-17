"""Declarative base and portable column types.

The Phase 1A tables are deliberately built from types that behave identically
on PostgreSQL/TimescaleDB (production) and SQLite (hermetic tests):

* ``sa.Uuid`` - native ``uuid`` on PostgreSQL, ``CHAR(32)`` on SQLite.
* ``JSONVariant`` - ``JSONB`` on PostgreSQL, ``JSON`` elsewhere.
* String-backed enums with a CHECK constraint rather than native PG enums, so
  that adding an issue type in a later phase is an ordinary insert rather than
  an ``ALTER TYPE`` migration.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONVariant = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class UtcDateTime(sa.types.TypeDecorator[dt.datetime]):
    """A timezone-aware timestamp that stays aware on the way back out.

    Phase 1C section 9 forbids naive datetimes in the operational layer, but
    SQLite has no timezone storage and hands back naive values. Comparing one of
    those against an aware value raises ``TypeError`` at runtime - which is how a
    late-arrival check can crash on SQLite while passing on PostgreSQL.

    This decorator closes that gap in one place: values are normalised to UTC on
    the way in, and re-tagged as UTC on the way out when the driver dropped the
    offset. The emitted DDL is unchanged (``TIMESTAMP WITH TIME ZONE``), so it is
    not a migration-visible change.
    """

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: dt.datetime | None, dialect: object) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            # A naive value reaching persistence is a bug upstream; assume UTC
            # rather than letting the backend guess.
            return value.replace(tzinfo=dt.UTC)
        return value.astimezone(dt.UTC)

    def process_result_value(
        self, value: dt.datetime | None, dialect: object
    ) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.UTC)
        return value.astimezone(dt.UTC)


def enum_column(python_enum: type, *, length: int = 48) -> sa.Enum:
    """String-backed enum column that stores the enum *value*."""
    return sa.Enum(
        python_enum,
        native_enum=False,
        length=length,
        values_callable=lambda enum_cls: [member.value for member in enum_cls],
        validate_strings=True,
    )


# Deterministic constraint names keep Alembic diffs free of incidental churn.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)

    type_annotation_map: dict[Any, Any] = {
        dict[str, Any]: JSONVariant,
        uuid.UUID: sa.Uuid(as_uuid=True),
        dt.datetime: UtcDateTime(),
    }


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        UtcDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )
