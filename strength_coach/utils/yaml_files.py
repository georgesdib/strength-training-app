"""Parse YAML configuration files once per file stamp.

Configuration is checked in, versioned and replaced wholesale; several loaders re-read and
re-parse the same file on every request because each one builds a fresh dataclass from it. The
parse is the expensive part (the exercise taxonomy alone takes ~65 ms), so the parsed document is
cached by (path, mtime_ns, size) and the loaders keep building their own objects from it.

The returned document is shared: callers must treat it as read-only and copy before mutating.
A config edit changes the stamp, so an edit is never served from the cache.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


@lru_cache(maxsize=64)
def _parse_file(source: str, _mtime_ns: int, _size: int) -> Any:
    return yaml.safe_load(Path(source).read_text(encoding="utf-8"))


def load_yaml_file(path: str | Path) -> Any:
    """Return one file's parsed YAML, re-parsing only when the stamp changes.

    A missing file raises, exactly as reading it would; callers that want "missing means empty"
    keep their own is_file() guard.
    """
    source = Path(path)
    stat = source.stat()
    return _parse_file(str(source), stat.st_mtime_ns, stat.st_size)
