"""Unit tests for the workflow safety guards in src.main.

These cover the mass-deletion failure mode: a wrong mount/path config makes
every torrent file look missing, which must never result in deletion.
"""

import pytest

from src.config import Config
from src.file_analyzer import FileAnalyzer
from src.hardlink_fixer import HardlinkFixer
from src.main import run_workflow
from src.models import DeletionRule, SizeIndex
from src.torrent_cleaner import TorrentCleaner


class FakeTorrentFile:
    def __init__(self, name):
        self.name = name


class FakeTorrent:
    def __init__(self, torrent_hash, name, save_path, seeding_time, ratio):
        self.hash = torrent_hash
        self.name = name
        self.save_path = save_path
        self.seeding_time = seeding_time
        self.ratio = ratio


class FakeQbtClient:
    """Minimal in-memory stand-in for QBittorrentClient."""

    def __init__(self, torrents, files_by_hash):
        self.torrents = list(torrents)
        self.files_by_hash = files_by_hash
        self.deleted = []
        self.paused = []
        self.resumed = []

    def torrents_info(self, **kwargs):
        return [t for t in self.torrents if t.hash not in self.deleted]

    def torrents_files(self, torrent_hash):
        return self.files_by_hash[torrent_hash]

    def torrents_trackers(self, torrent_hash):
        return []

    def delete_torrent(self, torrent_hash, delete_files=True, dry_run=True):
        if not dry_run:
            self.deleted.append(torrent_hash)
        return True

    def pause_torrent(self, torrent_hash):
        self.paused.append(torrent_hash)

    def resume_torrent(self, torrent_hash):
        self.resumed.append(torrent_hash)


@pytest.fixture
def make_config(tmp_path, monkeypatch):
    """Build a real Config against temp dirs, defaulting to non-dry-run."""
    def _make(**env):
        monkeypatch.setenv('QBITTORRENT_HOST', 'localhost')
        monkeypatch.setenv('QBITTORRENT_USERNAME', 'admin')
        monkeypatch.setenv('QBITTORRENT_PASSWORD', 'admin')
        monkeypatch.setenv('TORRENT_DIR', str(tmp_path))
        monkeypatch.setenv('MEDIA_LIBRARY_DIR', str(tmp_path))
        monkeypatch.setenv('DATA_DIR', str(tmp_path / 'data'))
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        config = Config()
        config.deletion_rules = [DeletionRule(min_duration='30d', min_ratio=2.0)]
        config.dry_run = False
        return config
    return _make


def run(config, client, size_index=None):
    return run_workflow(
        config,
        client,
        FileAnalyzer(),
        HardlinkFixer(),
        TorrentCleaner(config, client),
        size_index if size_index is not None else SizeIndex(),
    )


OLD_ENOUGH = 100 * 86400  # comfortably past the 30d rule


def test_missing_files_block_deletion(make_config, tmp_path):
    """A torrent whose files can't be stat'd must be kept, not deleted."""
    config = make_config()
    save_dir = tmp_path / 'torrents'
    save_dir.mkdir()
    (save_dir / 'present.mkv').write_bytes(b'X' * 1024)

    torrent = FakeTorrent('h1', 'partially-visible', str(save_dir), OLD_ENOUGH, 5.0)
    client = FakeQbtClient(
        [torrent],
        {'h1': [FakeTorrentFile('present.mkv'), FakeTorrentFile('missing.mkv')]},
    )

    stats = run(config, client)

    assert client.deleted == [], "Torrent with unreadable files must not be deleted"
    assert stats.torrents_deleted == 0
    assert stats.torrents_kept == 1
    assert stats.torrents_kept_file_errors == 1


def test_all_save_paths_invisible_aborts_run(make_config, tmp_path):
    """If no save path exists in the container, the run must abort before deleting."""
    config = make_config()
    torrent = FakeTorrent('h1', 'invisible', str(tmp_path / 'nonexistent'), OLD_ENOUGH, 5.0)
    client = FakeQbtClient([torrent], {'h1': [FakeTorrentFile('movie.mkv')]})

    with pytest.raises(RuntimeError, match="save paths"):
        run(config, client)

    assert client.deleted == []


def test_all_save_paths_invisible_dry_run_continues(make_config, tmp_path):
    """In dry run the preflight only warns; per-torrent guard still keeps everything."""
    config = make_config()
    config.dry_run = True
    torrent = FakeTorrent('h1', 'invisible', str(tmp_path / 'nonexistent'), OLD_ENOUGH, 5.0)
    client = FakeQbtClient([torrent], {'h1': [FakeTorrentFile('movie.mkv')]})

    stats = run(config, client)

    assert stats.torrents_deleted == 0
    assert stats.torrents_kept_file_errors == 1


def test_deletion_cap_limits_deletions(make_config, tmp_path):
    """MAX_DELETIONS_PER_RUN stops deletions once reached."""
    config = make_config(MAX_DELETIONS_PER_RUN='1')
    save_dir = tmp_path / 'torrents'
    save_dir.mkdir()

    torrents = []
    files_by_hash = {}
    for i in range(3):
        name = f'orphan{i}.mkv'
        (save_dir / name).write_bytes(b'X' * (1024 + i))  # distinct sizes
        torrents.append(FakeTorrent(f'h{i}', name, str(save_dir), OLD_ENOUGH, 5.0))
        files_by_hash[f'h{i}'] = [FakeTorrentFile(name)]

    client = FakeQbtClient(torrents, files_by_hash)
    stats = run(config, client)

    assert len(client.deleted) == 1
    assert stats.torrents_deleted == 1
    assert stats.deletions_skipped_cap == 2


def test_deletion_cap_zero_is_unlimited(make_config, tmp_path):
    """MAX_DELETIONS_PER_RUN=0 disables the cap."""
    config = make_config(MAX_DELETIONS_PER_RUN='0')
    save_dir = tmp_path / 'torrents'
    save_dir.mkdir()

    torrents = []
    files_by_hash = {}
    for i in range(3):
        name = f'orphan{i}.mkv'
        (save_dir / name).write_bytes(b'X' * (1024 + i))
        torrents.append(FakeTorrent(f'h{i}', name, str(save_dir), OLD_ENOUGH, 5.0))
        files_by_hash[f'h{i}'] = [FakeTorrentFile(name)]

    client = FakeQbtClient(torrents, files_by_hash)
    stats = run(config, client)

    assert len(client.deleted) == 3
    assert stats.deletions_skipped_cap == 0


def test_group_override_cannot_bypass_incomplete_guard(make_config):
    """An incomplete torrent must be kept even when its group's stats pass."""
    config = make_config()
    cleaner = TorrentCleaner(config, qbt_client=None)
    incomplete = FakeTorrent('h1', 'incomplete', '/x', seeding_time=0, ratio=0.0)

    decision = cleaner.should_delete_torrent(
        incomplete,
        override_seeding_time=OLD_ENOUGH,
        override_ratio=99.0,
    )

    assert decision.should_delete is False
    assert 'not completed' in decision.reasons[0].lower()
