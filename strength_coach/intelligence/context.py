"""Context identity for a capability response (contract §3.2, plan §4.4).

INT-1 has no baseline context package yet; that arrives with INT-2. What it needs now is the
identity of the *request context* so a response can be reproduced:

* the builder version,
* the database revision (the same data_version plus total_changes stamp the e1RM calibration
  cache already uses),
* the configuration revision,

and a deterministic hash over those plus the capability identity and its validated arguments.
INT-2 replaces the argument component with the baseline package; the field names and the hash
contract do not change.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

import strength_coach
from strength_coach.features.evidence import canonical_json

BUILDER_VERSION = "context.v1"


def database_revision(conn: sqlite3.Connection) -> int:
    """A cheap monotonic-ish stamp for the current database contents.

    PRAGMA data_version changes when another connection commits; total_changes counts this
    connection's writes. Together they catch a changed database even when a query would return
    the same rows. This is the same pair @features/e1rm_calibration@ uses for its cache.
    """
    data_version = int(conn.execute("PRAGMA data_version").fetchone()[0])
    return (data_version << 32) | (int(conn.total_changes) & 0xFFFF_FFFF)


def config_revision(config: Mapping[str, object]) -> str:
    payload = {"config": dict(config), "package_version": strength_coach.__version__}
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return "sha256:" + digest


@dataclass(frozen=True)
class ContextStamp:
    database_revision: int
    config_revision: str
    builder_version: str = BUILDER_VERSION

    def context_hash(
        self,
        *,
        capability: str,
        version: str,
        arguments: Mapping[str, object],
    ) -> str:
        payload = {
            "capability": capability,
            "version": version,
            "arguments": dict(arguments),
            "builder_version": self.builder_version,
            "database_revision": self.database_revision,
            "config_revision": self.config_revision,
        }
        digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
        return "sha256:" + digest


def stamp(conn: sqlite3.Connection, config: Mapping[str, object]) -> ContextStamp:
    return ContextStamp(
        database_revision=database_revision(conn),
        config_revision=config_revision(config),
    )
