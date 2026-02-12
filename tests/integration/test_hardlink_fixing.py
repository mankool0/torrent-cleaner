"""Test hardlink fixing functionality."""

import pytest
import os
import time
from pathlib import Path
from unittest.mock import patch
from src.hardlink_fixer import HardlinkFixer
from src.file_analyzer import FileAnalyzer


def test_single_file_successful_fix(qb_client, torrent_creator, test_dirs):
    """Test successfully fixing single orphaned file by creating hardlink."""
    media_file = test_dirs['media'] / 'movie.mkv'
    media_content = b'M' * (10 * 1024 * 1024)
    media_file.write_bytes(media_content)

    torrent_data = torrent_creator('movie.mkv', content=media_content)

    qb_client.torrents_add(
        torrent_files=str(torrent_data['torrent']),
        save_path='/data/torrents',
        is_paused=True
    )
    time.sleep(2)

    stat_before = os.stat(torrent_data['file'])
    assert stat_before.st_nlink == 1, "File should be orphan before fix"

    hardlink_fixer = HardlinkFixer()
    result = hardlink_fixer.fix_hardlink(
        str(torrent_data['file']),
        str(media_file),
        dry_run=False
    )

    assert result.success, f"Fix should succeed: {result.message}"
    assert result.action == 'fixed'

    stat_after = os.stat(torrent_data['file'])
    assert stat_after.st_nlink == 2, "File should have hardlink count of 2 after fix"

    media_stat = os.stat(media_file)
    assert stat_after.st_ino == media_stat.st_ino, "Files should have same inode"


def test_fix_with_rollback(qb_client, torrent_creator, test_dirs):
    """Test rollback when hardlink creation fails."""
    media_file = test_dirs['media'] / 'movie.mkv'
    media_file.write_bytes(b'M' * (10 * 1024 * 1024))

    original_content = b'T' * (10 * 1024 * 1024)
    torrent_data = torrent_creator('movie.mkv', content=original_content)

    qb_client.torrents_add(
        torrent_files=str(torrent_data['torrent']),
        save_path='/data/torrents',
        is_paused=True
    )
    time.sleep(2)

    hardlink_fixer = HardlinkFixer()

    with patch('os.link', side_effect=OSError("Simulated hardlink failure")):
        result = hardlink_fixer.fix_hardlink(
            str(torrent_data['file']),
            str(media_file),
            dry_run=False
        )

    assert not result.success, "Fix should fail"
    assert result.action == 'link_failed_restored'
    assert "Simulated hardlink failure" in result.message

    assert torrent_data['file'].exists(), "Original file should be restored"
    assert torrent_data['file'].read_bytes() == original_content, "Content should be unchanged"

    backup_path = torrent_data['file'].with_suffix(torrent_data['file'].suffix + '.bak')
    assert not backup_path.exists(), "Backup should be cleaned up"


def test_size_mismatch_no_hardlink(qb_client, torrent_creator, test_dirs):
    """Test that hardlink is NOT created when file sizes don't match."""
    media_file = test_dirs['media'] / 'movie.mkv'
    media_file.write_bytes(b'M' * (10 * 1024 * 1024))

    torrent_data = torrent_creator('movie.mkv', size_mb=5)

    qb_client.torrents_add(
        torrent_files=str(torrent_data['torrent']),
        save_path='/data/torrents',
        is_paused=True
    )
    time.sleep(2)

    media_size = os.stat(media_file).st_size
    torrent_size = os.stat(torrent_data['file']).st_size
    assert media_size != torrent_size, "Files should have different sizes"

    hardlink_fixer = HardlinkFixer()
    result = hardlink_fixer.fix_hardlink(
        str(torrent_data['file']),
        str(media_file),
        dry_run=False
    )

    assert not result.success, "Fix should fail due to size mismatch"
    assert result.action == 'size_mismatch'

    stat_info = os.stat(torrent_data['file'])
    assert stat_info.st_nlink == 1, "File should remain orphan (size mismatch)"


