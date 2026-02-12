"""Unit tests for FileCache class."""

import pytest
import os
import time
import tempfile
from pathlib import Path
from src.file_cache import FileCache


@pytest.fixture
def cache_dir():
    """Create a temporary directory for cache database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def cache(cache_dir):
    """Create a FileCache instance with temp database."""
    db_path = os.path.join(cache_dir, 'test_cache.db')
    fc = FileCache(db_path=db_path)
    yield fc
    fc.close()


@pytest.fixture
def sample_file(cache_dir):
    """Create a temporary file to cache."""
    path = os.path.join(cache_dir, 'sample.bin')
    with open(path, 'wb') as f:
        f.write(b'hello world')
    return path


class TestFileCache:

    def test_store_and_retrieve_hash(self, cache, sample_file):
        """Test basic store and retrieve round-trip."""
        cache.store_hash(sample_file, 'abc123')
        result = cache.get_cached_hash(sample_file)
        assert result == 'abc123'

    def test_cache_miss_nonexistent(self, cache):
        """Test cache miss for file not in cache."""
        result = cache.get_cached_hash('/nonexistent/file.bin')
        assert result is None

    def test_invalidation_on_size_change(self, cache, sample_file):
        """Test that cache invalidates when file size changes."""
        cache.store_hash(sample_file, 'abc123')

        # Modify file size
        with open(sample_file, 'ab') as f:
            f.write(b'extra data')

        # Preserve mtime so only size differs
        result = cache.get_cached_hash(sample_file)
        assert result is None

    def test_invalidation_on_mtime_change(self, cache, sample_file):
        """Test that cache invalidates when file mtime changes."""
        cache.store_hash(sample_file, 'abc123')

        # Touch the file to change mtime (keep same content/size)
        original_size = os.stat(sample_file).st_size
        time.sleep(0.05)
        os.utime(sample_file, None)

        # Verify size unchanged but mtime changed
        assert os.stat(sample_file).st_size == original_size

        result = cache.get_cached_hash(sample_file)
        assert result is None

    def test_clear_cache(self, cache, sample_file):
        """Test clearing all cache entries."""
        cache.store_hash(sample_file, 'abc123')
        assert cache.get_cached_hash(sample_file) == 'abc123'

        cache.clear_cache()

        assert cache.get_cached_hash(sample_file) is None
        stats = cache.get_stats()
        assert stats.total_entries == 0

    def test_get_stats(self, cache, sample_file):
        """Test cache statistics."""
        stats = cache.get_stats()
        assert stats.total_entries == 0

        cache.store_hash(sample_file, 'abc123')

        stats = cache.get_stats()
        assert stats.total_entries == 1
        assert stats.db_size_bytes > 0

    def test_update_existing(self, cache, sample_file):
        """Test that storing a hash for the same file updates the entry."""
        cache.store_hash(sample_file, 'abc123')
        assert cache.get_cached_hash(sample_file) == 'abc123'

        cache.store_hash(sample_file, 'def456')
        assert cache.get_cached_hash(sample_file) == 'def456'

        stats = cache.get_stats()
        assert stats.total_entries == 1

    def test_context_manager(self, cache_dir):
        """Test that __enter__ and __exit__ work correctly."""
        db_path = os.path.join(cache_dir, 'ctx_cache.db')
        with FileCache(db_path=db_path) as fc:
            assert fc is not None
            # Should be usable inside context
            stats = fc.get_stats()
            assert stats.total_entries == 0
