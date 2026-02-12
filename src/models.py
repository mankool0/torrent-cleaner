"""Data models for torrent cleaner application."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, ValuesView


@dataclass
class SizeIndex:
    """Index mapping file sizes to lists of file paths."""
    _entries: Dict[int, List[str]] = field(default_factory=dict)

    def add(self, size: int, path: str) -> None:
        self._entries.setdefault(size, []).append(path)

    def get_candidates(self, size: int) -> List[str]:
        return self._entries.get(size, [])

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, size: int) -> bool:
        return size in self._entries

    def __getitem__(self, size: int) -> List[str]:
        return self._entries[size]

    def __bool__(self) -> bool:
        return bool(self._entries)

    @property
    def file_count(self) -> int:
        return sum(len(paths) for paths in self._entries.values())

    def values(self) -> ValuesView:
        return self._entries.values()


@dataclass
class FileCacheStats:
    """Statistics about the persistent file hash cache."""
    total_entries: int
    db_size_bytes: int


@dataclass
class CacheStats:
    """Statistics from file hash cache usage."""
    hits: int
    misses: int
    hit_rate: float


@dataclass
class TorrentStats:
    """Statistics about a torrent's seeding status."""
    ratio: float
    seeding_time_seconds: Optional[int]
    age: Optional[str]  # Human-readable format like "5d 3h"
    age_days: Optional[int]


@dataclass
class DeletionDecision:
    """Decision about whether to delete a torrent."""
    should_delete: bool
    reasons: List[str]
    stats: TorrentStats


@dataclass
class HardlinkResult:
    """Result of attempting to fix a single hardlink."""
    success: bool
    action: str
    message: str


@dataclass
class HardlinkFixResult:
    """Result of fixing a single orphaned file."""
    file: str
    media_file: str
    result: HardlinkResult


@dataclass
class HardlinkBatchResult:
    """Result of fixing multiple orphaned files."""
    attempted: int
    fixed: int
    failed: int
    media_files_fixed: int
    results: List[HardlinkFixResult]


@dataclass
class OrphanDetectionStats:
    """Statistics from orphaned file detection."""
    total: int
    orphaned: int
    linked: int
    errors: int


@dataclass
class OrphanDetectionResult:
    """Result of detecting orphaned files."""
    orphaned: List[str]
    linked: List[str]
    stats: OrphanDetectionStats


@dataclass
class WorkflowStats:
    """Statistics from the torrent cleaning workflow."""
    torrents_processed: int = 0
    torrents_deleted: int = 0
    torrents_kept: int = 0
    torrents_kept_hardlinks_fixed: int = 0
    torrents_kept_criteria_not_met: int = 0
    hardlinks_attempted: int = 0
    hardlinks_fixed: int = 0
    hardlinks_failed: int = 0
    orphaned_files_found: int = 0
    deletion_reasons: dict = None
    deleted_torrents: List[str] = None

    def __post_init__(self):
        """Initialize mutable default values."""
        if self.deletion_reasons is None:
            self.deletion_reasons = {}
        if self.deleted_torrents is None:
            self.deleted_torrents = []
