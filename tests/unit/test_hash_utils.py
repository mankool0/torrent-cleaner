"""Unit tests for hash utilities."""

import pytest
import tempfile
from pathlib import Path
from src.utils.hash_utils import hash_file


class TestHashFile:
    """Test hash_file() function."""

    def test_hash_identical_content(self):
        """Test that identical content produces identical hash."""
        content = b'Test content for hashing'

        with tempfile.NamedTemporaryFile(delete=False) as f1:
            f1.write(content)
            file1 = Path(f1.name)

        with tempfile.NamedTemporaryFile(delete=False) as f2:
            f2.write(content)
            file2 = Path(f2.name)

        try:
            hash1 = hash_file(file1)
            hash2 = hash_file(file2)

            assert hash1 == hash2, "Identical content should produce identical hash"
        finally:
            file1.unlink()
            file2.unlink()

    def test_hash_different_content(self):
        """Test that different content produces different hash."""
        with tempfile.NamedTemporaryFile(delete=False) as f1:
            f1.write(b'Content A')
            file1 = Path(f1.name)

        with tempfile.NamedTemporaryFile(delete=False) as f2:
            f2.write(b'Content B')
            file2 = Path(f2.name)

        try:
            hash1 = hash_file(file1)
            hash2 = hash_file(file2)

            assert hash1 != hash2, "Different content should produce different hash"
        finally:
            file1.unlink()
            file2.unlink()

    def test_hash_empty_file(self):
        """Test hashing an empty file."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            file_path = Path(f.name)

        try:
            hash_result = hash_file(file_path)
            assert isinstance(hash_result, str)
            assert len(hash_result) > 0
        finally:
            file_path.unlink()

    def test_hash_large_file(self):
        """Test hashing a large file (tests chunked reading)."""
        # Create 10MB file
        content = b'X' * (10 * 1024 * 1024)

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(content)
            file_path = Path(f.name)

        try:
            hash_result = hash_file(file_path)
            assert isinstance(hash_result, str)
            assert len(hash_result) > 0
        finally:
            file_path.unlink()

    def test_hash_file_not_found(self):
        """Test that FileNotFoundError is raised for non-existent file."""
        with pytest.raises(FileNotFoundError, match="File not found"):
            hash_file('/nonexistent/path/to/file.txt')

    def test_hash_directory(self):
        """Test that ValueError is raised when path is a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="Not a file"):
                hash_file(tmpdir)

    def test_hash_with_path_object(self):
        """Test that Path objects work as input."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b'Test content')
            file_path = Path(f.name)

        try:
            hash_result = hash_file(file_path)
            assert isinstance(hash_result, str)
        finally:
            file_path.unlink()

    def test_hash_with_string_path(self):
        """Test that string paths work as input."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b'Test content')
            file_path = f.name

        try:
            hash_result = hash_file(file_path)
            assert isinstance(hash_result, str)
        finally:
            Path(file_path).unlink()

    def test_hash_deterministic(self):
        """Test that hashing the same file multiple times gives same result."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b'Deterministic test content')
            file_path = Path(f.name)

        try:
            hash1 = hash_file(file_path)
            hash2 = hash_file(file_path)
            hash3 = hash_file(file_path)

            assert hash1 == hash2 == hash3, "Hash should be deterministic"
        finally:
            file_path.unlink()

    def test_hash_single_byte_difference(self):
        """Test that even single byte difference produces different hash."""
        content1 = b'Test content with byte A'
        content2 = b'Test content with byte B'

        with tempfile.NamedTemporaryFile(delete=False) as f1:
            f1.write(content1)
            file1 = Path(f1.name)

        with tempfile.NamedTemporaryFile(delete=False) as f2:
            f2.write(content2)
            file2 = Path(f2.name)

        try:
            hash1 = hash_file(file1)
            hash2 = hash_file(file2)

            assert hash1 != hash2, "Single byte difference should change hash"
        finally:
            file1.unlink()
            file2.unlink()
