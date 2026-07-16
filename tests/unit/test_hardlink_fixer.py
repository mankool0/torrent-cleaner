"""Unit tests for HardlinkFixer edge cases."""

import errno
import os
from unittest.mock import patch

import pytest

from src.hardlink_fixer import HardlinkFixer
from src.models import HardlinkAction


@pytest.fixture
def fixer():
    return HardlinkFixer()


def test_fix_hardlink_success(fixer, tmp_path):
    orphan = tmp_path / 'orphan.mkv'
    media = tmp_path / 'media.mkv'
    orphan.write_bytes(b'Same content')
    media.write_bytes(b'Same content')

    result = fixer.fix_hardlink(str(orphan), str(media), dry_run=False)

    assert result.success
    assert result.action == HardlinkAction.FIXED
    assert os.stat(orphan).st_ino == os.stat(media).st_ino


def test_leftover_backup_blocks_fix(fixer, tmp_path):
    """A leftover .bak from an interrupted run must fail the fix, not be clobbered."""
    orphan = tmp_path / 'orphan.mkv'
    media = tmp_path / 'media.mkv'
    backup = tmp_path / 'orphan.mkv.bak'
    orphan.write_bytes(b'Same content')
    media.write_bytes(b'Same content')
    backup.write_bytes(b'Leftover from interrupted run')

    result = fixer.fix_hardlink(str(orphan), str(media), dry_run=False)

    assert not result.success
    assert result.action == HardlinkAction.BACKUP_FAILED
    assert result.action.is_actionable_failure
    assert orphan.read_bytes() == b'Same content', "Original must be untouched"
    assert backup.read_bytes() == b'Leftover from interrupted run', "Backup must not be clobbered"


def test_byte_verify_rejects_different_content(fixer, tmp_path):
    """Same size but different bytes must fail with CONTENT_MISMATCH when verifying."""
    orphan = tmp_path / 'orphan.mkv'
    media = tmp_path / 'media.mkv'
    orphan.write_bytes(b'Content AAAA')
    media.write_bytes(b'Content BBBB')

    result = fixer.fix_hardlink(str(orphan), str(media), dry_run=False, byte_verify=True)

    assert not result.success
    assert result.action == HardlinkAction.CONTENT_MISMATCH
    assert result.action.is_actionable_failure
    assert orphan.read_bytes() == b'Content AAAA', "Original must be untouched"
    assert os.stat(orphan).st_nlink == 1


def test_byte_verify_accepts_identical_content(fixer, tmp_path):
    orphan = tmp_path / 'orphan.mkv'
    media = tmp_path / 'media.mkv'
    orphan.write_bytes(b'Same content')
    media.write_bytes(b'Same content')

    result = fixer.fix_hardlink(str(orphan), str(media), dry_run=False, byte_verify=True)

    assert result.success
    assert result.action == HardlinkAction.FIXED
    assert os.stat(orphan).st_ino == os.stat(media).st_ino


def test_cross_mount_failure_explains_itself(fixer, tmp_path):
    """EXDEV (hardlink across bind mounts) must produce an actionable hint."""
    orphan = tmp_path / 'orphan.mkv'
    media = tmp_path / 'media.mkv'
    orphan.write_bytes(b'Same content')
    media.write_bytes(b'Same content')

    with patch('os.link', side_effect=OSError(errno.EXDEV, 'Invalid cross-device link')):
        result = fixer.fix_hardlink(str(orphan), str(media), dry_run=False)

    assert not result.success
    assert result.action == HardlinkAction.LINK_FAILED_RESTORED
    assert 'single mount' in result.message, "EXDEV message should point at the mount layout"
    assert orphan.read_bytes() == b'Same content', "Original must be restored"


def test_dry_run_makes_no_changes(fixer, tmp_path):
    orphan = tmp_path / 'orphan.mkv'
    media = tmp_path / 'media.mkv'
    orphan.write_bytes(b'Same content')
    media.write_bytes(b'Same content')

    result = fixer.fix_hardlink(str(orphan), str(media), dry_run=True)

    assert result.success
    assert result.action == HardlinkAction.DRY_RUN
    assert os.stat(orphan).st_nlink == 1
