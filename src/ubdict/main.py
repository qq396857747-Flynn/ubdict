"""UbDict entry point."""
from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from ubdict.paths import user_data_dir


def _setup_logging() -> None:
    log_dir = user_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    if sys.stderr is not None:
        logger.add(sys.stderr, level="INFO")
    logger.add(log_dir / "ubdict.log", rotation="2 MB", retention="7 days", level="DEBUG")


def main() -> int:
    _setup_logging()
    logger.info("Starting UbDict")

    # Ensure src is importable when running from source tree.
    here = Path(__file__).resolve()
    src_root = here.parents[2]
    if str(src_root) not in sys.path:
        sys.path.insert(0, str(src_root))

    from ubdict.app import UbDictApp

    app = UbDictApp()
    return app.run()


if __name__ == "__main__":
    raise SystemExit(main())
