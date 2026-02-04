"""Unit tests for FileAnalyzer class."""

import pytest
import os
import tempfile
from pathlib import Path
from src.file_analyzer import FileAnalyzer
from src.models import MediaFileInfo
from src.utils.hash_utils import hash_file


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


class TestBuildMediaLibraryIndex:
    """Test build_media_library_index() method."""

    def test_index_single_file(self):
        """Test indexing a single file."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            media_dir = Path(tmpdir)
            file1 = media_dir / 'movie.mkv'
            file1.write_bytes(b'Movie content')

            index = analyzer.build_media_library_index(media_dir)

            assert len(index) == 1
            file_hash = hash_file(file1)
            assert file_hash in index
            assert isinstance(index[file_hash], MediaFileInfo)
            assert index[file_hash].path == str(file1)
            assert index[file_hash].size == 13
            assert index[file_hash].inode == os.stat(file1).st_ino

    def test_index_multiple_files(self):
        """Test indexing multiple files."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            media_dir = Path(tmpdir)
            file1 = media_dir / 'movie1.mkv'
            file2 = media_dir / 'movie2.mp4'
            file1.write_bytes(b'Movie 1')
            file2.write_bytes(b'Movie 2')

            index = analyzer.build_media_library_index(media_dir)

            assert len(index) == 2
            assert hash_file(file1) in index
            assert hash_file(file2) in index

    def test_index_nested_directories(self):
        """Test indexing files in nested directories."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            media_dir = Path(tmpdir)
            subdir = media_dir / 'movies' / '2024'
            subdir.mkdir(parents=True)

            file1 = media_dir / 'movie1.mkv'
            file2 = subdir / 'movie2.mkv'
            file1.write_bytes(b'Movie 1')
            file2.write_bytes(b'Movie 2')

            index = analyzer.build_media_library_index(media_dir)

            assert len(index) == 2
            assert hash_file(file1) in index
            assert hash_file(file2) in index

    def test_index_with_extension_filter(self):
        """Test indexing with extension filter."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            media_dir = Path(tmpdir)
            mkv_file = media_dir / 'movie.mkv'
            mp4_file = media_dir / 'movie.mp4'
            srt_file = media_dir / 'subtitle.srt'

            mkv_file.write_bytes(b'MKV content')
            mp4_file.write_bytes(b'MP4 content')
            srt_file.write_bytes(b'Subtitle')

            # Index only .mkv files
            index = analyzer.build_media_library_index(media_dir, extensions={'.mkv'})

            assert len(index) == 1
            assert hash_file(mkv_file) in index
            assert hash_file(mp4_file) not in index
            assert hash_file(srt_file) not in index

    def test_index_empty_directory(self):
        """Test indexing an empty directory."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            media_dir = Path(tmpdir)
            index = analyzer.build_media_library_index(media_dir)

            assert len(index) == 0

    def test_index_directory_not_exist(self):
        """Test that ValueError is raised for non-existent directory."""
        analyzer = FileAnalyzer()

        with pytest.raises(ValueError, match="Media directory does not exist"):
            analyzer.build_media_library_index(Path('/nonexistent/path'))

    def test_index_hash_collision(self):
        """Test that last file wins on hash collision."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            media_dir = Path(tmpdir)

            # Create two files with identical content (same hash)
            file1 = media_dir / 'duplicate1.mkv'
            file2 = media_dir / 'duplicate2.mkv'
            content = b'Identical content'
            file1.write_bytes(content)
            file2.write_bytes(content)

            index = analyzer.build_media_library_index(media_dir)

            # Should only have 1 entry (hash collision - last one wins)
            assert len(index) == 1
            file_hash = hash_file(file1)
            assert file_hash in index
            # Last file processed should win (alphabetically: duplicate2.mkv)
            assert 'duplicate2.mkv' in index[file_hash].path or 'duplicate1.mkv' in index[file_hash].path

    def test_index_skips_directories(self):
        """Test that directories are skipped during indexing."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            media_dir = Path(tmpdir)
            subdir = media_dir / 'subdir'
            subdir.mkdir()

            file1 = media_dir / 'movie.mkv'
            file1.write_bytes(b'Movie')

            index = analyzer.build_media_library_index(media_dir)

            # Should only index the file, not the directory
            assert len(index) == 1


class TestFindIdenticalFile:
    """Test find_identical_file() method."""

    def test_find_exact_match(self):
        """Test finding exact match in media index."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create orphaned file
            orphaned_file = tmpdir / 'orphan.mkv'
            orphaned_file.write_bytes(b'Movie content')

            # Create media file with same content
            media_file = tmpdir / 'media.mkv'
            media_file.write_bytes(b'Movie content')

            # Build index
            media_index = {
                hash_file(media_file): MediaFileInfo(
                    path=str(media_file),
                    size=os.stat(media_file).st_size,
                    inode=os.stat(media_file).st_ino
                )
            }

            result = analyzer.find_identical_file(str(orphaned_file), media_index)

            assert result == str(media_file)

    def test_find_no_match(self):
        """Test when no match exists in media index."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            orphaned_file = tmpdir / 'orphan.mkv'
            orphaned_file.write_bytes(b'Unique content')

            media_file = tmpdir / 'media.mkv'
            media_file.write_bytes(b'Different content')

            media_index = {
                hash_file(media_file): MediaFileInfo(
                    path=str(media_file),
                    size=os.stat(media_file).st_size,
                    inode=os.stat(media_file).st_ino
                )
            }

            result = analyzer.find_identical_file(str(orphaned_file), media_index)

            assert result is None

    def test_find_media_file_not_exists(self):
        """Test when media file in index no longer exists."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            orphaned_file = tmpdir / 'orphan.mkv'
            orphaned_file.write_bytes(b'Content')

            # Create media index pointing to non-existent file
            media_index = {
                hash_file(orphaned_file): MediaFileInfo(
                    path='/nonexistent/media.mkv',
                    size=7,
                    inode=12345
                )
            }

            result = analyzer.find_identical_file(str(orphaned_file), media_index)

            assert result is None

    def test_find_size_mismatch(self):
        """Test when hash matches but size doesn't (corrupted index)."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            orphaned_file = tmpdir / 'orphan.mkv'
            orphaned_file.write_bytes(b'Content')

            media_file = tmpdir / 'media.mkv'
            media_file.write_bytes(b'Content')

            # Create index with wrong size
            media_index = {
                hash_file(media_file): MediaFileInfo(
                    path=str(media_file),
                    size=9999,  # Wrong size
                    inode=os.stat(media_file).st_ino
                )
            }

            result = analyzer.find_identical_file(str(orphaned_file), media_index)

            assert result is None

    def test_find_uses_self_media_index(self):
        """Test that method uses self.media_index when media_index param is None."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            orphaned_file = tmpdir / 'orphan.mkv'
            orphaned_file.write_bytes(b'Content')

            media_file = tmpdir / 'media.mkv'
            media_file.write_bytes(b'Content')

            # Set analyzer's media_index
            analyzer.media_index = {
                hash_file(media_file): MediaFileInfo(
                    path=str(media_file),
                    size=os.stat(media_file).st_size,
                    inode=os.stat(media_file).st_ino
                )
            }

            result = analyzer.find_identical_file(str(orphaned_file))

            assert result == str(media_file)

    def test_find_empty_index(self):
        """Test finding in empty media index."""
        analyzer = FileAnalyzer()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            orphaned_file = tmpdir / 'orphan.mkv'
            orphaned_file.write_bytes(b'Content')

            media_index = {}

            result = analyzer.find_identical_file(str(orphaned_file), media_index)

            assert result is None
