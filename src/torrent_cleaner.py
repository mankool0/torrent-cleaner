"""Torrent deletion logic with age and ratio filtering."""

from datetime import timedelta
import logging
import qbittorrentapi

from src.config import Config
from src.qbittorrent_client import QBittorrentClient
from src.models import DeletionDecision, TorrentStats


class TorrentCleaner:
    """Handle torrent deletion with age and ratio criteria."""

    def __init__(self, config: Config, qbt_client: QBittorrentClient):
        """
        Initialize torrent cleaner.

        Args:
            config: Application configuration
            qbt_client: qBittorrent client instance
        """
        self.config = config
        self.qbt_client = qbt_client
        self.logger = logging.getLogger(__name__)

    def should_delete_torrent(self, torrent: qbittorrentapi.TorrentDictionary,
                              override_seeding_time: int = None,
                              override_ratio: float = None) -> DeletionDecision:
        """
        Check if torrent meets deletion criteria.

        Both criteria must be met (AND logic):
        - Age >= min_seeding_duration
        - Ratio >= min_ratio

        Args:
            torrent: Torrent dictionary from qBittorrent
            override_seeding_time: Optional seeding time in seconds (for aggregated stats)
            override_ratio: Optional ratio (for aggregated stats)

        Returns:
            DeletionDecision with should_delete flag, reasons, and stats
        """
        reasons = []
        should_delete = True

        ratio = override_ratio if override_ratio is not None else torrent.ratio
        seeding_time = override_seeding_time if override_seeding_time is not None else torrent.seeding_time

        # seeding_time will be 0 if torrent is not completed yet
        if seeding_time == 0:
            return DeletionDecision(
                should_delete=False,
                reasons=['Torrent not completed yet'],
                stats=TorrentStats(
                    ratio=ratio,
                    seeding_time_seconds=None,
                    age=None,
                    age_days=None
                )
            )

        age = timedelta(seconds=seeding_time)
        min_duration = self.config.parse_duration(self.config.min_seeding_duration)
        if age < min_duration:
            should_delete = False
            reasons.append(
                f"Age {self._format_timedelta(age)} < minimum {self.config.min_seeding_duration}"
            )
        else:
            reasons.append(
                f"Age {self._format_timedelta(age)} >= minimum {self.config.min_seeding_duration}"
            )

        if ratio < self.config.min_ratio:
            should_delete = False
            reasons.append(f"Ratio {ratio:.2f} < minimum {self.config.min_ratio}")
        else:
            reasons.append(f"Ratio {ratio:.2f} >= minimum {self.config.min_ratio}")

        return DeletionDecision(
            should_delete=should_delete,
            reasons=reasons,
            stats=TorrentStats(
                ratio=ratio,
                seeding_time_seconds=seeding_time,
                age=self._format_timedelta(age),
                age_days=age.days
            )
        )

    def delete_torrent(self, torrent_hash: str, torrent_name: str, delete_files: bool = True) -> bool:
        """
        Delete torrent from qBittorrent.

        Args:
            torrent_hash: Torrent hash
            torrent_name: Torrent name (for logging)
            delete_files: Whether to delete files from disk

        Returns:
            True if successful
        """
        self.logger.info(
            f"Deleting torrent: {torrent_name} (hash={torrent_hash}, delete_files={delete_files})"
        )

        success = self.qbt_client.delete_torrent(
            torrent_hash=torrent_hash,
            delete_files=delete_files,
            dry_run=self.config.dry_run
        )

        if success:
            if self.config.dry_run:
                self.logger.info(f"[DRY RUN] Would have deleted torrent: {torrent_name}")
            else:
                self.logger.info(f"Successfully deleted torrent: {torrent_name}")
        else:
            self.logger.error(f"Failed to delete torrent: {torrent_name}")

        return success

    @staticmethod
    def _format_timedelta(td: timedelta) -> str:
        """
        Format timedelta for human-readable display.

        Args:
            td: timedelta object

        Returns:
            Formatted string like "30d 5h" or "2d 3h 15m"
        """
        days = td.days
        seconds = td.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0 and days == 0:  # Only show minutes if less than a day
            parts.append(f"{minutes}m")

        return ' '.join(parts) if parts else '0m'
