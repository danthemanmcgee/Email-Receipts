import os

# Set a dummy DATABASE_URL before any imports so the lazy engine doesn't need psycopg2
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from sqlalchemy.orm import configure_mappers  # noqa: E402
from sqlalchemy.orm import instrumentation as sa_instrumentation  # noqa: E402
from sqlalchemy.orm.state import InstanceState  # noqa: E402

# Import all models to register them with the mapper
from app.models.card import PhysicalCard, CardAlias  # noqa: E402, F401
from app.models.receipt import Receipt, AttachmentLog  # noqa: E402, F401
from app.models.integration import GoogleConnection  # noqa: E402, F401
from app.models.setting import AllowedSender, AppSetting  # noqa: E402, F401
from app.models.job import JobRun  # noqa: E402, F401

# Configure all mappers so InstrumentedAttribute.impl is populated
configure_mappers()


def _patched_new(cls, *args, **kwargs):
    """Patch __new__ so SQLAlchemy instances created without __init__ still work."""
    instance = object.__new__(cls)
    manager = sa_instrumentation.manager_of_class(cls)
    if manager is not None:
        instance._sa_instance_state = InstanceState(instance, manager)
    return instance


# Apply patch to models used in tests with __new__
PhysicalCard.__new__ = staticmethod(_patched_new)
CardAlias.__new__ = staticmethod(_patched_new)
GoogleConnection.__new__ = staticmethod(_patched_new)
AllowedSender.__new__ = staticmethod(_patched_new)
AppSetting.__new__ = staticmethod(_patched_new)
Receipt.__new__ = staticmethod(_patched_new)
AttachmentLog.__new__ = staticmethod(_patched_new)
JobRun.__new__ = staticmethod(_patched_new)
