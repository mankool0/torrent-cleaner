"""Test deletion criteria based on seeding time and ratio."""

import pytest
from tests.helpers import get_torrent_by_hash, assert_torrent_metadata
from src.config import Config
from src.qbittorrent_client import QBittorrentClient
from src.torrent_cleaner import TorrentCleaner


@pytest.fixture
def torrent_cleaner(test_dirs):
    """Create TorrentCleaner instance for deletion criteria tests."""
    import os
    os.environ['QBITTORRENT_HOST'] = 'localhost'
    os.environ['QBITTORRENT_USERNAME'] = 'admin'
    os.environ['QBITTORRENT_PASSWORD'] = 'adminadmin'
    os.environ['TORRENT_DIR'] = str(test_dirs['torrents'])
    os.environ['MEDIA_LIBRARY_DIR'] = str(test_dirs['media'])
    os.environ['DATA_DIR'] = str(test_dirs['root'] / 'data')

    config = Config()
    config.min_seeding_duration = '30d'
    config.min_ratio = 2.0
    config.dry_run = False

    client = QBittorrentClient(
        config.qbt_host,
        config.qbt_port,
        config.qbt_username,
        config.qbt_password
    )
    return TorrentCleaner(config, client)


def test_young_torrent_low_ratio_keep(qb_client, preseeded_torrent, torrent_cleaner):
    """Test: seeding < 30d, ratio < 2.0 -> Keep."""
    torrent_data = preseeded_torrent('young_low.txt', content=b'Test', seeding_days=10, ratio=1.5)
    torrent = get_torrent_by_hash(qb_client, torrent_data['hash'], "after pre-seeding")

    assert_torrent_metadata(torrent, seeding_days=10, ratio=1.5)

    result = torrent_cleaner.should_delete_torrent(torrent)
    assert result.should_delete == False, "Young torrent with low ratio should be kept"
    assert any('Age' in reason or 'Ratio' in reason for reason in result.reasons)


def test_young_torrent_high_ratio_keep(qb_client, preseeded_torrent, torrent_cleaner):
    """Test: seeding < 30d, ratio >= 2.0 -> Keep (time not met)."""
    torrent_data = preseeded_torrent('young_high.txt', content=b'Test', seeding_days=15, ratio=3.0)
    torrent = get_torrent_by_hash(qb_client, torrent_data['hash'], "after pre-seeding")

    assert_torrent_metadata(torrent, seeding_days=15, ratio=3.0)

    result = torrent_cleaner.should_delete_torrent(torrent)
    assert result.should_delete == False, "Young torrent should be kept regardless of ratio"
    assert any('Age' in reason for reason in result.reasons)


def test_old_torrent_low_ratio_keep(qb_client, preseeded_torrent, torrent_cleaner):
    """Test: seeding >= 30d, ratio < 2.0 -> Keep (ratio not met)."""
    torrent_data = preseeded_torrent('old_low.txt', content=b'Test', seeding_days=35, ratio=1.5)
    torrent = get_torrent_by_hash(qb_client, torrent_data['hash'], "after pre-seeding")

    assert_torrent_metadata(torrent, seeding_days=35, ratio=1.5)

    result = torrent_cleaner.should_delete_torrent(torrent)
    assert result.should_delete == False, "Old torrent with low ratio should be kept"
    assert any('Ratio' in reason for reason in result.reasons)


def test_old_torrent_high_ratio_delete(qb_client, preseeded_torrent, torrent_cleaner):
    """Test: seeding >= 30d, ratio >= 2.0 -> Delete (both met)."""
    torrent_data = preseeded_torrent('old_high.txt', content=b'Test', seeding_days=35, ratio=2.5)
    torrent = get_torrent_by_hash(qb_client, torrent_data['hash'], "after pre-seeding")

    assert_torrent_metadata(torrent, seeding_days=35, ratio=2.5)

    result = torrent_cleaner.should_delete_torrent(torrent)
    assert result.should_delete == True, "Old torrent with high ratio should be deleted"


def test_exact_threshold_values(qb_client, preseeded_torrent, torrent_cleaner):
    """Test behavior at exact threshold values (30d, 2.0 ratio)."""
    torrent_data = preseeded_torrent('exact_threshold.txt', content=b'Test', seeding_days=30, ratio=2.0)
    torrent = get_torrent_by_hash(qb_client, torrent_data['hash'], "after pre-seeding")

    assert_torrent_metadata(torrent, seeding_days=30, ratio=2.0)

    result = torrent_cleaner.should_delete_torrent(torrent)
    assert result.should_delete == True, "Torrent at exact thresholds should be deleted"


def test_very_old_torrent_very_high_ratio(qb_client, preseeded_torrent, torrent_cleaner):
    """Test with extreme values (100 days, 10.0 ratio)."""
    torrent_data = preseeded_torrent('extreme.txt', content=b'Test', seeding_days=100, ratio=10.0)
    torrent = get_torrent_by_hash(qb_client, torrent_data['hash'], "after pre-seeding")

    assert_torrent_metadata(torrent, seeding_days=100, ratio=10.0)

    result = torrent_cleaner.should_delete_torrent(torrent)
    assert result.should_delete == True, "Very old torrent with very high ratio should be deleted"


def test_incomplete_torrent_keep(qb_client, incomplete_torrent, torrent_cleaner):
    """Test that incomplete torrents (seeding_time = 0) are always kept."""
    # Create incomplete torrent (0% downloaded, paused, no data file)
    torrent_data = incomplete_torrent('incomplete.txt', size_mb=1)
    torrent = get_torrent_by_hash(qb_client, torrent_data['hash'], "after adding incomplete torrent")

    assert torrent.seeding_time == 0, "Torrent should have seeding_time = 0"

    result = torrent_cleaner.should_delete_torrent(torrent)
    assert result.should_delete == False, "Incomplete torrent should be kept"
    assert 'not completed yet' in result.reasons[0].lower(), "Reason should mention torrent not completed"
    assert result.stats.seeding_time_seconds is None, "Stats should show None for seeding time"
    assert result.stats.age is None, "Stats should show None for age"
    assert result.stats.age_days is None, "Stats should show None for age_days"
