"""Logging configuration for torrent cleaner."""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path


def _rotate_log_file(log_file: str, max_files: int) -> None:
    """Rotate existing log file by renaming it with a timestamp suffix.

    If log_file exists and is non-empty, rename it to
    ``{stem}-{mtime_timestamp}{suffix}`` (e.g. ``cleaner-20260212-020000.log``).
    Then enforce *max_files* by deleting the oldest rotated files.
    When *max_files* is 0, no files are deleted.
    """
    path = Path(log_file)
    if not path.exists() or path.stat().st_size == 0:
        return

    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    timestamp = mtime.strftime("%Y%m%d-%H%M%S")
    rotated = path.with_name(f"{path.stem}-{timestamp}{path.suffix}")
    path.rename(rotated)

    if max_files <= 0:
        return

    pattern = f"{path.stem}-*{path.suffix}"
    rotated_files = sorted(path.parent.glob(pattern))
    while len(rotated_files) > max_files:
        rotated_files.pop(0).unlink()


def setup_logger(
    name: str,
    log_level: str = "INFO",
    log_file: str | None = None,
    max_files: int = 5,
) -> logging.Logger:
    """
    Configure and return a logger instance.

    Args:
        name: Logger name
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Optional log file path
        max_files: Max rotated log files to keep (0 = keep all)

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, log_level.upper()))

    logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        _rotate_log_file(log_file, max_files)

        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    return logger
