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
    def __init__(self, torrent_hash, name, save_path, seeding_time, ratio, amount_left=0):
        self.hash = torrent_hash
        self.name = name
        self.save_path = save_path
        self.seeding_time = seeding_time
        self.ratio = ratio
        self.amount_left = amount_left


class FakeTracker:
    def __init__(self, url, status, msg=""):
        self.url = url
        self.status = status
        self.msg = msg


class FakeQbtClient:
    """Minimal in-memory stand-in for QBittorrentClient."""

    def __init__(self, torrents, files_by_hash, trackers_by_hash=None):
        self.torrents = list(torrents)
        self.files_by_hash = files_by_hash
        self.trackers_by_hash = trackers_by_hash or {}
        self.deleted = []
        self.delete_files_by_hash = {}
        self.paused = []
        self.resumed = []

    def torrents_info(self, **kwargs):
        return [t for t in self.torrents if t.hash not in self.deleted]

    def torrents_files(self, torrent_hash):
        return self.files_by_hash[torrent_hash]

    def torrents_trackers(self, torrent_hash):
        return self.trackers_by_hash.get(torrent_hash, [])

    def delete_torrent(self, torrent_hash, delete_files=True, dry_run=True):
        self.delete_files_by_hash[torrent_hash] = delete_files
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


DEAD_TRACKERS = [FakeTracker("https://t/announce", 5, "unregistered torrent")]
WORKING_TRACKERS = [FakeTracker("https://t/announce", 2)]
DEAD_ENV = {'DELETE_DEAD_TRACKERS': 'true', 'DEAD_TRACKER_MESSAGES': 'unregistered torrent'}


def test_dead_torrent_shared_files_are_kept(make_config, tmp_path):
    """A dead torrent sharing its file path with a surviving torrent (same-path
    cross-seed) must lose its entry but keep its files."""
    config = make_config(**DEAD_ENV)
    save_dir = tmp_path / 'torrents'
    save_dir.mkdir()
    shared_file = save_dir / 'movie.mkv'
    shared_file.write_bytes(b'X' * 1024)

    dead = FakeTorrent('hdead', 'dead-twin', str(save_dir), seeding_time=1000, ratio=0.1)
    survivor = FakeTorrent('halive', 'live-twin', str(save_dir), seeding_time=1000, ratio=0.1)
    client = FakeQbtClient(
        [dead, survivor],
        {'hdead': [FakeTorrentFile('movie.mkv')], 'halive': [FakeTorrentFile('movie.mkv')]},
        trackers_by_hash={'hdead': DEAD_TRACKERS, 'halive': WORKING_TRACKERS},
    )

    stats = run(config, client)

    assert client.deleted == ['hdead']
    assert client.delete_files_by_hash['hdead'] is False, "Shared files must not be deleted"
    assert shared_file.exists()
    assert stats.torrents_deleted_dead_tracker == 1
    assert stats.space_freed_dead_tracker_bytes == 0


def _make_partial_overlap(tmp_path):
    """Dead pack (movie + sample) where a survivor shares only the movie."""
    save_dir = tmp_path / 'torrents'
    pack = save_dir / 'Pack'
    sample_dir = pack / 'Sample'
    sample_dir.mkdir(parents=True)
    movie = pack / 'movie.mkv'
    movie.write_bytes(b'X' * 1024)
    sample = sample_dir / 'sample.mkv'
    sample.write_bytes(b'S' * 512)

    dead = FakeTorrent('hdead', 'dead-pack', str(save_dir), seeding_time=1000, ratio=0.1)
    survivor = FakeTorrent('halive', 'live-single', str(save_dir), seeding_time=1000, ratio=0.1)
    client = FakeQbtClient(
        [dead, survivor],
        {
            'hdead': [FakeTorrentFile('Pack/movie.mkv'), FakeTorrentFile('Pack/Sample/sample.mkv')],
            'halive': [FakeTorrentFile('Pack/movie.mkv')],
        },
        trackers_by_hash={'hdead': DEAD_TRACKERS, 'halive': WORKING_TRACKERS},
    )
    return client, movie, sample, sample_dir, pack


def test_dead_torrent_partial_overlap_removes_unshared_files(make_config, tmp_path):
    """When only some files are shared, the entry goes, shared files stay, and
    unshared leftovers (e.g. a sample) are unlinked with empty dirs pruned."""
    config = make_config(**DEAD_ENV)
    client, movie, sample, sample_dir, pack = _make_partial_overlap(tmp_path)

    stats = run(config, client)

    assert client.deleted == ['hdead']
    assert client.delete_files_by_hash['hdead'] is False
    assert movie.exists(), "Shared file must survive"
    assert not sample.exists(), "Unshared file must be removed"
    assert not sample_dir.exists(), "Emptied directory must be pruned"
    assert pack.exists(), "Directory holding shared content must survive"
    assert stats.space_freed_dead_tracker_bytes == 512


