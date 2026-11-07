"""Database transfer utility: full replacement, schema check, no destructive surprise."""

from __future__ import annotations

import contextlib
import sqlite3

import pytest

from strength_coach.store import db
from tools import db_transfer


def _make_db(path, probe: str) -> None:
    with db.Store(path) as store:
        store.connection.execute("CREATE TABLE probe (value TEXT)")
        store.connection.execute("INSERT INTO probe (value) VALUES (?)", (probe,))


def _probe(path) -> str:
    with contextlib.closing(sqlite3.connect(path)) as conn:
        return conn.execute("SELECT value FROM probe").fetchone()[0]


def _export(source, archive):
    return db_transfer.export_database(source, archive)


def test_round_trip_replaces_target_and_keeps_a_backup(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _make_db(source, "source")
    _make_db(target, "target")
    archive = tmp_path / "transfer.tar.gz"

    exported = _export(source, archive)
    assert archive.exists()
    assert exported.fingerprint == db_transfer.read_fingerprint(source)

    result = db_transfer.import_database(archive, target, force=True)
    assert result.backup is not None and result.backup.exists()
    assert _probe(target) == "source"
    assert db_transfer.read_fingerprint(target) == exported.fingerprint


def test_import_requires_force_and_leaves_target_untouched(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _make_db(source, "source")
    _make_db(target, "target")
    archive = tmp_path / "transfer.tar.gz"
    _export(source, archive)

    with pytest.raises(db_transfer.TransferError, match="--force"):
        db_transfer.import_database(archive, target, force=False)
    assert _probe(target) == "target"


def test_import_rejects_a_different_migration_set(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _make_db(source, "source")
    _make_db(target, "target")
    archive = tmp_path / "transfer.tar.gz"
    _export(source, archive)

    with contextlib.closing(sqlite3.connect(target)) as conn:
        latest = conn.execute("SELECT max(version) FROM schema_migration").fetchone()[0]
        conn.execute("DELETE FROM schema_migration WHERE version = ?", (latest,))
        conn.commit()

    with pytest.raises(db_transfer.TransferError, match="schema mismatch"):
        db_transfer.import_database(archive, target, force=True)
    assert _probe(target) == "target"


def test_import_rejects_a_changed_migration_checksum(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _make_db(source, "source")
    _make_db(target, "target")
    archive = tmp_path / "transfer.tar.gz"
    _export(source, archive)

    with contextlib.closing(sqlite3.connect(target)) as conn:
        latest = conn.execute("SELECT max(version) FROM schema_migration").fetchone()[0]
        conn.execute(
            "UPDATE schema_migration SET checksum = ? WHERE version = ?",
            ("0" * 64, latest),
        )
        conn.commit()

    with pytest.raises(db_transfer.TransferError, match="checksum differs"):
        db_transfer.import_database(archive, target, force=True)


def test_import_refuses_a_target_with_wal_sidecars(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _make_db(source, "source")
    _make_db(target, "target")
    archive = tmp_path / "transfer.tar.gz"
    _export(source, archive)

    sidecar = target.with_name(target.name + "-wal")
    sidecar.write_text("busy", encoding="utf-8")
    with pytest.raises(db_transfer.TransferError, match="in use"):
        db_transfer.import_database(archive, target, force=True)
    assert _probe(target) == "target"


def test_dry_run_checks_without_replacing(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _make_db(source, "source")
    _make_db(target, "target")
    archive = tmp_path / "transfer.tar.gz"
    _export(source, archive)

    result = db_transfer.import_database(archive, target, dry_run=True)
    assert result.dry_run
    assert result.backup is None
    assert _probe(target) == "target"


def test_archive_rejects_unexpected_members(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _make_db(source, "source")
    _make_db(target, "target")
    archive = tmp_path / "transfer.tar.gz"

    import tarfile

    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(source, arcname="coach.db")
        tar.add(manifest, arcname="manifest.json")
        tar.add(manifest, arcname="extra.txt")

    with pytest.raises(db_transfer.TransferError, match="unexpected archive member"):
        db_transfer.import_database(archive, target, force=True)


def test_export_does_not_leave_wal_sidecars_on_a_stopped_source(tmp_path):
    source = tmp_path / "source.db"
    _make_db(source, "source")
    archive = tmp_path / "transfer.tar.gz"

    _export(source, archive)

    assert not source.with_name(source.name + "-wal").exists()
    assert not source.with_name(source.name + "-shm").exists()


def test_import_rejects_a_tampered_database(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "target.db"
    _make_db(source, "source")
    _make_db(target, "target")
    archive = tmp_path / "transfer.tar.gz"
    _export(source, archive)

    import tarfile

    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        for name in ("coach.db", "manifest.json"):
            handle = tar.extractfile(name)
            assert handle is not None
            (extracted / name).write_bytes(handle.read())
    with (extracted / "coach.db").open("ab") as handle:
        handle.write(b"tampered")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(extracted / "coach.db", arcname="coach.db")
        tar.add(extracted / "manifest.json", arcname="manifest.json")

    with pytest.raises(db_transfer.TransferError, match="checksum"):
        db_transfer.import_database(archive, target, force=True)


def test_import_requires_an_existing_target(tmp_path):
    source = tmp_path / "source.db"
    _make_db(source, "source")
    archive = tmp_path / "transfer.tar.gz"
    _export(source, archive)

    with pytest.raises(db_transfer.TransferError, match="target database not found"):
        db_transfer.import_database(archive, tmp_path / "missing.db", force=True)
