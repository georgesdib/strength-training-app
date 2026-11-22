# Narrow check lanes. Rationale and the mapping live in tools/check.py; the policy is in
# docs/AGENT-WORKFLOWS.md ("Test lanes"). Run `make check` while editing and `make full` once
# before a push; do not loop the full selection.
PY ?= $(shell test -x .venv/bin/python && echo .venv/bin/python || echo python)
F ?=

.PHONY: check lint docs full hook

check:
	$(PY) tools/check.py $(if $(F),--files $(F))

lint:
	$(PY) tools/check.py lint $(if $(F),--files $(F))

docs:
	$(PY) tools/check.py docs

full:
	$(PY) tools/check.py full

hook:
	$(PY) tools/check.py install-hook
