import json
import pytest
from hir_manual.protocol import strict_loads, validate_payload, validate_schema


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '[1]', 'prefix {"x":1}', '```json\n{}\n``` tail', '{"x":1e999}'])
def test_strict_rejects_ambiguous_json(raw):
    with pytest.raises(ValueError):
        strict_loads(raw)


def test_single_complete_fence():
    assert strict_loads('```json\n{"ok":true}\n```') == {"ok": True}


def test_string_boolean_rejected(fixture_json):
    payload = fixture_json("diagnosis")
    payload["sensitive"]["has_text"] = "true"
    with pytest.raises(ValueError):
        validate_payload("diagnose", payload)


def test_date_time_really_checked(fixture_json):
    state = fixture_json("state")
    state["created_at"] = "not-a-date"
    with pytest.raises(ValueError):
        validate_schema("state.schema.json", state)
