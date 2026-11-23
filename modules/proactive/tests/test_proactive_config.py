import json

import pytest

from proactive import config


def test_defaults_valid_and_all_sources_off():
    cfg = config.load(None)
    assert not any(s["enabled"] for s in cfg["sources"].values())
    assert cfg["briefing"]["max_points"] == 5


def test_file_overrides_deeply_without_losing_siblings(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"sources": {"todo": {"enabled": True}}, "briefing": {"max_points": 3}}))
    cfg = config.load(path)
    assert cfg["sources"]["todo"]["enabled"] is True
    assert cfg["sources"]["todo"]["file"] == ""  # sibling key kept
    assert cfg["briefing"]["max_words"] == 200
    assert cfg["briefing"]["max_points"] == 3


def test_merge_does_not_mutate_inputs():
    base = {"a": {"b": 1}}
    out = config.merge(base, {"a": {"c": 2}})
    assert base == {"a": {"b": 1}} and out == {"a": {"b": 1, "c": 2}}


@pytest.mark.parametrize("patch", [
    {"sources": {"todo": {"enabled": "yes"}}},
    {"scoring": {"kinds": {"reply": {"weight": "high", "cap": 1}}}},
    {"scoring": {"kinds": {"reply": {"weight": 1, "cap": 0}}}},
    {"briefing": {"max_points": 0}},
    {"voice": {"hours": [13, 6]}},
])
def test_invalid_config_is_rejected(tmp_path, patch):
    path = tmp_path / "c.json"
    path.write_text(json.dumps(patch))
    with pytest.raises(ValueError):
        config.load(path)


def test_unreadable_or_non_object_config_is_rejected(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    with pytest.raises(ValueError):
        config.load(bad)
    arr = tmp_path / "arr.json"
    arr.write_text("[1]")
    with pytest.raises(ValueError):
        config.load(arr)
