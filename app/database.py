from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _make_engine():
    settings = get_settings()
    return create_engine(settings.DATABASE_URL, pool_pre_ping=True)


class _LazyEngine:
    """Lazily creates the SQLAlchemy engine on first access."""

    def __init__(self):
        self._engine = None

    def _get(self):
        if self._engine is None:
            self._engine = _make_engine()
        return self._engine

    def connect(self):
        return self._get().connect()

    def dispose(self):
        if self._engine:
            self._engine.dispose()

    # Expose for Alembic / direct use
    def __getattr__(self, name):
        return getattr(self._get(), name)


engine = _LazyEngine()


def _get_session_factory():
    return sessionmaker(autocommit=False, autoflush=False, bind=engine._get())


class SessionLocal:
    """Context-manager wrapper that lazily creates sessions."""

    def __call__(self):
        factory = _get_session_factory()
        session = factory()
        return session

    def __enter__(self):
        self._session = _get_session_factory()()
        return self._session

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._session.close()


SessionLocal = SessionLocal()  # type: ignore[assignment]


def get_db():
    db = _get_session_factory()()
    try:
        yield db
    finally:
        db.close()
