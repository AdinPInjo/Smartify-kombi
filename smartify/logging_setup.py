"""
Centralized logging configuration for Smartify.
Import `logger` from this module throughout the application.
"""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict

# Initialize logger
logger = logging.getLogger("smartify")

# Configure logging if not already set up (prevents missing logs in systemd)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

# File logging (rotate to keep logs manageable)
_data_dir = Path(__file__).resolve().parent / "data"
_log_dir = _data_dir / "logs"
_log_dir.mkdir(parents=True, exist_ok=True)
_log_path = _log_dir / "smartify.log"

if not any(isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "") == str(_log_path) for h in logger.handlers):
    file_handler = RotatingFileHandler(
        _log_path,
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)


def log_exception(logger_obj: logging.Logger, message: str, **context: Dict[str, Any]) -> None:
    """
    Log an exception with optional structured context.
    """
    if context:
        message = f"{message} | context={context}"
    logger_obj.exception(message)
