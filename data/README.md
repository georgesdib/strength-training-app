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
