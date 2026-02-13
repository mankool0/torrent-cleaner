"""Unit tests for SpaceAccountant class."""

import os

from src.main import SpaceAccountant


class TestSpaceAccountant:

    def test_single_file_no_hardlinks(self, tmp_path):
        """Single file with nlink=1 — full size is counted."""
        f = tmp_path / "file.bin"
        f.write_bytes(b"x" * 1000)

        sa = SpaceAccountant()
        freed = sa.estimate_freed([str(f)])
        assert freed == 1000

    def test_hardlinked_file_one_path_deleted(self, tmp_path):
        """File with nlink=2, only one path deleted — no space freed."""
        f1 = tmp_path / "file.bin"
        f1.write_bytes(b"x" * 2000)
        f2 = tmp_path / "link.bin"
        os.link(f1, f2)

        sa = SpaceAccountant()
        freed = sa.estimate_freed([str(f1)])
        assert freed == 0

    def test_hardlinked_file_both_paths_deleted(self, tmp_path):
        """Two paths to same inode both passed — size counted once."""
        f1 = tmp_path / "file.bin"
        f1.write_bytes(b"x" * 3000)
        f2 = tmp_path / "link.bin"
        os.link(f1, f2)

        sa = SpaceAccountant()
        freed1 = sa.estimate_freed([str(f1)])
        assert freed1 == 0
        freed2 = sa.estimate_freed([str(f2)])
        assert freed2 == 3000

    def test_hardlinked_file_both_paths_in_single_call(self, tmp_path):
        """Both paths in a single call — size counted once."""
        f1 = tmp_path / "file.bin"
        f1.write_bytes(b"x" * 4000)
        f2 = tmp_path / "link.bin"
        os.link(f1, f2)

        sa = SpaceAccountant()
        freed = sa.estimate_freed([str(f1), str(f2)])
        assert freed == 4000

    def test_three_links_two_deleted(self, tmp_path):
        """File with nlink=3 (e.g. torrent + cross-seed + media), two deleted — no space freed."""
        f1 = tmp_path / "torrent_a.bin"
        f1.write_bytes(b"x" * 5000)
        f2 = tmp_path / "torrent_b.bin"
        os.link(f1, f2)
        f3 = tmp_path / "media.bin"
        os.link(f1, f3)

        sa = SpaceAccountant()
        # Delete both torrent paths, media link remains
        freed = sa.estimate_freed([str(f1)])
        assert freed == 0
        freed = sa.estimate_freed([str(f2)])
        assert freed == 0

    def test_mixed_unique_and_hardlinked(self, tmp_path):
        """Multiple files, mix of unique and hardlinked."""
        unique = tmp_path / "unique.bin"
        unique.write_bytes(b"u" * 100)

        shared1 = tmp_path / "shared_a.bin"
        shared1.write_bytes(b"s" * 200)
        shared2 = tmp_path / "shared_b.bin"
        os.link(shared1, shared2)

        sa = SpaceAccountant()
        # First torrent: unique file + one side of shared
        freed1 = sa.estimate_freed([str(unique), str(shared1)])
        assert freed1 == 100  # unique counted, shared skipped

        # Second torrent: other side of shared
        freed2 = sa.estimate_freed([str(shared2)])
        assert freed2 == 200  # now both links pending, counted

    def test_missing_file_skipped(self, tmp_path):
        """Missing file path is gracefully skipped."""
        f = tmp_path / "exists.bin"
        f.write_bytes(b"x" * 500)
        missing = str(tmp_path / "gone.bin")

        sa = SpaceAccountant()
        freed = sa.estimate_freed([missing, str(f)])
        assert freed == 500

    def test_all_missing_files(self, tmp_path):
        """All missing files — returns 0."""
        sa = SpaceAccountant()
        freed = sa.estimate_freed([
            str(tmp_path / "a.bin"),
            str(tmp_path / "b.bin"),
        ])
        assert freed == 0

    def test_empty_file_list(self):
        """Empty file list — returns 0."""
        sa = SpaceAccountant()
        freed = sa.estimate_freed([])
        assert freed == 0
