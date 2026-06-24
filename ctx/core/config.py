import copy
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "ctx"
CONFIG_PATH = CONFIG_DIR / "config.json"

_DEFAULTS: dict[str, dict] = {
    "colors": {
        "user": "#3b82f6",
        "assistant": "#f97316",
        "system": "#737373",
        "context": "#22c55e",
    },
    "ui": {
        # Max lines a node occupies in the right-pane conversation graph before
        # it truncates. A value of "auto" disables truncation for that role.
        # Config keys mirror the Product Concept (section 7.7); the UI maps
        # "human" -> the "user" role.
        "truncation_lines": {
            "human": 2,
            "assistant": 2,
            "context": 2,
            "system": 1,
        },
    },
}


def get_config() -> dict:
    merged = copy.deepcopy(_DEFAULTS)
    if not CONFIG_PATH.exists():
        return merged
    try:
        with open(CONFIG_PATH) as f:
            user_config = json.load(f)
    except (json.JSONDecodeError, OSError):
        return merged

    # A valid-JSON but non-object root (e.g. 5 or [1, 2]) cannot be merged.
    if not isinstance(user_config, dict):
        return merged

    merged.update(user_config)

    # Re-merge known sections, but only when the user value is itself a mapping;
    # a wrong-typed section (e.g. {"colors": "blue"}) falls back to defaults.
    if isinstance(user_config.get("colors"), dict):
        merged["colors"] = {**_DEFAULTS["colors"], **user_config["colors"]}
    else:
        merged["colors"] = copy.deepcopy(_DEFAULTS["colors"])

    if isinstance(user_config.get("ui"), dict):
        merged["ui"] = {**_DEFAULTS["ui"], **user_config["ui"]}
        if isinstance(user_config["ui"].get("truncation_lines"), dict):
            merged["ui"]["truncation_lines"] = {
                **_DEFAULTS["ui"]["truncation_lines"],
                **user_config["ui"]["truncation_lines"],
            }
        else:
            merged["ui"]["truncation_lines"] = copy.deepcopy(
                _DEFAULTS["ui"]["truncation_lines"]
            )
    else:
        merged["ui"] = copy.deepcopy(_DEFAULTS["ui"])

    return merged
