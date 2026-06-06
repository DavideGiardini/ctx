import logging
from pathlib import Path

LOG_DIR = Path.home() / ".local" / "state" / "ctx"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "ctx.log"

_handler = logging.FileHandler(LOG_FILE, mode="a")
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))

logger = logging.getLogger("ctx")
logger.setLevel(logging.DEBUG)
logger.addHandler(_handler)