def test_multi_file_main_media_fixed(qb_client, torrent_creator, test_dirs):
    """Test multi-file torrent where main media file gets fixed."""
    torrent_data = torrent_creator('movie', multi_file=True)

    media_file = test_dirs['media'] / 'movie.mkv'
    media_file.write_bytes(torrent_data['files']['main'].read_bytes())

    qb_client.torrents_add(
        torrent_files=str(torrent_data['torrent']),
        save_path='/data/torrents',
        is_paused=True
    )
    time.sleep(2)

    for file_path in torrent_data['files'].values():
        assert os.stat(file_path).st_nlink == 1

    hardlink_fixer = HardlinkFixer()
    file_analyzer = FileAnalyzer()

    size_index = file_analyzer.build_size_index(test_dirs['media'])

    orphaned_files = [str(torrent_data['files']['main'])]

    results = hardlink_fixer.fix_orphaned_files(
        orphaned_files,
        size_index,
        file_analyzer,
        dry_run=False
    )

    assert results.fixed == 1, "Main file should be fixed"
    assert results.media_files_fixed == 1, "Media file should be counted"

    main_stat = os.stat(torrent_data['files']['main'])
    assert main_stat.st_nlink == 2, "Main file should be hardlinked"

    for file_name in ['subtitle', 'nfo', 'sample']:
        stat_info = os.stat(torrent_data['files'][file_name])
        assert stat_info.st_nlink == 1, f"{file_name} should remain orphan"


def test_multi_file_only_subtitle_fixed(qb_client, torrent_creator, test_dirs):
    """Test multi-file torrent where only subtitle gets fixed (should delete)."""
    torrent_data = torrent_creator('movie2', multi_file=True)

    media_srt = test_dirs['media'] / 'movie2.srt'
    media_srt.write_bytes(torrent_data['files']['subtitle'].read_bytes())

    qb_client.torrents_add(
        torrent_files=str(torrent_data['torrent']),
        save_path='/data/torrents',
        is_paused=True
    )
    time.sleep(2)

    hardlink_fixer = HardlinkFixer()
    file_analyzer = FileAnalyzer()

    size_index = file_analyzer.build_size_index(test_dirs['media'])

    orphaned_files = [str(torrent_data['files']['subtitle'])]

    results = hardlink_fixer.fix_orphaned_files(
        orphaned_files,
        size_index,
        file_analyzer,
        dry_run=False
    )

    assert results.fixed == 1, "Subtitle should be fixed"
    assert results.media_files_fixed == 0, "Subtitle is not a media file"

    srt_stat = os.stat(torrent_data['files']['subtitle'])
    assert srt_stat.st_nlink == 2, "Subtitle should be hardlinked"

    main_stat = os.stat(torrent_data['files']['main'])
    assert main_stat.st_nlink == 1, "Main file should still be orphan"


def test_multi_file_sample_fixed(qb_client, torrent_creator, test_dirs):
    """Test multi-file torrent where sample file gets fixed (should keep)."""
    torrent_data = torrent_creator('movie3', multi_file=True)

    media_sample = test_dirs['media'] / 'sample.mkv'
    media_sample.write_bytes(torrent_data['files']['sample'].read_bytes())

    qb_client.torrents_add(
        torrent_files=str(torrent_data['torrent']),
        save_path='/data/torrents',
        is_paused=True
    )
    time.sleep(2)

    hardlink_fixer = HardlinkFixer()
    file_analyzer = FileAnalyzer()

    size_index = file_analyzer.build_size_index(test_dirs['media'])

    orphaned_files = [str(torrent_data['files']['sample'])]

    results = hardlink_fixer.fix_orphaned_files(
        orphaned_files,
        size_index,
        file_analyzer,
        dry_run=False
    )

    assert results.fixed == 1, "Sample should be fixed"
    assert results.media_files_fixed == 1, "Sample.mkv is a media file"

    sample_stat = os.stat(torrent_data['files']['sample'])
    assert sample_stat.st_nlink == 2, "Sample should be hardlinked"

    main_stat = os.stat(torrent_data['files']['main'])
    assert main_stat.st_nlink == 1, "Main file should still be orphan"
