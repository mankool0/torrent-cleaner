"""Unit tests for FileAnalyzer class."""

import pytest
import os
import tempfile
from pathlib import Path
from src.file_analyzer import FileAnalyzer
from src.models import SizeIndex


class TestIsMediaFile:
    """Test is_media_file() method."""

    def test_media_extensions(self):
        """Test that media file extensions are recognized."""
        analyzer = FileAnalyzer()

        # Video formats
        assert analyzer.is_media_file('/path/to/movie.mkv') == True
        assert analyzer.is_media_file('/path/to/movie.mp4') == True
        assert analyzer.is_media_file('/path/to/movie.avi') == True
        assert analyzer.is_media_file('/path/to/movie.mov') == True
        assert analyzer.is_media_file('/path/to/movie.m4v') == True
        assert analyzer.is_media_file('/path/to/movie.wmv') == True
        assert analyzer.is_media_file('/path/to/movie.flv') == True
        assert analyzer.is_media_file('/path/to/movie.webm') == True
        assert analyzer.is_media_file('/path/to/movie.ts') == True
        assert analyzer.is_media_file('/path/to/movie.m2ts') == True

    def test_non_media_extensions(self):
        """Test that non-media file extensions are not recognized."""
        analyzer = FileAnalyzer()

        assert analyzer.is_media_file('/path/to/subtitle.srt') == False
        assert analyzer.is_media_file('/path/to/info.nfo') == False
        assert analyzer.is_media_file('/path/to/readme.txt') == False
        assert analyzer.is_media_file('/path/to/data.json') == False
        assert analyzer.is_media_file('/path/to/script.py') == False

    def test_case_insensitive(self):
        """Test that extension matching is case insensitive."""
        analyzer = FileAnalyzer()

        assert analyzer.is_media_file('/path/to/movie.MKV') == True
        assert analyzer.is_media_file('/path/to/movie.Mp4') == True
        assert analyzer.is_media_file('/path/to/movie.AVI') == True
        assert analyzer.is_media_file('/path/to/subtitle.SRT') == False

    def test_no_extension(self):
        """Test files without extensions."""
        analyzer = FileAnalyzer()

        assert analyzer.is_media_file('/path/to/file') == False
        assert analyzer.is_media_file('movie') == False

    def test_custom_extensions(self):
        """Test custom media extensions passed via constructor."""
        analyzer = FileAnalyzer(media_extensions={'.mkv', '.srt'})

        assert analyzer.is_media_file('/path/to/movie.mkv') == True
        assert analyzer.is_media_file('/path/to/subtitle.srt') == True
        assert analyzer.is_media_file('/path/to/movie.mp4') == False


