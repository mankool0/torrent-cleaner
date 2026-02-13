"""Tests for log rotation in src/utils/logger.py."""

import os
from pathlib import Path

import pytest

from src.utils.logger import _rotate_log_file


@pytest.fixture
def log_dir(tmp_path):
    """Return a temporary directory for log files."""
    return tmp_path


def _make_log(log_dir: Path, name: str = "cleaner.log", content: str = "log line\n") -> Path:
    """Create a log file with some content and return its path."""
    p = log_dir / name
    p.write_text(content)
    return p


class TestRotateLogFile:
    def test_renames_existing_file_with_timestamp(self, log_dir):
        log_file = _make_log(log_dir)
        _rotate_log_file(str(log_file), max_files=5)

        # Original file should be gone
        assert not log_file.exists()
        # A rotated file should exist
        rotated = list(log_dir.glob("cleaner-*.log"))
        assert len(rotated) == 1
        assert rotated[0].read_text() == "log line\n"

    def test_noop_when_file_missing(self, log_dir):
        _rotate_log_file(str(log_dir / "missing.log"), max_files=5)
        assert list(log_dir.glob("*.log")) == []

    def test_noop_when_file_empty(self, log_dir):
        log_file = log_dir / "cleaner.log"
        log_file.write_text("")
        _rotate_log_file(str(log_file), max_files=5)
        # File should remain untouched
        assert log_file.exists()
        assert list(log_dir.glob("cleaner-*.log")) == []

    def test_cleanup_deletes_oldest(self, log_dir):
        # Pre-create 2 rotated files with distinct timestamps
        (log_dir / "cleaner-20260101-000000.log").write_text("old1")
        (log_dir / "cleaner-20260102-000000.log").write_text("old2")

        # Create the current log file to trigger rotation
        log_file = _make_log(log_dir)

        _rotate_log_file(str(log_file), max_files=2)

        rotated = sorted(log_dir.glob("cleaner-*.log"))
        assert len(rotated) == 2
        # The oldest (20260101) should have been deleted
        names = [r.name for r in rotated]
        assert "cleaner-20260101-000000.log" not in names

    def test_max_files_zero_keeps_all(self, log_dir):
        # Pre-create several rotated files
        for i in range(5):
            (log_dir / f"cleaner-2026010{i}-000000.log").write_text(f"old{i}")

        log_file = _make_log(log_dir)
        _rotate_log_file(str(log_file), max_files=0)

        rotated = list(log_dir.glob("cleaner-*.log"))
        # 5 pre-existing + 1 newly rotated = 6
        assert len(rotated) == 6

    def test_timestamp_uses_mtime(self, log_dir):
        log_file = _make_log(log_dir)
        # Set mtime to a known value
        mtime = 1750000245.0
        os.utime(log_file, (mtime, mtime))

        from datetime import datetime, timezone
        expected_ts = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y%m%d-%H%M%S")

        _rotate_log_file(str(log_file), max_files=5)

        rotated = list(log_dir.glob("cleaner-*.log"))
        assert len(rotated) == 1
        assert expected_ts in rotated[0].name
