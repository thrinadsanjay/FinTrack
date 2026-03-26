import logging
import os
import time
from logging.handlers import RotatingFileHandler

DEFAULT_LOG_DIR = "/fintracker/logs"
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 10

_IS_CONFIGURED = False


class UTCFormatter(logging.Formatter):
    converter = time.gmtime


class LoggerPrefixFilter(logging.Filter):
    def __init__(self, *prefixes: str):
        super().__init__()
        self.prefixes = tuple(prefixes)

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith(self.prefixes)


class ExcludeLoggerPrefixFilter(logging.Filter):
    def __init__(self, *prefixes: str):
        super().__init__()
        self.prefixes = tuple(prefixes)

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.name.startswith(self.prefixes)


class MinimumLevelFilter(logging.Filter):
    def __init__(self, min_level: int):
        super().__init__()
        self.min_level = min_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.min_level


def _env_int(name: str, default: int) -> int:
    try:
        return int(str(os.getenv(name, str(default))).strip())
    except (TypeError, ValueError):
        return default


def _rotating_handler(
    file_path: str,
    formatter: logging.Formatter,
    max_bytes: int,
    backup_count: int,
) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        file_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    return handler


def setup_logging() -> None:
    global _IS_CONFIGURED
    if _IS_CONFIGURED:
        return

    level_name = os.getenv("FT_LOG_LEVEL", "INFO").upper()
    if os.getenv("FT_DEBUG_LOG", "").lower() in ("1", "true", "yes", "on"):
        level_name = "DEBUG"
    level = getattr(logging, level_name, logging.INFO)

    log_dir = str(os.getenv("FT_LOG_DIR", DEFAULT_LOG_DIR)).strip() or DEFAULT_LOG_DIR
    max_bytes = _env_int("FT_LOG_MAX_BYTES", DEFAULT_MAX_BYTES)
    backup_count = _env_int("FT_LOG_BACKUP_COUNT", DEFAULT_BACKUP_COUNT)

    os.makedirs(log_dir, exist_ok=True)

    app_log_file = os.getenv("FT_LOG_FILE", os.path.join(log_dir, "application.log"))
    audit_log_file = os.getenv("FT_AUDIT_LOG_FILE", os.path.join(log_dir, "audit.log"))
    telegram_log_file = os.getenv("FT_TELEGRAM_LOG_FILE", os.path.join(log_dir, "telegram.log"))
    scheduler_log_file = os.getenv("FT_SCHEDULER_LOG_FILE", os.path.join(log_dir, "scheduler.log"))
    error_log_file = os.getenv("FT_ERROR_LOG_FILE", os.path.join(log_dir, "error.log"))

    formatter = UTCFormatter(
        "%(asctime)sZ | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    if root.handlers:
        _IS_CONFIGURED = True
        return

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    app_handler = _rotating_handler(app_log_file, formatter, max_bytes, backup_count)
    app_handler.addFilter(
        ExcludeLoggerPrefixFilter(
            "app.services.audit",
            "app.routers.telegram_bot",
            "app.services.telegram",
            "app.schedulers",
            "apscheduler",
        )
    )
    root.addHandler(app_handler)

    audit_handler = _rotating_handler(audit_log_file, formatter, max_bytes, backup_count)
    audit_handler.addFilter(LoggerPrefixFilter("app.services.audit"))
    root.addHandler(audit_handler)

    telegram_handler = _rotating_handler(telegram_log_file, formatter, max_bytes, backup_count)
    telegram_handler.addFilter(LoggerPrefixFilter("app.routers.telegram_bot", "app.services.telegram"))
    root.addHandler(telegram_handler)

    scheduler_handler = _rotating_handler(scheduler_log_file, formatter, max_bytes, backup_count)
    scheduler_handler.addFilter(LoggerPrefixFilter("app.schedulers", "apscheduler"))
    root.addHandler(scheduler_handler)

    error_handler = _rotating_handler(error_log_file, formatter, max_bytes, backup_count)
    error_handler.addFilter(MinimumLevelFilter(logging.ERROR))
    root.addHandler(error_handler)

    _IS_CONFIGURED = True
