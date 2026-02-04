import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logging():
    level_name = os.getenv("FT_LOG_LEVEL", "INFO").upper()
    if os.getenv("FT_DEBUG_LOG", "").lower() in ("1", "true", "yes", "on"):
        level_name = "DEBUG"
    level = getattr(logging, level_name, logging.INFO)

    log_dir = os.getenv("FT_LOG_DIR", "logs")
    log_file = os.getenv("FT_LOG_FILE", os.path.join(log_dir, "app.log"))
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    root = logging.getLogger()
    root.setLevel(level)

    if not root.handlers:
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)

        file_handler = RotatingFileHandler(
            log_file, maxBytes=5 * 1024 * 1024, backupCount=5
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
