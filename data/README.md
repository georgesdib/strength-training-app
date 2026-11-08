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

Use `tools/db_transfer.py` for a full-replacement transfer:

```bash
python tools/db_transfer.py export --db data/coach.db
python tools/db_transfer.py import --archive coach-db-*.tar.gz --db data/coach.db --force
```

Default import requires the source and target schemas to match. `--upgrade` accepts an older
source and applies the missing local migrations; `--upgrade-fill` also copies target-only rows
into the upgraded source, but only when every row can be matched or copied safely. Both modes
fail on a downgrade, a divergent migration, a row conflict, or any foreign-key/unique/trigger
problem.

Stop the app before importing. The tool checks the complete migration set and the database
checksum, refuses a target with SQLite WAL side files, and writes a `pre-transfer` backup
beside the target before replacing it. The archive contains personal health data and is not
encrypted.
