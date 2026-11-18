"""Cached YAML file parsing: one parse per file stamp, never a stale document."""

from __future__ import annotations

import os

import pytest
import yaml

from strength_coach.utils import yaml_files


@pytest.fixture(autouse=True)
def _clear_cache():
    yaml_files._parse_file.cache_clear()
    yield
    yaml_files._parse_file.cache_clear()


def _count_parses(monkeypatch):
    parses: list[str] = []
    real = yaml.safe_load

    def counting(text):
        parses.append(text)
        return real(text)

    monkeypatch.setattr(yaml_files.yaml, "safe_load", counting)
    return parses


def test_a_file_is_parsed_once_however_often_it_is_loaded(tmp_path, monkeypatch):
    source = tmp_path / "config.yaml"
    source.write_text("window_weeks: 4\n", encoding="utf-8")
    parses = _count_parses(monkeypatch)

    first = yaml_files.load_yaml_file(source)
    second = yaml_files.load_yaml_file(source)

    assert parses == ["window_weeks: 4\n"]
    assert first == second == {"window_weeks": 4}


def test_an_edit_is_never_served_from_the_cache(tmp_path):
    source = tmp_path / "config.yaml"
    source.write_text("window_weeks: 4\n", encoding="utf-8")
    assert yaml_files.load_yaml_file(source) == {"window_weeks": 4}

    source.write_text("window_weeks: 6\n", encoding="utf-8")
    before = source.stat()
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))

    assert yaml_files.load_yaml_file(source) == {"window_weeks": 6}


def test_two_files_with_the_same_content_are_cached_separately(tmp_path):
    first = tmp_path / "a.yaml"
    second = tmp_path / "b.yaml"
    first.write_text("window_weeks: 4\n", encoding="utf-8")
    second.write_text("window_weeks: 4\n", encoding="utf-8")

    first_doc = yaml_files.load_yaml_file(first)
    second.write_text("window_weeks: 9\n", encoding="utf-8")
    stat = second.stat()
    os.utime(second, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    assert yaml_files.load_yaml_file(first) is first_doc
    assert yaml_files.load_yaml_file(second) == {"window_weeks": 9}


def test_a_missing_file_still_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        yaml_files.load_yaml_file(tmp_path / "absent.yaml")
