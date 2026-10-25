-- 0033_form_ratings — optional post-lift form assessment.
--
-- One 1-5 rating per exercise, after the lift. Ratings are descriptive inputs to the rubric
-- only; they never change a prescribed load or set. Workout ratings are append-only events and
-- are copied into session_form_rating on completion; later corrections supersede the old row.

CREATE TABLE workout_form_rating (
    form_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    workout_id  TEXT    NOT NULL REFERENCES workout_session(workout_id),
    exercise_id TEXT    NOT NULL,
    rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    note        TEXT,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_workout_form ON workout_form_rating(workout_id, exercise_id, form_id);

CREATE TRIGGER workout_form_rating_no_update BEFORE UPDATE ON workout_form_rating
BEGIN SELECT RAISE(ABORT, 'append-only: workout_form_rating rows cannot be updated'); END;
CREATE TRIGGER workout_form_rating_no_delete BEFORE DELETE ON workout_form_rating
BEGIN SELECT RAISE(ABORT, 'append-only: workout_form_rating rows cannot be deleted'); END;

CREATE TABLE session_form_rating (
    form_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT    NOT NULL REFERENCES session(session_id),
    exercise_id  TEXT    NOT NULL,
    rating       INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    note         TEXT,
    supersedes_id INTEGER REFERENCES session_form_rating(form_id),
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_session_form ON session_form_rating(session_id, exercise_id, form_id);

CREATE TRIGGER session_form_rating_no_update BEFORE UPDATE ON session_form_rating
BEGIN SELECT RAISE(ABORT, 'append-only: session_form_rating rows cannot be updated'); END;
CREATE TRIGGER session_form_rating_no_delete BEFORE DELETE ON session_form_rating
BEGIN SELECT RAISE(ABORT, 'append-only: session_form_rating rows cannot be deleted'); END;
