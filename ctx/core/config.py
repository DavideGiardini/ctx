import copy
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "ctx"
CONFIG_PATH = CONFIG_DIR / "config.json"

# Default LLM model, user-overridable via config.json's top-level "model" key.
# Lives here (not in the framework-free conversation core) so it sits alongside
# the other user-settable defaults (ADR 0006 #3).
DEFAULT_MODEL = "openrouter/google/gemma-4-26b-a4b-it"

# The preserve-info instruction handed to the model when drafting a compression
# and no per-range prompt is supplied (ADR-0016 A#1). Single source of the text:
# it seeds _DEFAULTS["compression"]["default_prompt"] and conversation.py
# re-exports it as DEFAULT_COMPRESSION_PROMPT. Overriding is JSON-only (task 18).
DEFAULT_COMPRESSION_PROMPT = (
    "Preserve the facts, decisions, entities, and open threads needed for the "
    "conversation to continue coherently."
)

_DEFAULTS: dict = {
    "model": DEFAULT_MODEL,
    "compression": {
        "default_prompt": DEFAULT_COMPRESSION_PROMPT,
    },
    "colors": {
        "user": "#3b82f6",
        "assistant": "#f97316",
        "system": "#737373",
        "context": "#22c55e",
        "compression": "#a855f7",
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
        # Basis for the per-node weight % shown in the UI. "context" expresses
        # each node as a share of the current conversation's total tokens;
        # "window" expresses it as a share of the model's input window. Any
        # other value is coerced back to "context" in get_config().
        "weight_basis": "context",
        # Whether the UI surfaces AI turns whose generation context has since
        # drifted from the current one (ADR-0016 concern "b"): gates *all* drift
        # UI, both the passive `Δ` marker and the active `g d` diff drill (task
        # 24) — off means no marker and `g d` is a no-op on a drifted turn (a K
        # still deep-dives). A non-bool user value is coerced back to this
        # default in get_config().
        "show_context_drift": True,
    },
}

_WEIGHT_BASES = ("context", "window")


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

    if isinstance(user_config.get("compression"), dict):
        merged["compression"] = {
            **_DEFAULTS["compression"],
            **user_config["compression"],
        }
    else:
        merged["compression"] = copy.deepcopy(_DEFAULTS["compression"])

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

    # Coerce an out-of-domain weight_basis (wrong string or wrong type) back to
    # the default. The merge above may have carried a user value verbatim.
    if merged["ui"].get("weight_basis") not in _WEIGHT_BASES:
        merged["ui"]["weight_basis"] = _DEFAULTS["ui"]["weight_basis"]

    # Coerce a non-bool show_context_drift (wrong type, incl. int masquerading as
    # bool) back to the default. A legitimate False (opt-out) survives.
    if not isinstance(merged["ui"].get("show_context_drift"), bool):
        merged["ui"]["show_context_drift"] = _DEFAULTS["ui"]["show_context_drift"]

    return merged
