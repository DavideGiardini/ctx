"""Tests for ctx.core.config.get_config().

Each test cites its contract id (C1..C18). Expected values trace to the
adjudicated contract for get_config(), never to the implementation.

`defaults` denotes the baseline config returned when the config file is
absent; per-test snapshots are captured via copy.deepcopy before any mutation.
"""

import copy
import json

import pytest

import ctx.core.config
from ctx.core.config import get_config


@pytest.fixture(autouse=True)
def _isolate_config_defaults():
    """Restore ctx.core.config._DEFAULTS after each test.

    get_config() shares the module-level defaults dict by reference, so a test
    that mutates a returned config can corrupt it for later tests. Snapshot and
    restore the contents in place (preserving the dict's identity) to keep tests
    independent.
    """
    snapshot = copy.deepcopy(ctx.core.config._DEFAULTS)
    yield
    ctx.core.config._DEFAULTS.clear()
    ctx.core.config._DEFAULTS.update(snapshot)


@pytest.fixture
def config_file(monkeypatch, tmp_path):
    """Isolate config I/O: point CONFIG_DIR/CONFIG_PATH at tmp_path.

    Returns a helper to control the on-disk state of the config file.
    """
    config_dir = tmp_path
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(ctx.core.config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(ctx.core.config, "CONFIG_PATH", config_path)

    class _Helper:
        def __init__(self, path):
            self.path = path

        def absent(self):
            if self.path.exists():
                self.path.unlink()

        def write_text(self, text):
            self.path.write_text(text)

        def write_json(self, obj):
            self.path.write_text(json.dumps(obj))

        def as_directory(self):
            self.path.mkdir(parents=True, exist_ok=True)

    return _Helper(config_path)


def _baseline(config_file):
    """Capture a fresh deepcopy of the baseline config (file absent)."""
    config_file.absent()
    return copy.deepcopy(get_config())


def test_c1_returns_dict(config_file):
    # C1
    config_file.absent()
    result = get_config()
    assert isinstance(result, dict)


def test_c2_absent_returns_baseline(config_file):
    # C2
    defaults = _baseline(config_file)
    config_file.absent()
    result = get_config()
    assert result == defaults


def test_c3_baseline_shape(config_file):
    # C3
    defaults = _baseline(config_file)
    assert set(defaults.keys()) == {"colors", "ui", "model"}

    # The default model is a non-empty string (ADR 0006 #3 — sourced from config).
    assert isinstance(defaults["model"], str)
    assert defaults["model"]

    assert set(defaults["colors"].keys()) == {
        "user",
        "assistant",
        "system",
        "context",
        "compression",
    }
    for value in defaults["colors"].values():
        assert isinstance(value, str)

    truncation = defaults["ui"]["truncation_lines"]
    assert set(truncation.keys()) == {"human", "assistant", "context", "system"}
    for value in truncation.values():
        assert isinstance(value, int)


def test_c4_absent_no_raise_returns_dict(config_file):
    # C4
    config_file.absent()
    result = get_config()
    assert isinstance(result, dict)


def test_c5_invalid_json_returns_defaults(config_file):
    # C5
    defaults = _baseline(config_file)
    config_file.write_text("not: valid: json {{{")
    result = get_config()
    assert result == defaults


def test_c6_empty_file_returns_defaults(config_file):
    # C6
    defaults = _baseline(config_file)
    config_file.write_text("")
    result = get_config()
    assert result == defaults


def test_c7_path_is_directory_returns_defaults(config_file):
    # C7
    defaults = _baseline(config_file)
    config_file.as_directory()
    result = get_config()
    assert result == defaults


def test_c8_empty_object_returns_defaults(config_file):
    # C8
    defaults = _baseline(config_file)
    config_file.write_text("{}")
    result = get_config()
    assert result == defaults


def test_c9_single_color_override_merges(config_file):
    # C9
    defaults = _baseline(config_file)
    config_file.write_json({"colors": {"user": "#123456"}})
    result = get_config()
    assert result["colors"]["user"] == "#123456"
    for k in defaults["colors"]:
        if k == "user":
            continue
        assert result["colors"][k] == defaults["colors"][k]


def test_c10_multiple_color_overrides_merge(config_file):
    # C10
    defaults = _baseline(config_file)
    config_file.write_json({"colors": {"user": "#111111", "assistant": "#222222"}})
    result = get_config()
    assert result["colors"]["user"] == "#111111"
    assert result["colors"]["assistant"] == "#222222"
    for k in defaults["colors"]:
        if k in ("user", "assistant"):
            continue
        assert result["colors"][k] == defaults["colors"][k]


def test_c11_single_truncation_override_merges(config_file):
    # C11
    defaults = _baseline(config_file)
    config_file.write_json({"ui": {"truncation_lines": {"human": 7}}})
    result = get_config()
    assert result["ui"]["truncation_lines"]["human"] == 7
    for k in defaults["ui"]["truncation_lines"]:
        if k == "human":
            continue
        assert result["ui"]["truncation_lines"][k] == defaults["ui"]["truncation_lines"][k]


def test_c12_extra_ui_flag_preserves_truncation(config_file):
    # C12
    defaults = _baseline(config_file)
    config_file.write_json({"ui": {"some_other_flag": True}})
    result = get_config()
    assert result["ui"]["truncation_lines"] == defaults["ui"]["truncation_lines"]
    assert result["ui"]["some_other_flag"] is True
    for k in defaults["ui"]:
        assert k in result["ui"]
        assert result["ui"][k] == defaults["ui"][k]


def test_c13_override_one_section_leaves_other_unchanged(config_file):
    # C13
    defaults = _baseline(config_file)

    config_file.write_json({"colors": {"user": "#123456"}})
    result_colors = get_config()
    assert result_colors["ui"] == defaults["ui"]

    some_trunc_key = next(iter(defaults["ui"]["truncation_lines"]))
    config_file.write_json({"ui": {"truncation_lines": {some_trunc_key: 99}}})
    result_ui = get_config()
    assert result_ui["colors"] == defaults["colors"]


def test_c14_unknown_top_level_key_added(config_file):
    # C14
    defaults = _baseline(config_file)
    config_file.write_json({"editor": "vim"})
    result = get_config()
    assert result["editor"] == "vim"
    assert result["colors"] == defaults["colors"]
    assert result["ui"] == defaults["ui"]


def test_c15_two_calls_absent_are_equal(config_file):
    # C15
    defaults = _baseline(config_file)
    config_file.absent()
    r1 = get_config()
    r2 = get_config()
    assert r1 == r2
    assert r1 == defaults


def test_c16_top_level_mutation_does_not_persist(config_file):
    # C16
    defaults = _baseline(config_file)
    config_file.absent()
    r1 = get_config()
    r1["colors"] = {}
    r1["new_key"] = "x"
    r2 = get_config()
    assert r2 == defaults


def test_c17_nested_mutation_does_not_persist(config_file):
    # C17
    defaults = _baseline(config_file)
    config_file.absent()
    r1 = get_config()
    r1["colors"]["user"] = "#deadbe"
    r2 = get_config()
    assert r2["colors"]["user"] == defaults["colors"]["user"]


def test_c18_wrong_typed_sections_do_not_raise(config_file):
    # C18
    config_file.write_json({"colors": "not-a-dict"})
    result = get_config()
    assert isinstance(result, dict)

    config_file.write_json({"ui": 42})
    result = get_config()
    assert isinstance(result, dict)


# C19
def test_c19_non_object_root_does_not_raise(config_file):
    defaults = _baseline(config_file)
    config_file.write_json(5)
    result = get_config()
    assert isinstance(result, dict)
    assert result == defaults


# C20
def test_c20_auto_truncation_value_passed_through(config_file):
    defaults = _baseline(config_file)
    config_file.write_json({"ui": {"truncation_lines": {"assistant": "auto"}}})
    result = get_config()
    assert result["ui"]["truncation_lines"]["assistant"] == "auto"
    for k in defaults["ui"]["truncation_lines"]:
        if k == "assistant":
            continue
        assert result["ui"]["truncation_lines"][k] == defaults["ui"]["truncation_lines"][k]


# C21
def test_c21_default_weight_basis_is_context(config_file):
    # Intent: with no config file, the effective config carries the documented
    # default ui.weight_basis == "context".
    config_file.absent()

    result = get_config()

    assert result["ui"]["weight_basis"] == "context"


# C22
def test_c22_valid_window_override_preserved(config_file):
    # Intent: "window" is one of the two legal values and a user-set legal value
    # must survive the per-section ui merge.
    config_file.write_json({"ui": {"weight_basis": "window"}})

    result = get_config()

    assert result["ui"]["weight_basis"] == "window"


# C23
@pytest.mark.parametrize(
    "illegal_value",
    [
        "banana",  # wrong string
        42,  # wrong type (int)
        None,  # null
        ["context"],  # list
    ],
)
def test_c23_illegal_weight_basis_coerced_to_context(config_file, illegal_value):
    # Intent: any value not exactly "context"/"window" is coerced to "context"
    # WITHOUT raising. Capture the baseline truncation_lines first (file absent),
    # then write the illegal config and assert coercion + sibling untouched.
    config_file.absent()
    baseline_truncation = _baseline(config_file)["ui"]["truncation_lines"]

    config_file.write_json({"ui": {"weight_basis": illegal_value}})

    # Must not raise on an invalid value.
    result = get_config()

    # Illegal value coerced back to the default.
    assert result["ui"]["weight_basis"] == "context"
    # Coercing weight_basis must not disturb the sibling ui default.
    assert result["ui"]["truncation_lines"] == baseline_truncation
