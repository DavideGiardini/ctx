"""Tests for ctx.core.workspace.Workspace.

Oracle of record: tests/specs/workspace.md (authored code-blind).
Every assertion's expected value traces to a contract item (C1..C27),
NOT to any implementation detail. Each test cites its contract id in the
test name and in a comment/docstring.
"""

import os

import pytest

from ctx.core.workspace import Workspace

# ---------------------------------------------------------------------------
# Path properties
# ---------------------------------------------------------------------------

def test_c1_workspace_path_is_root_dot_ctx(tmp_path):
    # C1: Workspace(root).workspace_path == root / ".ctx"
    ws = Workspace(tmp_path)
    assert ws.workspace_path == tmp_path / ".ctx"


def test_c2_context_dir_is_root_dot_ctx_context(tmp_path):
    # C2: Workspace(root).context_dir == root / ".ctx" / "context"
    ws = Workspace(tmp_path)
    assert ws.context_dir == tmp_path / ".ctx" / "context"


def test_c3_db_path_is_root_dot_ctx_conversations_db(tmp_path):
    # C3: Workspace(root).db_path == root / ".ctx" / "conversations.db"
    ws = Workspace(tmp_path)
    assert ws.db_path == tmp_path / ".ctx" / "conversations.db"


def test_c4_reading_properties_is_pure(tmp_path):
    # C4: Accessing properties on a non-ensured workspace creates nothing on disk.
    ws = Workspace(tmp_path)
    _ = ws.workspace_path
    _ = ws.context_dir
    _ = ws.db_path
    assert not ws.workspace_path.exists()
    assert not ws.context_dir.exists()
    assert not ws.db_path.exists()
    assert not (tmp_path / ".ctx").exists()


def test_c5_property_parent_relationships(tmp_path):
    # C5: context_dir.parent == workspace_path and db_path.parent == workspace_path
    ws = Workspace(tmp_path)
    assert ws.context_dir.parent == ws.workspace_path
    assert ws.db_path.parent == ws.workspace_path


# ---------------------------------------------------------------------------
# ensure()
# ---------------------------------------------------------------------------

def test_c6_ensure_creates_directories(tmp_path):
    # C6: After ensure(), workspace_path and context_dir exist and are directories.
    ws = Workspace(tmp_path)
    assert not ws.workspace_path.exists()
    ws.ensure()
    assert ws.workspace_path.is_dir()
    assert ws.context_dir.is_dir()


def test_c7_ensure_returns_workspace_path(tmp_path):
    # C7: ensure() returns workspace_path.
    ws = Workspace(tmp_path)
    result = ws.ensure()
    assert result == ws.workspace_path


def test_c8_ensure_idempotent_and_non_destructive(workspace):
    # C8: Calling ensure() again does not error or destroy existing content.
    keep = workspace.context_dir / "keep.md"
    content = "Important notes\nthat must survive a re-ensure."
    keep.write_text(content, encoding="utf-8")

    workspace.ensure()  # second call

    assert workspace.workspace_path.is_dir()
    assert workspace.context_dir.is_dir()
    assert keep.exists()
    assert keep.read_text(encoding="utf-8") == content


# ---------------------------------------------------------------------------
# list_files()
# ---------------------------------------------------------------------------

def test_c9_list_files_no_ctx_returns_empty(tmp_path):
    # C9: Fresh, never-ensured workspace -> list_files() == [] (no error).
    ws = Workspace(tmp_path)
    assert ws.list_files() == []


def test_c10_list_files_empty_context_dir(workspace):
    # C10: Ensured workspace with empty context dir -> [].
    assert workspace.list_files() == []


def test_c11_list_files_single_file(workspace):
    # C11: One file context/notes.md -> ["notes.md"].
    (workspace.context_dir / "notes.md").write_text(
        "Project meeting notes for Q2.", encoding="utf-8"
    )
    assert workspace.list_files() == ["notes.md"]


