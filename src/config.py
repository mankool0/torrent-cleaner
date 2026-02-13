"""Configuration management for torrent cleaner."""

import os
from pathlib import Path
from datetime import timedelta
from typing import List, Set
from dotenv import load_dotenv
from src.models import DeletionRule


class Config:
    """Application configuration loaded from environment variables."""

    def __init__(self):
        """Load and validate configuration from environment."""
        load_dotenv()

        self.qbt_host = self._get_required('QBITTORRENT_HOST')
        try:
            self.qbt_port = int(os.getenv('QBITTORRENT_PORT', '8080'))
        except ValueError:
            raise ValueError(f"QBITTORRENT_PORT must be an integer, got: '{os.getenv('QBITTORRENT_PORT')}'")
        self.qbt_username = self._get_required('QBITTORRENT_USERNAME')
        self.qbt_password = self._get_required('QBITTORRENT_PASSWORD')

        self.torrent_dir = Path(os.getenv('TORRENT_DIR', '/data/torrents'))
        self.media_library_dir = Path(os.getenv('MEDIA_LIBRARY_DIR', '/data/media'))

        self.deletion_rules = self._parse_deletion_criteria(
            os.getenv('DELETION_CRITERIA', '30d 2.0')
        )

        self.dry_run = os.getenv('DRY_RUN', 'true').lower() in ('true', '1', 'yes')
        self.fix_hardlinks = os.getenv('FIX_HARDLINKS', 'true').lower() in ('true', '1', 'yes')

        # Data directory base path (used for cache and logs)
        self.data_dir = Path(os.getenv('DATA_DIR', '/app/data/torrent-cleaner'))

        # File hash cache settings
        self.enable_cache = os.getenv('ENABLE_CACHE', 'true').lower() in ('true', '1', 'yes')
        self.cache_db_path = os.getenv('CACHE_DB_PATH', None)  # None = use default location

        self.discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL', '')

        # Dead tracker cleanup
        self.delete_dead_trackers = os.getenv('DELETE_DEAD_TRACKERS', 'false').lower() in ('true', '1', 'yes')
        dead_msg_raw = os.getenv('DEAD_TRACKER_MESSAGES', '')
        self.dead_tracker_messages = [m.strip() for m in dead_msg_raw.split('|') if m.strip()]

        self.media_extensions = self._parse_media_extensions(
            os.getenv('MEDIA_EXTENSIONS', '.mkv,.mp4,.avi,.mov,.m4v,.wmv,.flv,.webm,.ts,.m2ts')
        )

        self.log_level = os.getenv('LOG_LEVEL', 'INFO')
        self.log_file = os.getenv('LOG_FILE', str(self.data_dir / 'logs' / 'cleaner.log'))

        try:
            self.log_max_files = int(os.getenv('LOG_MAX_FILES', '5'))
        except ValueError:
            raise ValueError(f"LOG_MAX_FILES must be an integer, got: '{os.getenv('LOG_MAX_FILES')}'")
        if self.log_max_files < 0:
            raise ValueError(f"LOG_MAX_FILES must be >= 0, got: {self.log_max_files}")

        self._validate()

    @staticmethod
    def _parse_media_extensions(raw: str) -> Set[str]:
        """Parse comma-separated media extensions, normalizing to lowercase with leading dot."""
        extensions = set()
        for ext in raw.split(','):
            ext = ext.strip().lower()
            if not ext:
                continue
            if not ext.startswith('.'):
                ext = '.' + ext
            extensions.add(ext)
        if not extensions:
            raise ValueError("MEDIA_EXTENSIONS must contain at least one extension")
        return extensions

    def _get_required(self, key: str) -> str:
        """Get required environment variable or raise error."""
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Required environment variable not set: {key}")
        return value

    @staticmethod
    def _parse_deletion_criteria(raw: str) -> List[DeletionRule]:
        """Parse DELETION_CRITERIA string into a list of DeletionRule objects.

        Format: rules separated by | (OR logic), tokens within a rule separated by space (AND logic).
        Duration tokens end with d/m/y (e.g. 30d, 3m, 1y). Ratio tokens are plain numbers (e.g. 2.0).

        Raises:
            ValueError: On empty input, empty rules, invalid tokens, or duplicate duration/ratio in a rule.
        """
        if not raw or not raw.strip():
            raise ValueError("DELETION_CRITERIA cannot be empty")

        rules = []
        for rule_str in raw.split('|'):
            rule_str = rule_str.strip()
            if not rule_str:
                raise ValueError("DELETION_CRITERIA contains an empty rule (double pipe or trailing pipe)")

            tokens = rule_str.split()
            rule = DeletionRule()

            for token in tokens:
                token_lower = token.strip().lower()
                if not token_lower:
                    continue

                # Check if it's a duration (ends with d/m/y)
                if token_lower[-1] in ('d', 'm', 'y'):
                    if rule.min_duration is not None:
                        raise ValueError(f"Duplicate duration in rule '{rule_str}': already have '{rule.min_duration}', got '{token}'")
                    Config.parse_duration(token)
                    rule.min_duration = token.strip()
                else:
                    # Must be a ratio
                    try:
                        ratio = float(token)
                    except ValueError:
                        raise ValueError(f"Invalid token in DELETION_CRITERIA: '{token}' (expected duration like 30d or number like 2.0)")
                    if ratio < 0:
                        raise ValueError(f"Ratio must be >= 0, got: {ratio}")
                    if rule.min_ratio is not None:
                        raise ValueError(f"Duplicate ratio in rule '{rule_str}': already have '{rule.min_ratio}', got '{token}'")
                    rule.min_ratio = ratio

            if rule.min_duration is None and rule.min_ratio is None:
                raise ValueError(f"Rule '{rule_str}' has no valid conditions")

            rules.append(rule)

        if not rules:
            raise ValueError("DELETION_CRITERIA must contain at least one rule")

        return rules

    def _validate(self):
        """Validate configuration values."""
        if not self.torrent_dir.exists():
            raise ValueError(f"Torrent directory does not exist: {self.torrent_dir}")

        if not self.media_library_dir.exists():
            raise ValueError(f"Media library directory does not exist: {self.media_library_dir}")

        if not self.dry_run and not os.access(self.torrent_dir, os.W_OK):
            raise ValueError(f"Torrent directory is not writable: {self.torrent_dir}")

        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ValueError(f"Cannot create data directory {self.data_dir}: {e}")
        if not os.access(self.data_dir, os.W_OK):
            raise ValueError(f"Data directory is not writable: {self.data_dir}")

        if self.cache_db_path:
            cache_parent = Path(self.cache_db_path).parent
            try:
                cache_parent.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise ValueError(f"Cannot create cache directory {cache_parent}: {e}")

    @staticmethod
    def parse_duration(duration_str: str) -> timedelta:
        """
        Parse duration string to timedelta.

        Args:
            duration_str: Duration string like "30d", "3m", "1y"

        Returns:
            timedelta object

        Raises:
            ValueError: If format is invalid
        """
        duration_str = duration_str.strip().lower()

        if not duration_str:
            raise ValueError("Duration string is empty")

        if duration_str[-1] not in ('d', 'm', 'y'):
            raise ValueError(f"Invalid duration unit. Use 'd' (days), 'm' (months), or 'y' (years): {duration_str}")

        try:
            value = int(duration_str[:-1])
        except ValueError:
            raise ValueError(f"Invalid duration value: {duration_str}")

        unit = duration_str[-1]

        if value < 0:
            raise ValueError(f"Duration value must be positive: {duration_str}")

        if unit == 'd':
            days = value
        elif unit == 'm':
            days = value * 30  # Approximate month as 30 days
        elif unit == 'y':
            days = value * 365  # Approximate year as 365 days

        return timedelta(days=days)

    @staticmethod
    def format_deletion_rules(rules: List[DeletionRule]) -> str:
        """Format deletion rules for display."""
        parts = []
        for rule in rules:
            tokens = []
            if rule.min_duration is not None:
                tokens.append(rule.min_duration)
            if rule.min_ratio is not None:
                tokens.append(str(rule.min_ratio))
            parts.append(' '.join(tokens))
        return ' | '.join(parts)

    def __str__(self) -> str:
        """Return string representation of config."""
        return (
            f"Config(\n"
            f"  qbt_host={self.qbt_host}:{self.qbt_port}\n"
            f"  torrent_dir={self.torrent_dir}\n"
            f"  media_library_dir={self.media_library_dir}\n"
            f"  deletion_rules={self.format_deletion_rules(self.deletion_rules)}\n"
            f"  dry_run={self.dry_run}\n"
            f"  fix_hardlinks={self.fix_hardlinks}\n"
            f"  enable_cache={self.enable_cache}\n"
            f"  cache_db_path={self.cache_db_path or 'default'}\n"
            f"  media_extensions={','.join(sorted(self.media_extensions))}\n"
            f"  discord_webhook={'configured' if self.discord_webhook_url else 'not configured'}\n"
            f"  log_max_files={self.log_max_files}\n"
            f")"
        )
