#!/usr/bin/env python3
"""Export and import a complete Strength Coach database between machines.

The default transfer is a **full replacement**, not a merge; `--upgrade-fill` is a narrow,
conservative exception for target-only rows. It is built for the case where one machine is
authoritative and another is used for development:

    # authoritative machine
    python tools/db_transfer.py export --db data/coach.db --include-local-config
    scp data/exports/coach-db-*.tar.gz dev-host:

    # development machine (stop the web server first)
    python tools/db_transfer.py import --archive coach-db-*.tar.gz --db data/coach.db --force --include-local-config
    python tools/db_transfer.py import --archive coach-db-*.tar.gz --db data/coach.db --create --force --include-local-config
    python tools/db_transfer.py import --archive coach-db-*.tar.gz --db data/coach.db --upgrade
    python tools/db_transfer.py import --archive coach-db-*.tar.gz --db data/coach.db --upgrade-fill

The archive contains a consistent SQLite snapshot and a JSON manifest, plus optional local
config files. The manifest records the full applied migration set (version and checksum), the
app version, the database size, the database SHA-256 and one size/SHA-256 entry per local
config file. Import verifies all of it before replacing anything. By default the source and
target schemas must match exactly.

--include-local-config adds the git-ignored local overlays (config/**/*.local.yaml) and
config/llm.local.toml, including the LLM key. Import requires the same flag when the archive
contains them, backs up existing local config files, and rolls the database back if the
config restore fails.

Two schema opt-in modes exist. --upgrade accepts an older source, applies the missing local
migrations to a copy, and fails on a downgrade or a divergent migration. --upgrade-fill does
the same and then copies target-only rows into the upgraded copy; it requires the target to
be at the local migration version and fails whenever a row cannot be matched or copied
safely. It never overwrites an existing row.

--create allows a missing target. The target is created at the local code's schema only after
all archive, schema and --force checks pass; a dry run never creates it. A created target has
no prior data, so no backup is written for it.

Import never runs while the target has SQLite WAL side files, and it writes an automatic
backup next to an existing target before replacing it. The tool does not label either side
authoritative; the operator decides which archive to import and must pass --force.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from strength_coach.store import db as store_db  # noqa: E402 - ROOT must be on sys.path first

FORMAT = "strength-coach-db-transfer"
# Version 2 adds optional local config overlays. Version 1 archives remain importable.
FORMAT_VERSION = 2
SUPPORTED_FORMAT_VERSIONS = (1, 2)
ARCHIVE_DB = "coach.db"
ARCHIVE_MANIFEST = "manifest.json"
ARCHIVE_CONFIG_DIR = "config"
LOCAL_CONFIG_DIR = ROOT / "config"


class TransferError(RuntimeError):
    """A transfer cannot proceed without risking the target database."""


@dataclass(frozen=True)
class SchemaFingerprint:
    """The applied migration set; the database's real schema version."""

    migrations: tuple[tuple[str, str], ...]

    @property
    def latest(self) -> str:
        return self.migrations[-1][0] if self.migrations else "none"

    @property
    def digest(self) -> str:
        payload = json.dumps(
            [{"version": version, "checksum": checksum} for version, checksum in self.migrations],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def as_manifest(self) -> dict[str, object]:
        return {
            "latest": self.latest,
            "fingerprint_sha256": self.digest,
            "migrations": [
                {"version": version, "checksum": checksum}
                for version, checksum in self.migrations
            ],
        }


@dataclass(frozen=True)
class ExportResult:
    db_path: Path
    archive: Path
    fingerprint: SchemaFingerprint
    db_sha256: str
    db_bytes: int
    local_config: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportResult:
    archive: Path
    db_path: Path
    source: SchemaFingerprint
    target: SchemaFingerprint
    backup: Path | None
    dry_run: bool
    created_target: bool = False
    upgraded_from: str | None = None
    filled_rows: int = 0
    local_config: tuple[str, ...] = ()
    config_backup: Path | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_local_config_name(name: str) -> bool:
    return name == "llm.local.toml" or name.endswith(".local.yaml")


def _local_config_files(config_dir: Path) -> list[Path]:
    if not config_dir.is_dir():
        return []
    files: list[Path] = []
    for path in config_dir.rglob("*"):
        if not _is_local_config_name(path.name):
            continue
        if path.is_symlink():
            raise TransferError(
                f"local config is a symlink; replace it with a regular file: {path}"
            )
        if path.is_file():
            files.append(path)
    return sorted(files)


def _config_manifest_entries(files: list[Path], config_dir: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for path in files:
        relative = path.relative_to(config_dir).as_posix()
        entries.append({
            "path": f"{ARCHIVE_CONFIG_DIR}/{relative}",
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        })
    return entries


def _safe_config_member(name: str) -> bool:
    if not name.startswith(f"{ARCHIVE_CONFIG_DIR}/"):
        return False
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts:
        return False
    if relative.as_posix() != name:
        return False
    return _is_local_config_name(relative.name)


def _config_target_path(config_dir: Path, archive_path: str) -> Path:
    if not _safe_config_member(archive_path):
        raise TransferError(f"unsafe local config path: {archive_path!r}")
    relative = PurePosixPath(archive_path).relative_to(ARCHIVE_CONFIG_DIR)
    return config_dir.joinpath(*relative.parts)


def _validate_config_targets(config_dir: Path, entries: list[dict[str, object]]) -> None:
    root = config_dir.expanduser().resolve()
    for entry in entries:
        archive_path = str(entry["path"])
        target = _config_target_path(root, archive_path)
        relative = PurePosixPath(archive_path).relative_to(ARCHIVE_CONFIG_DIR)
        current = root
        for part in relative.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise TransferError(
                    f"local config target uses a symlinked directory: {current}"
                )
        if target.is_symlink():
            raise TransferError(f"local config target is a symlink: {target}")
        try:
            target.resolve(strict=False).relative_to(root)
        except ValueError as exc:
            raise TransferError(f"local config target escapes {root}: {target}") from exc


def _backup_local_config(
    config_dir: Path,
    entries: list[dict[str, object]],
    backup_root: Path,
) -> Path | None:
    existing = [
        _config_target_path(config_dir, str(entry["path"]))
        for entry in entries
        if _config_target_path(config_dir, str(entry["path"])).is_file()
    ]
    if not existing:
        return None
    backup_root = backup_root.expanduser().resolve()
    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    directory = backup_root / f"local-config-pre-transfer-{stamp}"
    counter = 1
    while directory.exists():
        directory = backup_root / f"local-config-pre-transfer-{stamp}-{counter}"
        counter += 1
    directory.mkdir(mode=0o700)
    for target in existing:
        destination = directory / target.relative_to(config_dir)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, destination)
        os.chmod(destination, 0o600)
    return directory


def _apply_local_config(
    archive_root: Path,
    config_dir: Path,
    entries: list[dict[str, object]],
    backup_root: Path,
) -> Path | None:
    _validate_config_targets(config_dir, entries)
    staged: list[tuple[Path, Path]] = []
    replaced: list[tuple[Path, Path | None]] = []
    try:
        for entry in entries:
            target = _config_target_path(config_dir, str(entry["path"]))
            target.parent.mkdir(parents=True, exist_ok=True)
            staged_path = target.with_name(f".{target.name}.transfer-{os.getpid()}")
            shutil.copyfile(archive_root / str(entry["path"]), staged_path)
            os.chmod(staged_path, 0o600)
            staged.append((staged_path, target))
        backup = _backup_local_config(config_dir, entries, backup_root)
        for staged_path, target in staged:
            backup_path = (
                backup / target.relative_to(config_dir) if backup is not None else None
            )
            os.replace(staged_path, target)
            replaced.append((target, backup_path))
        return backup
    except Exception:
        for target, backup_path in reversed(replaced):
            if backup_path is not None and backup_path.exists():
                shutil.copyfile(backup_path, target)
                os.chmod(target, 0o600)
            else:
                target.unlink(missing_ok=True)
        raise
    finally:
        for staged_path, _ in staged:
            staged_path.unlink(missing_ok=True)


def _app_version() -> str:
    try:
        from strength_coach import __version__

        return __version__
    except Exception:
        return "unknown"


def _connect_read_only(path: Path) -> sqlite3.Connection:
    # URI mode prevents a missing or non-database file from being created or modified.
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _fingerprint_from_connection(conn: sqlite3.Connection, where: Path) -> SchemaFingerprint:
    try:
        rows = conn.execute(
            "SELECT version, checksum FROM schema_migration ORDER BY version"
        ).fetchall()
    except sqlite3.Error as exc:
        raise TransferError(f"{where} is not a Strength Coach database: {exc}") from exc
    if not rows:
        raise TransferError(f"{where} has no applied migrations; refusing to transfer an empty schema")
    migrations = tuple((str(row[0]), str(row[1])) for row in rows)
    return SchemaFingerprint(migrations)


def read_fingerprint(path: Path) -> SchemaFingerprint:
    """Read the migration set without modifying the database."""
    if not path.is_file():
        raise TransferError(f"database not found: {path}")
    with contextlib.closing(_connect_read_only(path)) as conn:
        return _fingerprint_from_connection(conn, path)


def _sidecar_paths(db_path: Path) -> tuple[Path, Path]:
    return (
        db_path.with_name(db_path.name + "-wal"),
        db_path.with_name(db_path.name + "-shm"),
    )


def _local_fingerprint() -> SchemaFingerprint:
    migrations = store_db.discover_migrations()
    return SchemaFingerprint(tuple((item.version, item.checksum) for item in migrations))


def _is_ancestor(older: SchemaFingerprint, newer: SchemaFingerprint) -> bool:
    if len(older.migrations) > len(newer.migrations):
        return False
    return older.migrations == newer.migrations[:len(older.migrations)]


def _require_ancestor(candidate: SchemaFingerprint, code: SchemaFingerprint, label: str) -> None:
    if _is_ancestor(candidate, code):
        return
    raise TransferError(
        f"{label} schema is not an ancestor of the local migrations "
        f"(database {candidate.latest}, code {code.latest}); "
        "downgrade or divergent migrations are not supported"
    )


def _upgrade_source(source_db: Path, source: SchemaFingerprint, code: SchemaFingerprint) -> SchemaFingerprint:
    if source == code:
        return source
    _require_ancestor(source, code, "source")
    conn = store_db.connect(source_db)
    try:
        store_db.migrate(conn)
    except store_db.MigrationError as exc:
        raise TransferError(f"source database upgrade failed: {exc}") from exc
    finally:
        conn.close()
    upgraded = read_fingerprint(source_db)
    if upgraded != code:
        raise TransferError(
            f"source database did not reach the local schema after upgrade "
            f"(got {upgraded.latest}, expected {code.latest})"
        )
    return upgraded


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table_names(conn: sqlite3.Connection, schema: str) -> list[str]:
    rows = conn.execute(
        f"SELECT name FROM {schema}.sqlite_master "
        "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name != 'schema_migration' "
        "ORDER BY name"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _columns(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA {schema}.table_info({_quote(table)})").fetchall()
    return [str(row[1]) for row in rows]


def _primary_key(conn: sqlite3.Connection, schema: str, table: str) -> list[str]:
    rows = conn.execute(f"PRAGMA {schema}.table_info({_quote(table)})").fetchall()
    ordered = sorted((row for row in rows if row[5]), key=lambda row: row[5])
    return [str(row[1]) for row in ordered]


def _table_has_insert_trigger(conn: sqlite3.Connection, table: str) -> bool:
    rows = conn.execute(
        "SELECT sql FROM main.sqlite_master WHERE type = 'trigger' AND tbl_name = ?",
        (table,),
    ).fetchall()
    return any("INSERT" in (row[0] or "").upper() for row in rows)


def _count(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def _copy_target_only_rows(conn: sqlite3.Connection, table: str, columns: list[str], pks: list[str]) -> int:
    quoted = ", ".join(_quote(column) for column in columns)
    join = " AND ".join(f"s.{_quote(pk)} IS t.{_quote(pk)}" for pk in pks)
    before = conn.total_changes
    conn.execute(
        f"INSERT INTO main.{_quote(table)} ({quoted}) "
        f"SELECT {quoted} FROM target.{_quote(table)} AS t "
        f"WHERE NOT EXISTS (SELECT 1 FROM main.{_quote(table)} AS s WHERE {join})"
    )
    return conn.total_changes - before


def _fill_from_target(source_db: Path, target_db: Path, temp_dir: Path) -> int:
    target_copy = temp_dir / "target-fill.db"
    shutil.copyfile(target_db, target_copy)
    conn = sqlite3.connect(str(source_db))
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("ATTACH DATABASE ? AS target", (str(target_copy),))
        conn.execute("BEGIN")
        try:
            main_tables = _table_names(conn, "main")
            target_tables = _table_names(conn, "target")
            if set(main_tables) != set(target_tables):
                raise TransferError("cannot fill: source and target table sets differ")
            filled = 0
            for table in main_tables:
                columns = _columns(conn, "main", table)
                if columns != _columns(conn, "target", table):
                    raise TransferError(f"cannot fill table {table}: column sets differ")
                quoted = ", ".join(_quote(column) for column in columns)
                source_count = _count(conn, f"SELECT COUNT(*) FROM main.{_quote(table)}")
                target_count = _count(conn, f"SELECT COUNT(*) FROM target.{_quote(table)}")
                pks = _primary_key(conn, "main", table)

                if not pks:
                    if source_count == 0 and target_count > 0:
                        if _table_has_insert_trigger(conn, table):
                            raise TransferError(f"cannot fill table {table}: INSERT trigger present")
                        before = conn.total_changes
                        try:
                            conn.execute(
                                f"INSERT INTO main.{_quote(table)} ({quoted}) "
                                f"SELECT {quoted} FROM target.{_quote(table)}"
                            )
                        except sqlite3.IntegrityError as exc:
                            raise TransferError(f"cannot fill table {table}: {exc}") from exc
                        filled += conn.total_changes - before
                        continue
                    extra = _count(
                        conn,
                        f"SELECT COUNT(*) FROM (SELECT {quoted} FROM main.{_quote(table)} "
                        f"EXCEPT SELECT {quoted} FROM target.{_quote(table)})",
                    )
                    missing = _count(
                        conn,
                        f"SELECT COUNT(*) FROM (SELECT {quoted} FROM target.{_quote(table)} "
                        f"EXCEPT SELECT {quoted} FROM main.{_quote(table)})",
                    )
                    if extra or missing:
                        raise TransferError(
                            f"cannot merge table {table} without a primary key"
                        )
                    continue

                join = " AND ".join(f"s.{_quote(pk)} IS t.{_quote(pk)}" for pk in pks)
                source_only = _count(
                    conn,
                    f"SELECT COUNT(*) FROM main.{_quote(table)} AS s "
                    f"WHERE NOT EXISTS (SELECT 1 FROM target.{_quote(table)} AS t WHERE {join})",
                )
                if source_only:
                    raise TransferError(
                        f"source has {source_only} row(s) that target lacks in {table}; "
                        "refusing to guess which side is newer"
                    )
                non_pk = [column for column in columns if column not in pks]
                if non_pk:
                    differs = " OR ".join(
                        f"s.{_quote(column)} IS NOT t.{_quote(column)}" for column in non_pk
                    )
                    conflicts = _count(
                        conn,
                        f"SELECT COUNT(*) FROM main.{_quote(table)} AS s "
                        f"JOIN target.{_quote(table)} AS t ON {join} WHERE {differs}",
                    )
                    if conflicts:
                        raise TransferError(
                            f"{conflicts} row conflict(s) in {table}; refusing to overwrite either side"
                        )
                target_only = _count(
                    conn,
                    f"SELECT COUNT(*) FROM target.{_quote(table)} AS t "
                    f"WHERE NOT EXISTS (SELECT 1 FROM main.{_quote(table)} AS s WHERE {join})",
                )
                if target_only:
                    if _table_has_insert_trigger(conn, table):
                        raise TransferError(f"cannot fill table {table}: INSERT trigger present")
                    try:
                        filled += _copy_target_only_rows(conn, table, columns, pks)
                    except sqlite3.IntegrityError as exc:
                        raise TransferError(f"cannot fill table {table}: {exc}") from exc

            problems = conn.execute("PRAGMA main.foreign_key_check").fetchall()
            if problems:
                raise TransferError(
                    f"foreign-key check failed after fill ({len(problems)} row(s)); "
                    "the target was not changed"
                )
            integrity = conn.execute("PRAGMA main.integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise TransferError("integrity check failed after fill; the target was not changed")
            conn.execute("COMMIT")
            return filled
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()


def _snapshot_database(source: Path, destination: Path) -> None:
    """Write a consistent copy using SQLite's backup API, not a raw file copy."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    before = tuple(path.exists() for path in _sidecar_paths(source))
    try:
        with (
            contextlib.closing(_connect_read_only(source)) as src,
            contextlib.closing(sqlite3.connect(destination)) as dst,
        ):
            src.backup(dst)
    finally:
        # A read-only open of a WAL database creates -wal/-shm. Remove only the sidecars
        # this process created; a running app's sidecars are left untouched.
        for existed, path in zip(before, _sidecar_paths(source), strict=True):
            if not existed and path.exists():
                path.unlink()


def _default_export_path() -> Path:
    directory = ROOT / "data" / "exports"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory / f"coach-db-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"


def export_database(
    db_path: Path,
    archive: Path,
    *,
    force: bool = False,
    include_local_config: bool = False,
    config_dir: Path | None = None,
) -> ExportResult:
    """Create a single archive containing a consistent snapshot and its manifest."""
    db_path = db_path.expanduser().resolve()
    archive = archive.expanduser().resolve()
    if not db_path.is_file():
        raise TransferError(f"database not found: {db_path}")
    if archive == db_path:
        raise TransferError("archive path must not be the database itself")
    if archive.exists() and not force:
        raise TransferError(f"archive already exists: {archive} (pass --force to replace it)")

    config_root = Path(config_dir or LOCAL_CONFIG_DIR).expanduser().resolve()
    config_files = _local_config_files(config_root) if include_local_config else []
    config_entries = _config_manifest_entries(config_files, config_root)

    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="strength-db-export-") as temp_dir:
        temp = Path(temp_dir)
        snapshot = temp / ARCHIVE_DB
        _snapshot_database(db_path, snapshot)
        fingerprint = read_fingerprint(snapshot)
        digest = _sha256(snapshot)
        size = snapshot.stat().st_size
        manifest = {
            "format": FORMAT,
            "format_version": FORMAT_VERSION,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "app_version": _app_version(),
            "source_name": db_path.name,
            "db_sha256": digest,
            "db_bytes": size,
            "schema": fingerprint.as_manifest(),
            "local_config": config_entries,
        }
        manifest_path = temp / ARCHIVE_MANIFEST
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(snapshot, arcname=ARCHIVE_DB)
            tar.add(manifest_path, arcname=ARCHIVE_MANIFEST)
            for source, entry in zip(config_files, config_entries, strict=True):
                tar.add(source, arcname=str(entry["path"]))

    os.chmod(archive, 0o600)
    return ExportResult(
        db_path=db_path,
        archive=archive,
        fingerprint=fingerprint,
        db_sha256=digest,
        db_bytes=size,
        local_config=tuple(str(entry["path"]) for entry in config_entries),
    )


def _extract_archive(archive: Path, destination: Path) -> tuple[Path, dict]:
    """Extract the database, manifest and any declared local config files."""
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members: dict[str, tarfile.TarInfo] = {}
            for member in tar.getmembers():
                expected = member.name in {ARCHIVE_DB, ARCHIVE_MANIFEST}
                if not expected and not _safe_config_member(member.name):
                    raise TransferError(f"unexpected archive member: {member.name!r}")
                if not member.isfile():
                    raise TransferError(f"archive member is not a regular file: {member.name!r}")
                if member.name in members:
                    raise TransferError(f"duplicate archive member: {member.name!r}")
                members[member.name] = member
            if not {ARCHIVE_DB, ARCHIVE_MANIFEST}.issubset(members):
                raise TransferError("archive must contain coach.db and manifest.json")
            for name, member in members.items():
                handle = tar.extractfile(member)
                if handle is None:
                    raise TransferError(f"cannot read archive member: {name}")
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(handle.read())
    except tarfile.TarError as exc:
        raise TransferError(f"archive is not a valid .tar.gz: {exc}") from exc
    try:
        manifest = json.loads((destination / ARCHIVE_MANIFEST).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TransferError("manifest.json is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise TransferError("manifest.json must contain a JSON object")
    return destination / ARCHIVE_DB, manifest


def _validate_local_config_manifest(
    manifest: dict,
    archive_root: Path,
    format_version: int,
) -> list[dict[str, object]]:
    entries = manifest.get("local_config")
    if format_version == 1:
        if entries not in (None, []):
            raise TransferError("format version 1 must not declare local config")
        entries = []
    if not isinstance(entries, list):
        raise TransferError("manifest local_config must be a list")
    declared: list[dict[str, object]] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise TransferError("manifest local config entries are malformed")
        path = entry.get("path")
        expected_sha = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        if not isinstance(path, str) or not _safe_config_member(path):
            raise TransferError(f"unsafe local config path in manifest: {path!r}")
        if path in seen:
            raise TransferError(f"duplicate local config entry: {path}")
        seen.add(path)
        target = archive_root / path
        if not target.is_file():
            raise TransferError(f"local config file missing from archive: {path}")
        if expected_bytes != target.stat().st_size:
            raise TransferError(f"local config size does not match the manifest: {path}")
        if expected_sha != _sha256(target):
            raise TransferError(f"local config checksum does not match the manifest: {path}")
        declared.append({"path": path, "sha256": expected_sha, "bytes": expected_bytes})
    config_root = archive_root / ARCHIVE_CONFIG_DIR
    actual = {
        path.relative_to(archive_root).as_posix()
        for path in config_root.rglob("*")
        if path.is_file()
    }
    if actual != seen:
        extra = sorted(actual - seen)
        missing = sorted(seen - actual)
        details = []
        if extra:
            details.append(f"undeclared: {', '.join(extra)}")
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        raise TransferError("local config members do not match the manifest (" + "; ".join(details) + ")")
    return declared


def _validate_manifest(
    manifest: dict,
    db_path: Path,
    fingerprint: SchemaFingerprint,
    archive_root: Path,
) -> list[dict[str, object]]:
    if manifest.get("format") != FORMAT:
        raise TransferError(f"not a {FORMAT} archive")
    format_version = manifest.get("format_version")
    if format_version not in SUPPORTED_FORMAT_VERSIONS:
        raise TransferError(f"unsupported archive format version: {format_version!r}")
    if manifest.get("db_sha256") != _sha256(db_path):
        raise TransferError("database checksum does not match the manifest")
    if manifest.get("db_bytes") != db_path.stat().st_size:
        raise TransferError("database size does not match the manifest")
    schema = manifest.get("schema")
    if not isinstance(schema, dict) or not isinstance(schema.get("migrations"), list):
        raise TransferError("manifest has no schema migration list")
    try:
        recorded = tuple(
            (str(row["version"]), str(row["checksum"])) for row in schema["migrations"]
        )
    except (KeyError, TypeError) as exc:
        raise TransferError("manifest schema entries are malformed") from exc
    if recorded != fingerprint.migrations:
        raise TransferError("manifest schema does not match the database inside the archive")
    if schema.get("latest") != fingerprint.latest:
        raise TransferError("manifest schema latest version does not match the archive")
    if schema.get("fingerprint_sha256") != fingerprint.digest:
        raise TransferError("manifest schema fingerprint does not match the archive")
    return _validate_local_config_manifest(manifest, archive_root, int(format_version))


def _require_same_schema(source: SchemaFingerprint, target: SchemaFingerprint) -> None:
    if source.migrations == target.migrations:
        return
    source_map = dict(source.migrations)
    target_map = dict(target.migrations)
    only_source = sorted(set(source_map) - set(target_map))
    only_target = sorted(set(target_map) - set(source_map))
    changed = sorted(
        version
        for version in set(source_map) & set(target_map)
        if source_map[version] != target_map[version]
    )
    details = [f"source latest {source.latest}, target latest {target.latest}"]
    if only_source:
        details.append(f"only source: {', '.join(only_source)}")
    if only_target:
        details.append(f"only target: {', '.join(only_target)}")
    if changed:
        details.append(f"checksum differs: {', '.join(changed)}")
    raise TransferError("database schema mismatch: " + "; ".join(details))


def _require_not_in_use(db_path: Path) -> None:
    # Opening a WAL database read-only creates -wal/-shm sidecars, so this check must not
    # open the target. A running app always leaves the sidecars while it holds the database.
    for suffix in ("-wal", "-shm"):
        sidecar = db_path.with_name(db_path.name + suffix)
        if sidecar.exists():
            raise TransferError(
                f"target database is in use ({sidecar.name} exists); stop the app before import"
            )


def _backup_target(db_path: Path, backup_dir: Path | None) -> Path:
    directory = (backup_dir or db_path.parent).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = directory / f"{db_path.name}.pre-transfer-{stamp}"
    counter = 1
    while backup.exists():
        backup = directory / f"{db_path.name}.pre-transfer-{stamp}-{counter}"
        counter += 1
    # The target has no WAL sidecars at this point, so a raw copy is a consistent snapshot.
    shutil.copyfile(db_path, backup)
    os.chmod(backup, 0o600)
    return backup


def _read_fingerprint_copy(path: Path, temp_dir: Path) -> SchemaFingerprint:
    # Inspect a copy so the target itself never gets WAL sidecars from this read.
    copy = temp_dir / f"{path.name}.fingerprint"
    shutil.copyfile(path, copy)
    return read_fingerprint(copy)


def _verify_database(path: Path, expected: SchemaFingerprint, temp_dir: Path) -> None:
    actual = _read_fingerprint_copy(path, temp_dir)
    if actual != expected:
        raise TransferError("written database schema does not match the source")
    copy = temp_dir / f"{path.name}.integrity"
    shutil.copyfile(path, copy)
    with contextlib.closing(_connect_read_only(copy)) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok":
        raise TransferError(f"database integrity check failed: {result[0] if result else 'no result'}")


def import_database(
    archive: Path,
    db_path: Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    backup_dir: Path | None = None,
    upgrade: bool = False,
    fill: bool = False,
    create: bool = False,
    include_local_config: bool = False,
    config_dir: Path | None = None,
) -> ImportResult:
    """Verify an archive and replace the target database if every check passes."""
    archive = archive.expanduser().resolve()
    db_path = db_path.expanduser().resolve()
    config_root = Path(config_dir or LOCAL_CONFIG_DIR).expanduser().resolve()
    if not archive.is_file():
        raise TransferError(f"archive not found: {archive}")
    if db_path.exists() and not db_path.is_file():
        raise TransferError(f"target path is not a file: {db_path}")
    target_missing = not db_path.is_file()
    if target_missing and not create:
        raise TransferError(
            f"target database not found: {db_path}; create it before importing or pass --create"
        )
    if fill and not upgrade:
        upgrade = True

    _require_not_in_use(db_path)
    with tempfile.TemporaryDirectory(prefix="strength-db-import-") as temp_dir:
        temp = Path(temp_dir)
        source_db, manifest = _extract_archive(archive, temp)
        source_fingerprint = read_fingerprint(source_db)
        local_config = _validate_manifest(
            manifest, source_db, source_fingerprint, temp
        )
        if local_config and not include_local_config:
            raise TransferError(
                "archive contains local config; pass --include-local-config to restore it"
            )
        if local_config:
            _validate_config_targets(config_root, local_config)
        # A missing target has the local code's schema: it will be created at that schema if
        # the transfer succeeds. A dry run checks against that same fingerprint without
        # creating the file or a backup.
        target_fingerprint = (
            _local_fingerprint() if target_missing else _read_fingerprint_copy(db_path, temp)
        )

        upgraded_from = None
        filled_rows = 0
        if upgrade:
            code = _local_fingerprint()
            _require_ancestor(source_fingerprint, code, "source")
            _require_ancestor(target_fingerprint, code, "target")
            if fill and target_fingerprint != code:
                raise TransferError(
                    "--upgrade-fill requires the target to be at the local migration version; "
                    "upgrade the target database first"
                )
            upgraded_from = source_fingerprint.latest if source_fingerprint != code else None
            source_fingerprint = _upgrade_source(source_db, source_fingerprint, code)
            if fill and not target_missing:
                filled_rows = _fill_from_target(source_db, db_path, temp)
        else:
            _require_same_schema(source_fingerprint, target_fingerprint)
        _require_not_in_use(db_path)

        config_paths = tuple(str(entry["path"]) for entry in local_config)
        if dry_run:
            return ImportResult(
                archive=archive,
                db_path=db_path,
                source=source_fingerprint,
                target=target_fingerprint,
                backup=None,
                dry_run=True,
                created_target=target_missing,
                upgraded_from=upgraded_from,
                filled_rows=filled_rows,
                local_config=config_paths,
            )
        if not force:
            raise TransferError(
                f"refusing to replace {db_path}; pass --force after confirming the target"
            )

        # A missing target has no data to preserve, so it gets no backup. The staged file is
        # replaced into place atomically, creating the database only after every check passed.
        backup = None if target_missing else _backup_target(db_path, backup_dir)
        _require_not_in_use(db_path)
        staged = db_path.with_name(f".{db_path.name}.transfer-{os.getpid()}")
        replaced = False
        config_backup = None
        try:
            _snapshot_database(source_db, staged)
            os.chmod(staged, 0o600)
            _verify_database(staged, source_fingerprint, temp)
            os.replace(staged, db_path)
            replaced = True
            _verify_database(db_path, source_fingerprint, temp)
            if local_config:
                try:
                    config_backup = _apply_local_config(
                        temp,
                        config_root,
                        local_config,
                        backup_dir or db_path.parent,
                    )
                except Exception as exc:
                    # A failed config restore must not leave the database silently ahead of
                    # the local config; roll the database back as well.
                    if backup is not None:
                        shutil.copyfile(backup, db_path)
                        os.chmod(db_path, 0o600)
                    else:
                        db_path.unlink(missing_ok=True)
                    raise TransferError(
                        f"local config restore failed; database import was rolled back: {exc}"
                    ) from exc
        except Exception:
            if replaced:
                # The replacement was written but did not verify; put the previous target
                # back, or remove the newly created file when there was no previous target.
                if backup is not None:
                    shutil.copyfile(backup, db_path)
                    os.chmod(db_path, 0o600)
                else:
                    db_path.unlink(missing_ok=True)
            raise
        finally:
            if staged.exists():
                staged.unlink()

    return ImportResult(
        archive=archive,
        db_path=db_path,
        source=source_fingerprint,
        target=target_fingerprint,
        backup=backup,
        dry_run=False,
        created_target=target_missing,
        upgraded_from=upgraded_from,
        filled_rows=filled_rows,
        local_config=config_paths,
        config_backup=config_backup,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export or import a complete Strength Coach database (full replacement).",
        epilog=(
            "Default import requires exact schema equality. --upgrade applies missing local "
            "migrations to an older source and fails on downgrade. --upgrade-fill also copies "
            "target-only rows and fails if any row cannot be merged safely. Use "
            "--include-local-config to carry git-ignored local overlays; import requires it "
            "when the archive contains them. Import is destructive: stop the app, verify the "
            "source, and pass --force. Use --dry-run to check everything without replacing "
            "the target."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser("export", help="write a transfer archive from a local database")
    export.add_argument("--db", type=Path, default=ROOT / "data" / "coach.db")
    export.add_argument("--out", type=Path, default=None, help="archive path (.tar.gz)")
    export.add_argument("--force", action="store_true", help="replace an existing archive")
    export.add_argument(
        "--include-local-config",
        action="store_true",
        help=(
            "also include git-ignored config/*.local.yaml and config/llm.local.toml; "
            "this includes the LLM key"
        ),
    )

    imp = sub.add_parser("import", help="verify an archive and replace a local database")
    imp.add_argument("--archive", type=Path, required=True)
    imp.add_argument("--db", type=Path, default=ROOT / "data" / "coach.db")
    imp.add_argument("--backup-dir", type=Path, default=None)
    imp.add_argument("--force", action="store_true", help="required to replace the database")
    imp.add_argument(
        "--include-local-config",
        action="store_true",
        help="restore local config files from the archive; required when the archive has them",
    )
    imp.add_argument(
        "--create",
        action="store_true",
        help="allow a missing target; create it at the local schema during import",
    )
    imp.add_argument("--dry-run", action="store_true", help="check everything, replace nothing")
    mode = imp.add_mutually_exclusive_group()
    mode.add_argument(
        "--upgrade",
        action="store_true",
        help="apply missing local migrations to an older source; fail on downgrade",
    )
    mode.add_argument(
        "--upgrade-fill",
        action="store_true",
        help="upgrade, then copy target-only rows; fail if the merge is not safe",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "export":
            output = args.out.expanduser() if args.out else _default_export_path()
            result = export_database(
                args.db,
                output,
                force=args.force,
                include_local_config=args.include_local_config,
            )
            print(f"Archive: {result.archive}")
            print(f"Source:  {result.db_path}")
            print(f"Schema:  {result.fingerprint.latest} ({len(result.fingerprint.migrations)} migrations)")
            print(f"Size:    {result.db_bytes / (1024 * 1024):.1f} MiB")
            print(f"SHA256:  {result.db_sha256}")
            if result.local_config:
                print(
                    f"Local config: {len(result.local_config)} file(s) "
                    "(may include the LLM key)"
                )
            print("Warning: contains personal health data; the archive is not encrypted.")
            return 0

        result = import_database(
            args.archive,
            args.db,
            force=args.force,
            dry_run=args.dry_run,
            backup_dir=args.backup_dir,
            upgrade=args.upgrade or args.upgrade_fill,
            fill=args.upgrade_fill,
            create=args.create,
            include_local_config=args.include_local_config,
        )
        print(f"Source schema: {result.source.latest}")
        print(f"Target schema: {result.target.latest}")
        if result.created_target:
            print("Target: would be created" if result.dry_run else "Target: created")
        if result.upgraded_from:
            print(f"Upgraded source: {result.upgraded_from} -> {result.source.latest}")
        if result.filled_rows:
            print(f"Filled target-only rows: {result.filled_rows}")
        if result.local_config:
            print(f"Local config: {len(result.local_config)} file(s)")
        if result.dry_run:
            print("Dry run: checks passed; target was not changed.")
        else:
            print(f"Backup: {result.backup}" if result.backup else "Backup: none (new target)")
            if result.config_backup:
                print(f"Config backup: {result.config_backup}")
            print(f"Imported: {result.db_path}")
        return 0
    except TransferError as exc:
        print(f"db_transfer: {exc}", file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error) as exc:
        print(f"db_transfer: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
