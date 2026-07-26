import copy
import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "ctx"
CONFIG_PATH = CONFIG_DIR / "config.json"

# Default LLM model, user-overridable via config.json's top-level "model" key.
# Lives here (not in the framework-free conversation core) so it sits alongside
# the other user-settable defaults (ADR 0006 #3).
DEFAULT_MODEL = "openrouter/google/gemma-4-26b-a4b-it"

# The *system* prompt handed to the model when drafting a compression and no
# per-range prompt is supplied (ADR-0016 A#6, superseding A#1's user-turn text).
# The draft call sends the whole conversation as one user message with the target
# span wrapped in <compress_this>…</compress_this>, so the default is a marker-aware
# scaffold ("summarize only what is between the markers") plus the preserve-intent
# clause. Single source of the text: it seeds _DEFAULTS["compression"]
# ["default_prompt"] and conversation.py re-exports it as
# DEFAULT_COMPRESSION_PROMPT. Overriding is JSON-only (task 18); the user may edit
# the whole thing, markers included, at their own risk (power over protection).
DEFAULT_COMPRESSION_PROMPT = (
    "You are compressing part of an ongoing conversation. The full conversation is "
    "given to you as a single message, with one span wrapped in <compress_this> and "
    "</compress_this> markers. Summarize only the content between those markers; use "
    "everything outside them as context to understand that span, but do not "
    "summarize the rest. Preserve the facts, decisions, entities, and open threads "
    "needed for the conversation to continue coherently. Respond with only the "
    "summary text, no preamble."
)

# The *system* prompt handed to the model when drafting an ``import`` extract and
# no per-import prompt is supplied (ctx0 §4.2). Unlike the compression default it
# is marker-free — the whole user message is the one file to extract from, so the
# instruction only needs to say what to pull out and to emit the extract alone.
# Single source of the text: it seeds _DEFAULTS["import"]["default_prompt"].
DEFAULT_IMPORT_PROMPT = (
    "You are extracting the parts of a file that are relevant to an ongoing "
    "conversation. The file is given to you as a single message. Pull out only "
    "what is useful as context, preserving exact names, signatures, and values; "
    "drop boilerplate and anything irrelevant. Respond with only the extracted "
    "text, no preamble."
)

_DEFAULTS: dict = {
    "model": DEFAULT_MODEL,
    "compression": {
        "default_prompt": DEFAULT_COMPRESSION_PROMPT,
    },
    "import": {
        "default_prompt": DEFAULT_IMPORT_PROMPT,
    },
    # Web search: which of litellm's bundled backends to query, how many hits
    # to ask for, and how many tool calls one turn may make before the model
    # has to answer from what it has (ADR-0018 §5, plan D7). Swapping backend
    # is this one line plus that backend's key in the environment.
    "search": {
        "provider": "tavily",
        "max_results": 5,
        "max_tool_calls": 12,
    },
    # The single UI palette — the one place every color the app draws lives, so
    # retheming means editing here (and, in future, config.json) rather than
    # hunting hex values across the CSS. Two groups:
    #
    #   * Role bars (user/assistant/system/context/compression) — the left-edge
    #     bar per node role, applied in message_row.py via Color.parse. They keep
    #     their original fixed hex accents: they render as truecolor regardless of
    #     the ansi-dark theme, and a bar is a foreground glyph (not a background
    #     fill), so a fixed color here doesn't break terminal transparency. ANSI
    #     names (e.g. "ansi_blue") also work for palette-tracking bars.
    #   * Chrome (selection/seam/muted) — surfaced to the CSS as the variables
    #     $ctx-selection / $ctx-seam / $ctx-muted (ChatApp.get_css_variables), so
    #     the stylesheet reads them by name. "selection" is the hovered/selected
    #     row + split highlight; "seam" the pane/split dividers; "muted" the
    #     header model + gauge text.
    "colors": {
        "user": "#3b82f6",
        "assistant": "#f97316",
        "system": "#737373",
        "context": "#22c55e",
        # A compression summary shares the context-import green (both are
        # human-side, model-facing injections); the row's kind glyph (≡) is what
        # keeps a summary distinguishable from an imported file (task 39).
        "compression": "#22c55e",
        # A search the model ran gets its own hue rather than sharing the context
        # green: a fetched page *is* an import (same green), but a ranked hit list
        # is a different shape and must be tellable from one at a glance
        # (ADR-0018 §4). Violet is the furthest hue from the four already in use.
        "search": "#a855f7",
        "selection": "#3a3a3a",
        # Fixed white rather than an ANSI name: "ansi_white" is a light grey in
        # most palettes and "ansi_bright_white" varies by theme. The rules are
        # foreground glyphs, so a fixed color costs no terminal transparency.
        "seam": "#ffffff",
        "muted": "ansi_bright_black",
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
            "search": 2,
            "system": 1,
        },
        # Basis for the per-node weight % shown in the UI. "context" expresses
        # each node as a share of the current conversation's total tokens;
        # "window" expresses it as a share of the model's input window. Any
        # other value is coerced back to "context" in get_config().
        "weight_basis": "context",
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

    if isinstance(user_config.get("import"), dict):
        merged["import"] = {
            **_DEFAULTS["import"],
            **user_config["import"],
        }
    else:
        merged["import"] = copy.deepcopy(_DEFAULTS["import"])

    if isinstance(user_config.get("search"), dict):
        merged["search"] = {
            **_DEFAULTS["search"],
            **user_config["search"],
        }
    else:
        merged["search"] = copy.deepcopy(_DEFAULTS["search"])

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

    return merged