def test_c12_list_files_sorted_by_posix_relative(workspace):
    # C12: zeta.md, alpha.md, beta.md -> sorted ["alpha.md", "beta.md", "zeta.md"].
    for name in ("zeta.md", "alpha.md", "beta.md"):
        (workspace.context_dir / name).write_text(
            f"Contents of {name}.", encoding="utf-8"
        )
    assert workspace.list_files() == ["alpha.md", "beta.md", "zeta.md"]


def test_c13_list_files_nested_uses_forward_slash(workspace):
    # C13: context/guides/setup.md -> contains "guides/setup.md".
    setup = workspace.context_dir / "guides" / "setup.md"
    setup.parent.mkdir(parents=True, exist_ok=True)
    setup.write_text("How to set up the environment.", encoding="utf-8")
    assert "guides/setup.md" in workspace.list_files()


def test_c14_list_files_excludes_directory_entries(workspace):
    # C14: context/docs/readme.md -> includes "docs/readme.md" but not "docs"/"docs/".
    readme = workspace.context_dir / "docs" / "readme.md"
    readme.parent.mkdir(parents=True, exist_ok=True)
    readme.write_text("Read me first before anything else.", encoding="utf-8")

    files = workspace.list_files()
    assert "docs/readme.md" in files
    assert "docs" not in files
    assert "docs/" not in files


def test_c15_list_files_skips_non_utf8_binary(workspace):
    # C15: text notes.md + non-UTF-8 blob.bin -> ["notes.md"] (binary skipped, no raise).
    (workspace.context_dir / "notes.md").write_text(
        "Plain readable text content.", encoding="utf-8"
    )
    (workspace.context_dir / "blob.bin").write_bytes(b"\xff\xfe\x00\x01\x80")
    assert workspace.list_files() == ["notes.md"]


def test_c16_list_files_mixed_text_and_binary_nested(workspace):
    # C16: intro.md + guides/setup.md (text) + image.bin + guides/data.bin (binary)
    #      -> ["guides/setup.md", "intro.md"].
    (workspace.context_dir / "intro.md").write_text(
        "Introduction to the project.", encoding="utf-8"
    )
    setup = workspace.context_dir / "guides" / "setup.md"
    setup.parent.mkdir(parents=True, exist_ok=True)
    setup.write_text("Setup guide details here.", encoding="utf-8")

    (workspace.context_dir / "image.bin").write_bytes(b"\xff\xfe\x00\x01\x80")
    (workspace.context_dir / "guides" / "data.bin").write_bytes(
        b"\x80\x81\x82\xff\x00"
    )

    assert workspace.list_files() == ["guides/setup.md", "intro.md"]


def test_c26_list_files_skips_unreadable_file(workspace):
    # C26. Skips a file it cannot read.
    # Root bypasses permission checks entirely, so the file would still be
    # readable and the skip behavior could not be observed.
    if os.geteuid() == 0:
        pytest.skip("running as root: permission bits do not constrain root")

    readable = workspace.context_dir / "readable.md"
    locked = workspace.context_dir / "locked.md"
    readable.write_text("# Readable\n\nThis is valid UTF-8 text.\n", encoding="utf-8")
    locked.write_text("# Locked\n\nThis is also valid UTF-8 text.\n", encoding="utf-8")

    os.chmod(locked, 0o000)
    try:
        # Some filesystems/environments ignore permission bits; if the file is
        # still readable, the precondition for this test does not hold.
        try:
            locked.read_text(encoding="utf-8")
            pytest.skip("filesystem ignores permission bits: locked.md is still readable")
        except (PermissionError, OSError):
            pass

        result = workspace.list_files()

        # The unreadable file must be silently skipped, not raise.
        assert "locked.md" not in result
        # The readable file must still be listed.
        assert "readable.md" in result
    finally:
        # Restore permissions so the temp dir can be cleaned up.
        os.chmod(locked, 0o644)


