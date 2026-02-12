"""Configuration management for torrent cleaner."""

import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv


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

        self.min_seeding_duration = os.getenv('MIN_SEEDING_DURATION', '30d')
        try:
            self.min_ratio = float(os.getenv('MIN_RATIO', '2.0'))
        except ValueError:
            raise ValueError(f"MIN_RATIO must be a number, got: '{os.getenv('MIN_RATIO')}'")


        self.dry_run = os.getenv('DRY_RUN', 'true').lower() in ('true', '1', 'yes')
        self.fix_hardlinks = os.getenv('FIX_HARDLINKS', 'true').lower() in ('true', '1', 'yes')

        # Data directory base path (used for cache and logs)
        self.data_dir = Path(os.getenv('DATA_DIR', '/app/data/torrent-cleaner'))

        # File hash cache settings
        self.enable_cache = os.getenv('ENABLE_CACHE', 'true').lower() in ('true', '1', 'yes')
        self.cache_db_path = os.getenv('CACHE_DB_PATH', None)  # None = use default location

        self.discord_webhook_url = os.getenv('DISCORD_WEBHOOK_URL', '')

        self.log_level = os.getenv('LOG_LEVEL', 'INFO')
        self.log_file = os.getenv('LOG_FILE', str(self.data_dir / 'logs' / 'cleaner.log'))

        self._validate()

    def _get_required(self, key: str) -> str:
        """Get required environment variable or raise error."""
        value = os.getenv(key)
        if not value:
            raise ValueError(f"Required environment variable not set: {key}")
        return value

    def _validate(self):
        """Validate configuration values."""
        if not self.torrent_dir.exists():
            raise ValueError(f"Torrent directory does not exist: {self.torrent_dir}")

        if not self.media_library_dir.exists():
            raise ValueError(f"Media library directory does not exist: {self.media_library_dir}")

        if not os.access(self.torrent_dir, os.W_OK):
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

        if self.min_ratio < 0:
            raise ValueError(f"MIN_RATIO must be >= 0, got: {self.min_ratio}")

        try:
            self.parse_duration(self.min_seeding_duration)
        except ValueError as e:
            raise ValueError(f"Invalid MIN_SEEDING_DURATION format: {e}")

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

    def __str__(self) -> str:
        """Return string representation of config."""
        return (
            f"Config(\n"
            f"  qbt_host={self.qbt_host}:{self.qbt_port}\n"
            f"  torrent_dir={self.torrent_dir}\n"
            f"  media_library_dir={self.media_library_dir}\n"
            f"  min_seeding_duration={self.min_seeding_duration}\n"
            f"  min_ratio={self.min_ratio}\n"
            f"  dry_run={self.dry_run}\n"
            f"  fix_hardlinks={self.fix_hardlinks}\n"
            f"  enable_cache={self.enable_cache}\n"
            f"  cache_db_path={self.cache_db_path or 'default'}\n"
            f"  discord_webhook={'configured' if self.discord_webhook_url else 'not configured'}\n"
            f")"
        )
