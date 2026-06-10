"""Workspace directory discovery and context file management."""

from pathlib import Path

from ctx.core.log import logger


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

        Returns relative paths from the context directory.
        Files that are not valid UTF-8 are skipped with a warning.
        """
        if not self._context.exists():
            return []

        files: list[str] = []
        for path in sorted(self._context.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self._context).as_posix()
            # Quick UTF-8 check — if it fails, skip
            try:
                path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                logger.warning("skipped non-text context file | path=%s", rel)
                continue
            except OSError:
                logger.warning("unreadable context file | path=%s", rel)
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
        # Security guard: ensure resolved path is still inside context_dir
        if not str(target).startswith(str(self._context.resolve())):
            raise ValueError(f"Path escapes context directory: {rel_path}")
        return target.read_text(encoding="utf-8")
