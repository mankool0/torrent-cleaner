"""SQLite-based file hash cache for faster media library indexing."""

import os
import time
from pathlib import Path
from typing import Optional
import logging
from peewee import SqliteDatabase, Model, CharField, IntegerField, FloatField

from src.models import FileCacheStats


db = SqliteDatabase(None)


class FileCacheEntry(Model):
    """File cache entry model."""
    path = CharField(primary_key=True)   # Absolute file path
    size = IntegerField()                # File size in bytes
    mtime = FloatField()                 # Modification time (Unix timestamp)
    hash = CharField()                   # xxhash hex string
    last_accessed = FloatField()         # Last access time (Unix timestamp)

    class Meta:
        database = db
        table_name = 'file_cache'


class FileCache:
    """SQLite-based file hash cache."""

    def __init__(self, db_path: str = None):
        """
        Initialize file cache.

        Args:
            db_path: Path to SQLite database file. If None, uses default location.
        """
        self.logger = logging.getLogger(__name__)

        if db_path is None:
            # Default to /app/data/torrent-cleaner/cache/file_cache.db
            cache_dir = Path('/app/data/torrent-cleaner/cache')
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(cache_dir / 'file_cache.db')

        self.db_path = db_path

        # Initialize database
        db.init(db_path)
        db.connect()
        db.create_tables([FileCacheEntry])

        self.logger.info(f"Initialized file cache at {db_path}")

    def get_cached_hash(self, file_path: str) -> Optional[str]:
        """
        Get cached hash for file if it exists and is still valid.

        Args:
            file_path: Absolute path to file

        Returns:
            Cached hash if valid, None otherwise
        """
        try:
            # Get current file stats
            stat = os.stat(file_path)
            size = stat.st_size
            mtime = stat.st_mtime

            # Look up in cache
            try:
                entry = FileCacheEntry.get(FileCacheEntry.path == file_path)

                # Check if cache is still valid (size and mtime match)
                if entry.size == size and entry.mtime == mtime:
                    # Update last_accessed
                    entry.last_accessed = time.time()
                    entry.save()

                    self.logger.debug(f"Cache hit: {file_path}")
                    return entry.hash
                else:
                    self.logger.debug(f"Cache invalid (size/mtime changed): {file_path}")
                    return None

            except FileCacheEntry.DoesNotExist:
                self.logger.debug(f"Cache miss: {file_path}")
                return None

        except OSError as e:
            self.logger.warning(f"Error checking cache for {file_path}: {e}")
            return None

    def store_hash(self, file_path: str, file_hash: str):
        """
        Store or update file hash in cache.

        Args:
            file_path: Absolute path to file
            file_hash: xxhash hex string
        """
        try:
            stat = os.stat(file_path)
            size = stat.st_size
            mtime = stat.st_mtime
            now = time.time()

            FileCacheEntry.replace(
                path=file_path,
                size=size,
                mtime=mtime,
                hash=file_hash,
                last_accessed=now
            ).execute()

            self.logger.debug(f"Cached hash for: {file_path}")

        except OSError as e:
            self.logger.warning(f"Error storing cache for {file_path}: {e}")

    def clear_cache(self):
        """Clear all cached entries."""
        try:
            FileCacheEntry.delete().execute()
            self.logger.info("Cleared file cache")
        except Exception as e:
            self.logger.error(f"Error clearing cache: {e}")

    def get_stats(self) -> FileCacheStats:
        """Get cache statistics."""
        try:
            total_entries = FileCacheEntry.select().count()
            db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
            return FileCacheStats(total_entries=total_entries, db_size_bytes=db_size)
        except Exception as e:
            self.logger.error(f"Error getting cache stats: {e}")
            return FileCacheStats(total_entries=0, db_size_bytes=0)

    def close(self):
        """Close database connection."""
        if not db.is_closed():
            db.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()