"""SQLite persistence: migrations, append-only repositories, import orchestration.

Layering: below `features`. May import `utils`, `domain` and `ingest` only.
"""

from strength_coach.store.db import (
    MigrationError,
    Store,
    connect,
    default_db_path,
    discover_migrations,
    migrate,
)
from strength_coach.store.importer import ImportReport, import_export

__all__ = [
    "ImportReport",
    "MigrationError",
    "Store",
    "connect",
    "default_db_path",
    "discover_migrations",
    "import_export",
    "migrate",
]
