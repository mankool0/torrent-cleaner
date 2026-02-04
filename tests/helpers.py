"""Helper utilities for integration tests."""

import subprocess
import time
import bencode
from pathlib import Path
from typing import Dict


def set_torrent_test_metadata(torrent_hash, seeding_days, ratio):
    """
    Set seeding_time and ratio for testing by editing fastresume file.

    This allows testing deletion criteria without waiting for real seeding time.

    Args:
        torrent_hash: Hash of the torrent to modify
        seeding_days: Number of days to set for seeding_time
        ratio: Upload/download ratio to set
    """
    subprocess.run(
        ['docker-compose', '-f', 'docker-compose.test.yml', 'stop'],
        check=True,
        capture_output=True
    )

    import os
    test_data_path = os.environ.get('TEST_DATA_PATH', './test_data')
    fastresume_path = Path(f'{test_data_path}/config/qBittorrent/BT_backup/{torrent_hash}.fastresume')

    if not fastresume_path.exists():
        raise FileNotFoundError(f"FastResume file not found: {fastresume_path}")

    with open(fastresume_path, 'rb') as f:
        data = bencode.decode(f.read())

    seeding_seconds = seeding_days * 86400
    data[b'seeding_time'] = seeding_seconds

    # Set ratio by adjusting uploaded/downloaded
    downloaded = 1000000000  # 1GB
    uploaded = int(downloaded * ratio)
    data[b'uploaded'] = uploaded
    data[b'downloaded'] = downloaded

    with open(fastresume_path, 'wb') as f:
        f.write(bencode.encode(data))

    subprocess.run(
        ['docker-compose', '-f', 'docker-compose.test.yml', 'start'],
        check=True,
        capture_output=True
    )
    time.sleep(5)  # Wait for startup, TODO: Improve with healthcheck


def stop_qbittorrent():
    """Stop the qBittorrent test container."""
    subprocess.run(
        ['docker-compose', '-f', 'docker-compose.test.yml', 'stop'],
        check=True,
        capture_output=True
    )


def start_qbittorrent():
    """Start the qBittorrent test container."""
    subprocess.run(
        ['docker-compose', '-f', 'docker-compose.test.yml', 'start'],
        check=True,
        capture_output=True
    )
    time.sleep(5)  # Wait for startup


def restart_qbittorrent():
    """Restart the qBittorrent test container."""
    subprocess.run(
        ['docker-compose', '-f', 'docker-compose.test.yml', 'restart'],
        check=True,
        capture_output=True
    )
    time.sleep(5)  # Wait for startup


def get_torrent_by_hash(qb_client, torrent_hash, error_context=""):
    """
    Get a torrent by hash with helpful error message if not found.

    Args:
        qb_client: qBittorrent client
        torrent_hash: Hash of the torrent to find
        error_context: Additional context for error message

    Returns:
        The torrent object

    Raises:
        AssertionError: If torrent not found with detailed error message
    """
    torrents = qb_client.torrents_info(torrent_hashes=torrent_hash)

    if len(torrents) == 0:
        # Get all torrents to show what's actually there
        all_torrents = qb_client.torrents_info()

        error_msg = f"Torrent {torrent_hash} not found in qBittorrent"
        if error_context:
            error_msg += f" ({error_context})"

        if all_torrents:
            error_msg += f"\n  Available torrents ({len(all_torrents)}):"
            for t in all_torrents[:5]:  # Show first 5
                error_msg += f"\n    - {t.name} ({t.hash})"
            if len(all_torrents) > 5:
                error_msg += f"\n    ... and {len(all_torrents) - 5} more"
        else:
            error_msg += "\n  No torrents found in qBittorrent at all!"

        raise AssertionError(error_msg)

    return torrents[0]


def assert_torrent_metadata(torrent, seeding_days=None, ratio=None, tolerance=0.1):
    """
    Assert torrent has expected metadata with helpful error messages.

    Args:
        torrent: The torrent object
        seeding_days: Expected seeding days (optional)
        ratio: Expected ratio (optional)
        tolerance: Tolerance for ratio comparison (default 10%)
    """
    errors = []

    if seeding_days is not None:
        expected_seconds = seeding_days * 86400
        actual_seconds = torrent.seeding_time

        if actual_seconds < expected_seconds * (1 - tolerance):
            errors.append(
                f"Seeding time too low: expected ~{seeding_days}d "
                f"({expected_seconds}s), got {actual_seconds}s "
                f"({actual_seconds / 86400:.1f}d)"
            )

    if ratio is not None:
        actual_ratio = torrent.ratio

        if actual_ratio < ratio * (1 - tolerance):
            errors.append(
                f"Ratio too low: expected ~{ratio}, got {actual_ratio}"
            )

    if errors:
        error_msg = f"Torrent metadata assertion failed for {torrent.name}:"
        for err in errors:
            error_msg += f"\n  - {err}"
        error_msg += f"\n\nActual torrent state:"
        error_msg += f"\n  Name: {torrent.name}"
        error_msg += f"\n  Hash: {torrent.hash}"
        error_msg += f"\n  State: {torrent.state}"
        error_msg += f"\n  Seeding time: {torrent.seeding_time}s ({torrent.seeding_time / 86400:.1f}d)"
        error_msg += f"\n  Ratio: {torrent.ratio}"
        error_msg += f"\n  Uploaded: {torrent.uploaded}"
        error_msg += f"\n  Downloaded: {torrent.downloaded}"
        error_msg += f"\n  Save path: {torrent.save_path}"

        raise AssertionError(error_msg)