class TestBuildSizeIndex:
    """Test build_size_index() method."""

    def test_single_file(self):
        """Test size indexing a single file."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            media_dir = Path(tmpdir)
            file1 = media_dir / 'movie.mkv'
            file1.write_bytes(b'Movie content')

            index = analyzer.build_size_index(media_dir)

            assert len(index) == 1
            size = os.stat(file1).st_size
            assert size in index
            assert str(file1) in index[size]

    def test_multiple_same_size(self):
        """Test that files with same size are grouped."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            media_dir = Path(tmpdir)
            file1 = media_dir / 'movie1.mkv'
            file2 = media_dir / 'movie2.mkv'
            content = b'Same size content'
            file1.write_bytes(content)
            file2.write_bytes(content)

            index = analyzer.build_size_index(media_dir)

            size = len(content)
            assert size in index
            assert len(index[size]) == 2

    def test_different_sizes(self):
        """Test files with different sizes are separate."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            media_dir = Path(tmpdir)
            file1 = media_dir / 'small.mkv'
            file2 = media_dir / 'large.mkv'
            file1.write_bytes(b'small')
            file2.write_bytes(b'much larger content')

            index = analyzer.build_size_index(media_dir)

            assert len(index) == 2

    def test_nested_directories(self):
        """Test indexing files in nested directories."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            media_dir = Path(tmpdir)
            subdir = media_dir / 'movies' / '2024'
            subdir.mkdir(parents=True)

            file1 = media_dir / 'movie1.mkv'
            file2 = subdir / 'movie2.mkv'
            file1.write_bytes(b'Movie 1')
            file2.write_bytes(b'Movie 22')

            index = analyzer.build_size_index(media_dir)

            assert len(index) == 2

    def test_with_extension_filter(self):
        """Test size index with extension filter."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            media_dir = Path(tmpdir)
            mkv = media_dir / 'movie.mkv'
            srt = media_dir / 'subtitle.srt'
            mkv.write_bytes(b'MKV content')
            srt.write_bytes(b'SRT content')

            index = analyzer.build_size_index(media_dir, extensions={'.mkv'})

            # Only mkv should be indexed
            assert any(str(mkv) in paths for paths in index.values())
            assert not any(str(srt) in paths for paths in index.values())

    def test_empty_directory(self):
        """Test size index of empty directory."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            index = analyzer.build_size_index(Path(tmpdir))
            assert len(index) == 0

    def test_nonexistent_directory(self):
        """Test that ValueError is raised for non-existent directory."""
        analyzer = FileAnalyzer()

        with pytest.raises(ValueError, match="Media directory does not exist"):
            analyzer.build_size_index(Path('/nonexistent/path'))

    def test_skips_directories(self):
        """Test that directories are skipped during indexing."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            media_dir = Path(tmpdir)
            subdir = media_dir / 'subdir'
            subdir.mkdir()

            file1 = media_dir / 'movie.mkv'
            file1.write_bytes(b'Movie')

            index = analyzer.build_size_index(media_dir)

            total_files = sum(len(paths) for paths in index.values())
            assert total_files == 1


class TestFindIdenticalFile:
    """Test find_identical_file() method."""

    def test_exact_match(self):
        """Test finding exact match via size index."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            orphaned_file = tmpdir / 'orphan.mkv'
            orphaned_file.write_bytes(b'Movie content')

            media_file = tmpdir / 'media' / 'movie.mkv'
            media_file.parent.mkdir()
            media_file.write_bytes(b'Movie content')

            size = os.stat(orphaned_file).st_size
            size_index = SizeIndex()
            size_index.add(size, str(media_file))

            result = analyzer.find_identical_file(str(orphaned_file), size_index=size_index)

            assert result == str(media_file)

    def test_no_match_different_content(self):
        """Test no match when content differs (same size)."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            orphaned_file = tmpdir / 'orphan.mkv'
            orphaned_file.write_bytes(b'Content AAAA')

            media_file = tmpdir / 'media.mkv'
            media_file.write_bytes(b'Content BBBB')

            size = os.stat(orphaned_file).st_size
            size_index = SizeIndex()
            size_index.add(size, str(media_file))

            result = analyzer.find_identical_file(str(orphaned_file), size_index=size_index)

            assert result is None

    def test_no_match_wrong_size(self):
        """Test no match when no candidates have matching size."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            orphaned_file = tmpdir / 'orphan.mkv'
            orphaned_file.write_bytes(b'Short')

            media_file = tmpdir / 'media.mkv'
            media_file.write_bytes(b'Much longer content here')

            media_size = os.stat(media_file).st_size
            size_index = SizeIndex()
            size_index.add(media_size, str(media_file))

            result = analyzer.find_identical_file(str(orphaned_file), size_index=size_index)

            assert result is None

    def test_uses_internal_size_index(self):
        """Test that find_identical_file uses self._size_index when set."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            orphaned_file = tmpdir / 'orphan.mkv'
            orphaned_file.write_bytes(b'Movie content')

            media_dir = tmpdir / 'media'
            media_dir.mkdir()
            media_file = media_dir / 'movie.mkv'
            media_file.write_bytes(b'Movie content')

            analyzer.build_size_index(media_dir)

            # Call without explicit size_index
            result = analyzer.find_identical_file(str(orphaned_file))

            assert result == str(media_file)

    def test_no_size_index_returns_none(self):
        """Test that find_identical_file returns None when no index available."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            orphaned_file = Path(tmpdir) / 'orphan.mkv'
            orphaned_file.write_bytes(b'Content')

            result = analyzer.find_identical_file(str(orphaned_file))
            assert result is None


class TestFileAnalyzerWithCache:
    """Test FileAnalyzer with cache integration."""

    def test_works_without_cache(self):
        """Test that FileAnalyzer works fine without cache."""
        analyzer = FileAnalyzer(cache=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            media_dir = Path(tmpdir)
            file1 = media_dir / 'movie.mkv'
            file1.write_bytes(b'Movie content')

            index = analyzer.build_size_index(media_dir)
            assert len(index) == 1

    def test_cache_populates_on_find(self):
        """Test that finding a file populates the cache."""
        from src.file_cache import FileCache

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            db_path = str(tmpdir / 'cache.db')

            cache = FileCache(db_path=db_path)
            analyzer = FileAnalyzer(cache=cache)

            media_dir = tmpdir / 'media'
            media_dir.mkdir()
            media_file = media_dir / 'movie.mkv'
            media_file.write_bytes(b'Movie content')

            orphaned_file = tmpdir / 'orphan.mkv'
            orphaned_file.write_bytes(b'Movie content')

            size_index = analyzer.build_size_index(media_dir)
            analyzer.find_identical_file(str(orphaned_file), size_index=size_index)

            # Both files should now be cached
            assert cache.get_cached_hash(str(media_file)) is not None
            assert cache.get_cached_hash(str(orphaned_file)) is not None

            cache.close()

    def test_cache_hits_tracked(self):
        """Test that cache hits/misses are tracked."""
        from src.file_cache import FileCache

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            db_path = str(tmpdir / 'cache.db')

            cache = FileCache(db_path=db_path)
            analyzer = FileAnalyzer(cache=cache)

            media_dir = tmpdir / 'media'
            media_dir.mkdir()
            media_file = media_dir / 'movie.mkv'
            media_file.write_bytes(b'Movie content')

            orphaned_file = tmpdir / 'orphan.mkv'
            orphaned_file.write_bytes(b'Movie content')

            size_index = analyzer.build_size_index(media_dir)

            # First find: both files are cache misses
            analyzer.find_identical_file(str(orphaned_file), size_index=size_index)
            stats = analyzer.get_cache_stats()
            assert stats.misses == 2
            assert stats.hits == 0

            # Second find: both files are cache hits
            analyzer.find_identical_file(str(orphaned_file), size_index=size_index)
            stats = analyzer.get_cache_stats()
            assert stats.hits == 2
            assert stats.misses == 2

            cache.close()
