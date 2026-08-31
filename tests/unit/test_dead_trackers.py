"""Unit tests for dead-tracker detection in src.main."""

from src.main import is_dead_tracker_torrent


DEAD_MESSAGES = [
    "002: Invalid InfoHash, Torrent not found",
    "This torrent does not exist",
    "unregistered torrent",
]


class FakeTracker:
    def __init__(self, url, status, msg=""):
        self.url = url
        self.status = status
        self.msg = msg


class FakeTorrent:
    hash = "h1"
    name = "torrent"


class FakeQbtClient:
    def __init__(self, trackers):
        self.trackers = trackers

    def torrents_trackers(self, torrent_hash):
        return self.trackers


def is_dead(trackers, messages=DEAD_MESSAGES):
    return is_dead_tracker_torrent(FakeQbtClient(trackers), FakeTorrent(), messages)


def test_status_4_with_dead_message_matches():
    trackers = [FakeTracker("https://a/announce", 4, "unregistered torrent")]
    assert is_dead(trackers) is True


def test_status_5_with_dead_message_matches():
    """qBittorrent 5.1 reports tracker-rejected announces as status 5, not 4."""
    trackers = [FakeTracker("https://a/announce", 5, "002: Invalid InfoHash, Torrent not found")]
    assert is_dead(trackers) is True


def test_mixed_status_4_and_5_all_dead_matches():
    trackers = [
        FakeTracker("https://a/announce", 5, "unregistered torrent"),
        FakeTracker("https://b/announce", 4, "This torrent does not exist"),
    ]
    assert is_dead(trackers) is True


def test_message_match_is_case_insensitive():
    trackers = [FakeTracker("https://a/announce", 5, "Unregistered Torrent")]
    assert is_dead(trackers) is True


def test_unknown_message_does_not_match():
    trackers = [FakeTracker("https://a/announce", 5, "temporarily unavailable")]
    assert is_dead(trackers) is False


def test_working_tracker_blocks_match():
    trackers = [
        FakeTracker("https://a/announce", 5, "unregistered torrent"),
        FakeTracker("https://b/announce", 2),
    ]
    assert is_dead(trackers) is False


def test_not_contacted_tracker_blocks_match():
    """Right after a qBittorrent restart trackers are status 1 with no message."""
    trackers = [FakeTracker("https://a/announce", 1)]
    assert is_dead(trackers) is False


def test_pseudo_trackers_are_ignored():
    trackers = [
        FakeTracker("** [DHT] **", 2),
        FakeTracker("** [PeX] **", 2),
        FakeTracker("https://a/announce", 5, "unregistered torrent"),
    ]
    assert is_dead(trackers) is True


def test_only_pseudo_trackers_never_matches():
    trackers = [FakeTracker("** [DHT] **", 2), FakeTracker("** [PeX] **", 2)]
    assert is_dead(trackers) is False


def test_no_trackers_never_matches():
    assert is_dead([]) is False


def test_empty_message_list_never_matches():
    trackers = [FakeTracker("https://a/announce", 5, "unregistered torrent")]
    assert is_dead(trackers, messages=[]) is False


def test_tracker_fetch_failure_is_kept():
    class FailingClient:
        def torrents_trackers(self, torrent_hash):
            raise RuntimeError("api down")

    assert is_dead_tracker_torrent(FailingClient(), FakeTorrent(), DEAD_MESSAGES) is False
