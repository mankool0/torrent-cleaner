"""Test orphan file detection logic."""

import pytest
import os
import time
from pathlib import Path
from src.file_analyzer import FileAnalyzer


def test_single_orphaned_file(qb_client, torrent_creator, test_dirs):
    """Test detection of single orphaned file (hardlink count = 1)."""
    torrent_data = torrent_creator('orphan.mkv', size_mb=10)

    qb_client.torrents_add(
        torrent_files=str(torrent_data['torrent']),
        save_path=str(torrent_data['file'].parent),
        is_paused=True
    )
    time.sleep(2)

    torrents = qb_client.torrents_info()
    assert len(torrents) == 1
    torrent = torrents[0]

    files = qb_client.torrents_files(torrent_hash=torrent.hash)
    assert len(files) == 1

    file_analyzer = FileAnalyzer()
    file_paths = [str(torrent_data['file'])]
    analysis = file_analyzer.detect_orphaned_files(file_paths)

    assert len(analysis.orphaned) == 1, "Should detect 1 orphaned file"
    assert len(analysis.linked) == 0, "Should detect 0 linked files"
    assert analysis.orphaned[0] == str(torrent_data['file'])


def test_single_hardlinked_file(qb_client, torrent_creator, test_dirs):
    """Test detection of hardlinked file (hardlink count > 1)."""
    media_file = test_dirs['media'] / 'movie.mkv'
    media_file.write_bytes(b'M' * (10 * 1024 * 1024))

    torrent_data = torrent_creator('movie.mkv', content=media_file.read_bytes())

    # Setup: Create hardlink (simple os.link for test setup)
    torrent_data['file'].unlink()
    os.link(media_file, torrent_data['file'])

    qb_client.torrents_add(
        torrent_files=str(torrent_data['torrent']),
        save_path=str(torrent_data['file'].parent),
        is_paused=True
    )
    time.sleep(2)

    torrents = qb_client.torrents_info()
    assert len(torrents) == 1

    file_analyzer = FileAnalyzer()
    file_paths = [str(torrent_data['file'])]
    analysis = file_analyzer.detect_orphaned_files(file_paths)

    assert len(analysis.orphaned) == 0, "Should detect 0 orphaned files"
    assert len(analysis.linked) == 1, "Should detect 1 linked file"
    assert analysis.linked[0] == str(torrent_data['file'])


def test_multi_file_all_orphans(qb_client, torrent_creator):
    """Test multi-file torrent where all files are orphans."""
    torrent_data = torrent_creator('all_orphans', multi_file=True)

    qb_client.torrents_add(
        torrent_files=str(torrent_data['torrent']),
        save_path=str(torrent_data['dir'].parent),
        is_paused=True
    )
    time.sleep(2)

    torrents = qb_client.torrents_info()
    assert len(torrents) == 1
    torrent = torrents[0]

    files = qb_client.torrents_files(torrent_hash=torrent.hash)
    assert len(files) == 4

    file_analyzer = FileAnalyzer()
    file_paths = [str(fp) for fp in torrent_data['files'].values()]
    analysis = file_analyzer.detect_orphaned_files(file_paths)

    assert len(analysis.orphaned) == 4, "Should detect all 4 files as orphaned"
    assert len(analysis.linked) == 0, "Should detect 0 linked files"


def test_multi_file_mixed_orphans(qb_client, torrent_creator, test_dirs):
    """Test multi-file torrent with mixed orphan/hardlinked files."""
    torrent_data = torrent_creator('mixed', multi_file=True)

    media_file = test_dirs['media'] / 'mixed.mkv'
    media_file.write_bytes(torrent_data['files']['main'].read_bytes())

    # Setup: Create hardlink (simple os.link for test setup)
    torrent_data['files']['main'].unlink()
    os.link(media_file, torrent_data['files']['main'])

    qb_client.torrents_add(
        torrent_files=str(torrent_data['torrent']),
        save_path=str(torrent_data['dir'].parent),
        is_paused=True
    )
    time.sleep(2)

    file_analyzer = FileAnalyzer()
    file_paths = [str(fp) for fp in torrent_data['files'].values()]
    analysis = file_analyzer.detect_orphaned_files(file_paths)

    assert len(analysis.orphaned) == 3, "Should detect 3 orphaned files (subtitle, nfo, sample)"
    assert len(analysis.linked) == 1, "Should detect 1 linked file (main)"
    assert str(torrent_data['files']['main']) in analysis.linked


def test_verify_file_extensions(qb_client, torrent_creator):
    """Test that we can identify media vs non-media files by extension."""
    # Create multi-file torrent
    torrent_data = torrent_creator('extensions_test', multi_file=True)

    # Add to qBittorrent
    qb_client.torrents_add(
        torrent_files=str(torrent_data['torrent']),
        save_path=str(torrent_data['dir'].parent),
        is_paused=True
    )
    time.sleep(2)

    # Get torrent
    torrents = qb_client.torrents_info()
    assert len(torrents) == 1
    torrent = torrents[0]

    # Get files
    files = qb_client.torrents_files(torrent_hash=torrent.hash)

    # Categorize files
    media_files = []
    non_media_files = []

    media_extensions = {'.mkv', '.mp4', '.avi', '.mov', '.m4v'}

    for f in files:
        file_ext = Path(f.name).suffix.lower()
        if file_ext in media_extensions:
            media_files.append(f.name)
        else:
            non_media_files.append(f.name)

    assert len(media_files) >= 2, "Should have at least 2 media files (main + sample)"
    assert len(non_media_files) >= 2, "Should have at least 2 non-media files (srt + nfo)"

    assert any('extensions_test.mkv' in name for name in media_files)

    assert any('extensions_test.srt' in name for name in non_media_files)
    assert any('extensions_test.nfo' in name for name in non_media_files)
