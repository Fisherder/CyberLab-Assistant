from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str) -> Engine:
    if database_url == "sqlite+pysqlite:///:memory:":
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
    if database_url.startswith("sqlite"):
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            future=True,
        )
    return create_engine(database_url, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False, future=True)


def init_db(engine: Engine) -> None:
    from cla import models  # noqa: F401

    Base.metadata.create_all(engine)
    _reconcile_sqlite_development_schema(engine)


def _reconcile_sqlite_development_schema(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    if "appeals" not in inspector.get_table_names():
        return

    appeal_columns = {column["name"] for column in inspector.get_columns("appeals")}
    if "criterion_id" in appeal_columns:
        return

    # 本地 SQLite 开发库可能来自旧版本；create_all 不会自动补齐既有表列。
    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE appeals ADD COLUMN criterion_id VARCHAR(120)")
        )


def session_scope(SessionLocal: sessionmaker[Session]) -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
