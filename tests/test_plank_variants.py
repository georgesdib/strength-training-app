"""Side Plank and Chinese Plank are their own identities, and 0060 splits old rows."""

from __future__ import annotations

from pathlib import Path

from conftest import make_readiness, make_training

from strength_coach.store import db, importer
from strength_coach.utils import exercises

MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "strength_coach/store/migrations/0060_plank_variants.sql"
)
ROWS = [
    {"Date": "2024-01-01", "Exercise": "Side Plank", "Weight_Used": "0", "Reps_Done": "60"},
    {"Date": "2024-01-01", "Exercise": "Chinese Plank", "Weight_Used": "0", "Reps_Done": "90"},
    {"Date": "2024-01-01", "Exercise": "Regular Plank", "Weight_Used": "0", "Reps_Done": "120"},
]


def test_plank_variants_resolve_to_their_own_ids():
    taxonomy = exercises.taxonomy()
    assert taxonomy.resolve("Side Plank").id == "side_plank"
    assert taxonomy.resolve("Chinese Plank").id == "chinese_plank"
    # The generic plank keeps the plain and front hold, and remains the regex fallback.
    assert taxonomy.resolve("Regular Plank").id == "plank"
    assert taxonomy.resolve("Front Plank").id == "plank"
    assert taxonomy.resolve("Some New Plank").id == "plank"
    for name in ("Side Plank", "Chinese Plank"):
        resolved = taxonomy.resolve(name)
        assert resolved.rep_semantics == "seconds"
        assert resolved.is_time_based is True


def test_plank_variants_keep_their_declared_pattern():
    """A mis-clicked pattern would silently book the hold against the wrong volume bucket."""
    taxonomy = exercises.taxonomy()
    expected = {
        "Regular Plank": ("plank", "core_isometric"),
        "Front Plank": ("plank", "core_isometric"),
        "Side Plank": ("side_plank", "core_isometric"),
        # A hip-extension hold, not a trunk plank (DEC-VARIANT-05).
        "Chinese Plank": ("chinese_plank", "hip_extension"),
    }
    for name, (entity_id, pattern) in expected.items():
        assert taxonomy.resolve(name).id == entity_id, name
        entity = taxonomy.entities[entity_id]
        assert entity.get("pattern") == pattern, name
        assert entity.get("time_based") is True, name


def test_plank_variants_keep_their_primary_muscles():
    taxonomy = exercises.taxonomy()
    assert taxonomy.entities["plank"]["primary_muscles"] == ["abs"]
    assert taxonomy.entities["side_plank"]["primary_muscles"] == ["abs", "erectors"]
    assert taxonomy.entities["chinese_plank"]["primary_muscles"] == ["glutes"]


def test_migration_splits_rows_imported_before_the_split():
    store = db.Store(":memory:")
    try:
        conn = store.connection
        training = make_training(ROWS)
        readiness = make_readiness([{"Date": "2024-01-01"}])
        importer.import_export(
            conn, training, readiness,
            training_sha256=importer.sha256_frame(training),
            readiness_sha256=importer.sha256_frame(readiness),
        )
        # Rewind to the pre-split state: every plank variant was stored as `plank`.
        conn.execute("DROP TRIGGER clean_set_no_update")
        conn.execute("UPDATE clean_set SET exercise_id = 'plank'")
        conn.execute(
            "CREATE TRIGGER clean_set_no_update BEFORE UPDATE ON clean_set "
            "BEGIN SELECT RAISE(ABORT, "
            "'append-only: clean_set rows cannot be updated'); END"
        )
        conn.executescript(MIGRATION.read_text(encoding="utf-8"))
        stored = {
            row["raw_exercise"]: row["exercise_id"]
            for row in conn.execute("SELECT raw_exercise, exercise_id FROM clean_set")
        }
        remapped = conn.execute("SELECT COUNT(*) FROM exercise_remap_log").fetchone()[0]
    finally:
        store.close()
    assert stored == {
        "Side Plank": "side_plank",
        "Chinese Plank": "chinese_plank",
        "Regular Plank": "plank",
    }
    assert remapped == 2
