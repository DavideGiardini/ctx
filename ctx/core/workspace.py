"""Workspace directory discovery and context file management."""

import codecs
from pathlib import Path

from ctx.core.log import logger

# Bytes read to classify a file as text. Bounded so listing cost is independent
# of file size (ADR 0008 #1): one small read per file, never the whole file.
SNIFF_BYTES = 8192


def _sniff_is_text(chunk: bytes) -> bool:
    """Return True if an ~8 KB prefix looks like UTF-8 text.

    A file qualifies when its prefix contains no NUL byte and decodes as UTF-8.
    Decoding is incremental with ``final=False`` so a multi-byte character split
    across the sniff boundary is tolerated rather than reported as invalid. This
    matches what ``read_file`` (UTF-8) can actually consume, so the picker and the
    reader agree by construction (ADR 0008 #1).
    """
    if b"\x00" in chunk:
        return False
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        decoder.decode(chunk, final=False)
    except UnicodeDecodeError:
        return False
    return True


class Workspace:
    """Deep module: owns workspace path discovery, creation, and file access.

    Encapsulates the `.ctx/` directory structure and all filesystem I/O
    related to context files, removing the global `Path.cwd()` dependency.
    """

    def __init__(self, root_path: Path) -> None:
        self._root = root_path
        self._workspace = root_path / ".ctx"
        self._context = self._workspace / "context"

    @property
    def workspace_path(self) -> Path:
        return self._workspace

    @property
    def context_dir(self) -> Path:
        return self._context

    @property
    def db_path(self) -> Path:
        return self._workspace / "conversations.db"

    def ensure(self) -> Path:
        """Create .ctx/ and .ctx/context/ if they don't exist; return the workspace path."""
        self._workspace.mkdir(parents=True, exist_ok=True)
        self._context.mkdir(parents=True, exist_ok=True)
        logger.info("workspace ensured | path=%s", self._workspace)
        return self._workspace

    def list_files(self) -> list[str]:
        """Recursively list all plain text files under .ctx/context/.

        Returns relative paths from the context directory. A file is included
        only if (1) its resolved path stays inside the context directory — the
        same containment guard ``read_file`` enforces, so a symlink escaping the
        sandbox is never listed — and (2) its first ~8 KB sniff as UTF-8 text.
        Files failing either check are skipped with a warning rather than raised.
        """
        if not self._context.exists():
            return []

        context_root = self._context.resolve()
        files: list[str] = []
        for path in sorted(self._context.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self._context).as_posix()
            # Containment guard (mirrors read_file): a symlink that resolves
            # outside context/ must not be listed, else read_file would reject it.
            if not path.resolve().is_relative_to(context_root):
                logger.warning("skipped out-of-bounds context file | path=%s", rel)
                continue
            try:
                with path.open("rb") as handle:
                    chunk = handle.read(SNIFF_BYTES)
            except OSError:
                logger.warning("unreadable context file | path=%s", rel)
                continue
            if not _sniff_is_text(chunk):
                logger.warning("skipped non-text context file | path=%s", rel)
                continue
            files.append(rel)
        logger.info("context files listed | count=%d", len(files))
        return files

    def read_file(self, rel_path: str) -> str:
        """Read a plain text file from .ctx/context/ and return its contents.

        Raises:
            FileNotFoundError: if the file does not exist.
            OSError: if the file cannot be read.
            ValueError: if the path escapes the context directory.
        """
        target = (self._context / rel_path).resolve()
        # Security guard: ensure resolved path is still inside context_dir.
        # Compare resolved paths for containment (not a string prefix), so a
        # sibling dir merely sharing a name prefix (e.g. context-extra) is rejected.
        if not target.is_relative_to(self._context.resolve()):
            raise ValueError(f"Path escapes context directory: {rel_path}")
        return target.read_text(encoding="utf-8")
