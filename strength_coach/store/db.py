"""SQLite connection setup and numbered migrations.

The store is the only module allowed to touch SQLite directly; everything above it talks to
`repositories`.

Two rules live here:

* **Migrations are the schema.** There is no separate `schema.sql` to drift from the
  migration files -- the schema is exactly the ordered sum of `migrations/*.sql`, and the
  applied checksums are recorded so an edited historical migration is caught rather than
  silently skipped.
* **Foreign keys are enforced per connection** (`PRAGMA foreign_keys = ON`), because SQLite
  defaults them off and a dangling `raw_id` would otherwise never be noticed.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from strength_coach.utils import paths

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

_SQLITE_IN_MEMORY = ":memory:"

_BOOKKEEPING_DDL = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version    TEXT PRIMARY KEY,
    checksum   TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
"""


class MigrationError(RuntimeError):
    """A migration is missing, out of order, or has been edited after being applied."""


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    checksum: str

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


def default_db_path() -> Path:
    """`data/coach.db`; already git-ignored via the `*.db` rule."""
    return paths.data_dir("coach.db")


def discover_migrations(migrations_dir: str | Path | None = None) -> list[Migration]:
    """Every `NNNN_name.sql` under the migrations directory, in version order."""
    directory = Path(migrations_dir or MIGRATIONS_DIR)
    if not directory.is_dir():
        raise MigrationError(f"migrations directory not found: {directory}")
    migrations: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        version, _, _ = path.stem.partition("_")
        if not version.isdigit():
            raise MigrationError(f"migration name must start with a numeric version: {path.name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        migrations.append(Migration(version=version, path=path, checksum=digest))
    if not migrations:
        raise MigrationError(f"no migrations found in {directory}")
    versions = [m.version for m in migrations]
    if len(set(versions)) != len(versions):
        raise MigrationError(f"duplicate migration versions: {versions}")
    if versions != sorted(versions):
        raise MigrationError(f"migrations are not in version order: {versions}")
    return migrations


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open (or create) the database with the pragmas the store depends on."""
    target: str | Path
    if path is None:
        target = default_db_path()
    else:
        target = path
    if isinstance(target, Path) and str(target) != _SQLITE_IN_MEMORY:
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), isolation_level=None)
    conn.row_factory = sqlite3.Row
    # Enforced per connection, and off by default in SQLite.
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if str(target) != _SQLITE_IN_MEMORY:
        # WAL keeps a reader (the CLI) from blocking the writer (an import).
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def applied_migrations(conn: sqlite3.Connection) -> dict[str, str]:
    """Mapping of applied version -> recorded checksum."""
    conn.execute(_BOOKKEEPING_DDL)
    rows = conn.execute("SELECT version, checksum FROM schema_migration").fetchall()
    return {row["version"]: row["checksum"] for row in rows}


def migrate(
    conn: sqlite3.Connection,
    migrations_dir: str | Path | None = None,
) -> list[str]:
    """Apply pending migrations; return the versions applied by this call.

    Re-running is a no-op. An already-applied migration whose file has changed raises
    `MigrationError` instead of being skipped: otherwise two machines could run against
    different schemas while both reporting the same version.
    """
    migrations = discover_migrations(migrations_dir)
    applied = applied_migrations(conn)
    newly_applied: list[str] = []

    for migration in migrations:
        recorded = applied.get(migration.version)
        if recorded is not None:
            if recorded != migration.checksum:
                raise MigrationError(
                    f"migration {migration.path.name} was edited after being applied "
                    f"(recorded {recorded[:12]}, now {migration.checksum[:12]})"
                )
            continue
        try:
            conn.executescript(migration.sql)
            conn.execute(
                "INSERT INTO schema_migration (version, checksum) VALUES (?, ?)",
                (migration.version, migration.checksum),
            )
        except sqlite3.Error as exc:  # pragma: no cover - surfaced, never swallowed
            raise MigrationError(f"failed to apply {migration.path.name}: {exc}") from exc
        newly_applied.append(migration.version)

    return newly_applied


@contextmanager
def transaction(conn: sqlite3.Connection):
    """Run a unit of work atomically; use a savepoint when already in a transaction."""
    if conn.in_transaction:
        savepoint = f"sp_{id(conn)}"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            yield
        except Exception:
            conn.execute(f"ROLLBACK TO {savepoint}")
            conn.execute(f"RELEASE {savepoint}")
            raise
        else:
            conn.execute(f"RELEASE {savepoint}")
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()


class Store:
    """A migrated database connection. Use as a context manager."""

    def __init__(self, path: str | Path | None = None, *, auto_migrate: bool = True) -> None:
        self.path = path if path is not None else default_db_path()
        self.connection = connect(self.path)
        if auto_migrate:
            migrate(self.connection)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def tables(self) -> list[str]:
        rows = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return [row["name"] for row in rows]
