"""Torrent deletion logic with age and ratio filtering."""

from datetime import timedelta
import logging
import qbittorrentapi

from src.config import Config
from src.models import DeletionDecision, DeletionRule, TorrentStats
from src.qbittorrent_client import QBittorrentClient


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
        Check if torrent meets any deletion rule.

        Rules use OR logic between them: if any rule fully passes, the torrent should be deleted.
        Within each rule, conditions use AND logic: all conditions in the rule must be met.

        Args:
            torrent: Torrent dictionary from qBittorrent
            override_seeding_time: Optional seeding time in seconds (for aggregated stats)
            override_ratio: Optional ratio (for aggregated stats)

        Returns:
            DeletionDecision with should_delete flag, reasons, and stats
        """
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
        reasons = []
        should_delete = False

        for rule in self.config.deletion_rules:
            rule_passed = True
            rule_reasons = []

            if rule.min_duration is not None:
                min_duration = self.config.parse_duration(rule.min_duration)
                if age < min_duration:
                    rule_passed = False
                    rule_reasons.append(f"age {self._format_timedelta(age)} < {rule.min_duration}")
                else:
                    rule_reasons.append(f"age {self._format_timedelta(age)} >= {rule.min_duration}")

            if rule.min_ratio is not None:
                if ratio < rule.min_ratio:
                    rule_passed = False
                    rule_reasons.append(f"ratio {ratio:.2f} < {rule.min_ratio}")
                else:
                    rule_reasons.append(f"ratio {ratio:.2f} >= {rule.min_ratio}")

            rule_label = self._format_rule(rule)
            if rule_passed:
                reasons.append(f"Rule [{rule_label}]: PASS ({', '.join(rule_reasons)})")
                should_delete = True
                break
            else:
                reasons.append(f"Rule [{rule_label}]: FAIL ({', '.join(rule_reasons)})")

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

    @staticmethod
    def _format_rule(rule: DeletionRule) -> str:
        """Format a deletion rule for display in reason strings."""
        parts = []
        if rule.min_duration is not None:
            parts.append(rule.min_duration)
        if rule.min_ratio is not None:
            parts.append(str(rule.min_ratio))
        return ' AND '.join(parts)

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
