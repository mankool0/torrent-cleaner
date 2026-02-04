"""File hashing utilities using xxHash."""

import xxhash
from pathlib import Path


def hash_file(file_path: str | Path, chunk_size: int = 65536) -> str:
    """
    Calculate xxHash64 digest of a file.

    Args:
        file_path: Path to file to hash
        chunk_size: Size of chunks to read (default 64KB)

    Returns:
        Hexadecimal hash digest string

    Raises:
        FileNotFoundError: If file doesn't exist
        PermissionError: If file cannot be read
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if not file_path.is_file():
        raise ValueError(f"Not a file: {file_path}")

    hasher = xxhash.xxh64()

    with open(file_path, 'rb') as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)

    return hasher.hexdigest()