# ---------------------------------------------------------------------------
# read_file() and security boundary
# ---------------------------------------------------------------------------

def test_c17_read_file_returns_exact_content(workspace):
    # C17: read_file("notes.md") returns the exact multi-line UTF-8 string.
    content = "Line one of the note.\nLine two.\nLine three with unicode: café."
    (workspace.context_dir / "notes.md").write_text(content, encoding="utf-8")
    assert workspace.read_file("notes.md") == content


def test_c18_read_file_nested_returns_exact_content(workspace):
    # C18: read_file("guides/setup.md") returns exact content.
    content = "Step 1: install.\nStep 2: configure.\nStep 3: run."
    setup = workspace.context_dir / "guides" / "setup.md"
    setup.parent.mkdir(parents=True, exist_ok=True)
    setup.write_text(content, encoding="utf-8")
    assert workspace.read_file("guides/setup.md") == content


def test_c19_read_file_missing_raises_filenotfound(workspace):
    # C19: read_file("missing.md") on absent file -> FileNotFoundError.
    with pytest.raises(FileNotFoundError):
        workspace.read_file("missing.md")


def test_c20_read_file_dotdot_escape_raises_valueerror(workspace):
    # C20: read_file("../../etc/passwd") -> ValueError.
    with pytest.raises(ValueError):
        workspace.read_file("../../etc/passwd")


def test_c21_read_file_escape_nonexistent_raises_valueerror_not_fnf(workspace):
    # C21: escaping path to a non-existent location -> ValueError (guard before existence).
    with pytest.raises(ValueError):
        workspace.read_file("../../this/does/not/exist.md")


def test_c22_read_file_dotdot_resolving_back_inside_ok(workspace):
    # C22: read_file("../context/note.md") resolves back inside -> returns exact content.
    content = "Note that stays inside the sandbox."
    (workspace.context_dir / "note.md").write_text(content, encoding="utf-8")
    assert workspace.read_file("../context/note.md") == content


def test_c22_read_file_dotdot_resolving_back_inside_missing_raises_fnf(workspace):
    # C22 (optional): an in-sandbox path that resolves to a missing file should raise
    # FileNotFoundError, not ValueError.
    with pytest.raises(FileNotFoundError):
        workspace.read_file("../context/nonexistent.md")


def test_c23_read_file_absolute_path_raises_valueerror(workspace):
    # C23: read_file("/etc/passwd") absolute path -> ValueError.
    with pytest.raises(ValueError):
        workspace.read_file("/etc/passwd")


@pytest.mark.xfail(
    reason="BUG: read_file permits reading an out-of-bounds sibling dir whose name "
    "shares a prefix with 'context' (naive startswith containment guard) — "
    "contract C24; see tests/specs/FOUND-BUGS.md",
    strict=True,
)
def test_c24_read_file_sibling_prefix_dir_raises_valueerror(workspace):
    # C24: sibling dir sharing a name prefix (context-extra) is out of bounds -> ValueError.
    sibling = workspace.context_dir.parent / "context-extra"
    sibling.mkdir(parents=True, exist_ok=True)
    (sibling / "secret.txt").write_text("top secret sibling data", encoding="utf-8")

    with pytest.raises(ValueError):
        workspace.read_file("../context-extra/secret.txt")


def test_c25_read_file_symlink_escaping_raises_valueerror(workspace, tmp_path):
    # C25: symlink whose resolved target escapes the sandbox -> ValueError.
    outside = tmp_path / "outside_secret.md"
    outside.write_text("secret outside the sandbox", encoding="utf-8")

    link = workspace.context_dir / "link.md"
    os.symlink(outside, link)

    with pytest.raises(ValueError):
        workspace.read_file("link.md")


def test_c27_read_file_empty_target_resolves_to_dir_raises_oserror(workspace):
    # C27: read_file("") resolves to context_dir itself (a directory) -> OSError family.
    with pytest.raises(OSError):
        workspace.read_file("")