def test_dead_torrent_partial_overlap_dry_run_keeps_disk_untouched(make_config, tmp_path):
    """Dry run reports the unshared removals without touching disk."""
    config = make_config(**DEAD_ENV)
    config.dry_run = True
    client, movie, sample, sample_dir, pack = _make_partial_overlap(tmp_path)

    stats = run(config, client)

    assert client.delete_files_by_hash['hdead'] is False
    assert movie.exists() and sample.exists() and sample_dir.exists()
    assert stats.space_freed_dead_tracker_bytes == 512  # still estimated


def test_dead_torrent_unshared_files_are_deleted(make_config, tmp_path):
    """A dead torrent whose files nothing else references is deleted with files."""
    config = make_config(**DEAD_ENV)
    save_dir = tmp_path / 'torrents'
    save_dir.mkdir()
    (save_dir / 'dead.mkv').write_bytes(b'X' * 1024)
    (save_dir / 'other.mkv').write_bytes(b'Y' * 2048)

    dead = FakeTorrent('hdead', 'dead-only', str(save_dir), seeding_time=1000, ratio=0.1)
    survivor = FakeTorrent('halive', 'unrelated', str(save_dir), seeding_time=1000, ratio=0.1)
    client = FakeQbtClient(
        [dead, survivor],
        {'hdead': [FakeTorrentFile('dead.mkv')], 'halive': [FakeTorrentFile('other.mkv')]},
        trackers_by_hash={'hdead': DEAD_TRACKERS, 'halive': WORKING_TRACKERS},
    )

    stats = run(config, client)

    assert client.deleted == ['hdead']
    assert client.delete_files_by_hash['hdead'] is True
    assert stats.space_freed_dead_tracker_bytes == 1024


def test_dead_cross_seed_pair_still_frees_files(make_config, tmp_path):
    """Two dead torrents sharing a path (both cross-seed twins dead) don't
    count as survivors for each other — files are freed."""
    config = make_config(**DEAD_ENV)
    save_dir = tmp_path / 'torrents'
    save_dir.mkdir()
    (save_dir / 'movie.mkv').write_bytes(b'X' * 1024)

    dead_a = FakeTorrent('ha', 'twin-a', str(save_dir), seeding_time=1000, ratio=0.1)
    dead_b = FakeTorrent('hb', 'twin-b', str(save_dir), seeding_time=1000, ratio=0.1)
    client = FakeQbtClient(
        [dead_a, dead_b],
        {'ha': [FakeTorrentFile('movie.mkv')], 'hb': [FakeTorrentFile('movie.mkv')]},
        trackers_by_hash={'ha': DEAD_TRACKERS, 'hb': DEAD_TRACKERS},
    )

    stats = run(config, client)

    assert sorted(client.deleted) == ['ha', 'hb']
    assert client.delete_files_by_hash['ha'] is True
    assert stats.torrents_deleted_dead_tracker == 2


def test_dead_torrent_missing_files_entry_removed(make_config, tmp_path):
    """A dead torrent whose files aren't visible loses its entry but no files
    (entry removal is always data-safe; the old behavior kept it forever)."""
    config = make_config(**DEAD_ENV)
    save_dir = tmp_path / 'torrents'
    save_dir.mkdir()

    dead = FakeTorrent('hdead', 'dead-missing', str(save_dir), seeding_time=1000, ratio=0.1)
    client = FakeQbtClient(
        [dead],
        {'hdead': [FakeTorrentFile('gone.mkv')]},
        trackers_by_hash={'hdead': DEAD_TRACKERS},
    )

    stats = run(config, client)

    assert client.deleted == ['hdead']
    assert client.delete_files_by_hash['hdead'] is False
    assert stats.torrents_deleted_dead_tracker == 1
    assert stats.space_freed_dead_tracker_bytes == 0


def test_unlistable_survivor_blocks_dead_deletions(make_config, tmp_path):
    """If any surviving torrent's file list can't be fetched, shared files can't
    be ruled out — no dead-tracker deletion may happen this run."""
    config = make_config(**DEAD_ENV)
    save_dir = tmp_path / 'torrents'
    save_dir.mkdir()
    (save_dir / 'movie.mkv').write_bytes(b'X' * 1024)

    dead = FakeTorrent('hdead', 'dead', str(save_dir), seeding_time=1000, ratio=0.1)
    survivor = FakeTorrent('halive', 'unlistable', str(save_dir), seeding_time=1000, ratio=0.1)
    client = FakeQbtClient(
        [dead, survivor],
        {'hdead': [FakeTorrentFile('movie.mkv')]},  # no entry for halive -> KeyError
        trackers_by_hash={'hdead': DEAD_TRACKERS, 'halive': WORKING_TRACKERS},
    )

    stats = run(config, client)

    assert client.deleted == []
    assert stats.torrents_deleted_dead_tracker == 0


def test_redownloading_torrent_is_kept(make_config):
    """A torrent that completed once but is downloading again (recheck lost
    pieces, missing files) keeps its old seeding_time — amount_left must
    still mark it incomplete."""
    config = make_config()
    cleaner = TorrentCleaner(config, qbt_client=None)
    redownloading = FakeTorrent('h1', 'redownloading', '/x',
                                seeding_time=OLD_ENOUGH, ratio=5.0, amount_left=512)

    decision = cleaner.should_delete_torrent(redownloading)

    assert decision.should_delete is False
    assert 'not completed' in decision.reasons[0].lower()


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
