# data/

This directory is git-ignored because everything in it is personal.

To run the tools locally, place your own exports here:

```
data/raw/training_log.csv     # training log export
data/raw/readiness.csv        # daily readiness export
```

The schemas those files are expected to follow are documented in
`docs/DATA-QUALITY.md` and `docs/DATA-MODEL.md`.

## Personal docs

Quantitative documents derived from a real log live in `private/`, which is also
git-ignored:

```
private/docs/EVIDENCE.md         # measured profile of the exports
private/docs/BASELINE.md         # current strength baseline
private/docs/INFO-REQUESTS.md    # personal goals/injury/suitability backlog
```

The public repository contains the methodology, schemas, rules and code. It does not
contain anyone's training data, bodyweight, injury history or derived metrics.

## Moving the database between machines

Use `tools/db_transfer.py` for a full-replacement transfer, not a merge:

```bash
python tools/db_transfer.py export --db data/coach.db
python tools/db_transfer.py import --archive coach-db-*.tar.gz --db data/coach.db --force
```

Stop the app before importing. The tool checks the complete migration set and the database
checksum, refuses a target with SQLite WAL side files, and writes a `pre-transfer` backup
beside the target before replacing it. The archive contains personal health data and is not
encrypted.
