"""Workspace directory discovery and context file management."""

from pathlib import Path

from ctx.core.log import logger


def get_workspace_path() -> Path:
    """Return the workspace directory for the current working directory."""
    return Path.cwd() / ".ctx"


def ensure_workspace() -> Path:
    """Create .ctx/ and .ctx/context/ if they don't exist; return the workspace path."""
    workspace = get_workspace_path()
    context_dir = workspace / "context"
    workspace.mkdir(parents=True, exist_ok=True)
    context_dir.mkdir(parents=True, exist_ok=True)
    logger.info("workspace ensured | path=%s", workspace)
    return workspace


def get_db_path() -> Path:
    """Return the local SQLite database path."""
    return get_workspace_path() / "conversations.db"


def get_context_dir() -> Path:
    """Return the context subdirectory path."""
    return get_workspace_path() / "context"


def list_context_files() -> list[str]:
    """Recursively list all plain text files under .ctx/context/.

    Returns relative paths from the context directory.
    Files that are not valid UTF-8 are skipped with a warning.
    """
    context_dir = get_context_dir()
    if not context_dir.exists():
        return []

    files: list[str] = []
    for path in sorted(context_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(context_dir).as_posix()
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


def read_context_file(rel_path: str) -> str:
    """Read a plain text file from .ctx/context/ and return its contents.

    Raises:
        FileNotFoundError: if the file does not exist.
        OSError: if the file cannot be read.
    """
    context_dir = get_context_dir()
    target = (context_dir / rel_path).resolve()
    # Security guard: ensure resolved path is still inside context_dir
    if not str(target).startswith(str(context_dir.resolve())):
        raise ValueError(f"Path escapes context directory: {rel_path}")
    return target.read_text(encoding="utf-8")
