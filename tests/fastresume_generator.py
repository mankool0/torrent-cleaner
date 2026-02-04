"""Generate qBittorrent fastresume files for testing."""

import bencode
from pathlib import Path
import time
import hashlib


def calculate_info_hash(torrent_file_path: Path) -> str:
    """Calculate the info hash from a torrent file."""
    with open(torrent_file_path, 'rb') as f:
        torrent_data = bencode.decode(f.read())

    info_encoded = bencode.encode(torrent_data['info'])
    return hashlib.sha1(info_encoded).digest()


def generate_fastresume(
    torrent_file_path: Path,
    save_path: Path,
    seeding_days: int = 0,
    ratio: float = 0.0,
    output_path: Path = None
) -> Path:
    """
    Generate a qBittorrent fastresume file.

    Args:
        torrent_file_path: Path to the .torrent file
        save_path: Path where torrent data files are located
        seeding_days: Number of days torrent has been seeding
        ratio: Upload/download ratio
        output_path: Where to write the fastresume file

    Returns:
        Path to the generated fastresume file
    """
    with open(torrent_file_path, 'rb') as f:
        torrent_data = bencode.decode(f.read())

    info = torrent_data['info']

    if 'length' in info:
        # Single file torrent
        total_size = info['length']
        num_files = 1
    else:
        # Multi-file torrent
        total_size = sum(f['length'] for f in info['files'])
        num_files = len(info['files'])

    piece_length = info['piece length']
    num_pieces = (total_size + piece_length - 1) // piece_length

    total_downloaded = total_size  # Fully downloaded
    total_uploaded = int(total_size * ratio)

    # Calculate times
    seeding_time = seeding_days * 86400
    now = int(time.time())
    completed_time = now - seeding_time
    added_time = completed_time - 3600  # Added 1 hour before completion

    info_hash = calculate_info_hash(torrent_file_path)

    # Generate pieces string (all completed)
    pieces = b'\x01' * num_pieces

    # Build fastresume structure
    fastresume = {
        # Time tracking
        b'active_time': seeding_time,
        b'added_time': added_time,
        b'completed_time': completed_time,
        b'finished_time': seeding_time,
        b'seeding_time': seeding_time,
        b'last_seen_complete': now,
        b'last_upload': now,
        b'last_download': completed_time,

        # Upload/download stats
        b'total_uploaded': total_uploaded,
        b'total_downloaded': total_downloaded,

        # File info
        b'file-format': b'libtorrent resume file',
        b'file-version': 1,
        b'libtorrent-version': b'2.0.11.0',
        b'file_priority': [1] * num_files,

        # Torrent state
        b'info-hash': info_hash,
        b'pieces': pieces,
        b'piece_priority': b'\x01' * num_pieces,
        b'paused': 0,
        b'auto_managed': 1,
        b'seed_mode': 0,
        b'super_seeding': 0,
        b'sequential_download': 0,
        b'upload_mode': 0,

        # Rate limits
        b'download_rate_limit': -1,
        b'upload_rate_limit': -1,
        b'max_connections': -1,
        b'max_uploads': -1,

        # Tracker/DHT settings
        b'announce_to_dht': 1,
        b'announce_to_lsd': 1,
        b'announce_to_trackers': 1,
        b'disable_dht': 0,
        b'disable_lsd': 0,
        b'disable_pex': 0,
        b'apply_ip_filter': 1,

        # Standard Libtorrent save path
        b'save_path': str(save_path).encode('utf-8'),

        # qBittorrent specific
        b'qBt-savePath': str(save_path).encode('utf-8'),
        b'qBt-ratioLimit': -2,
        b'qBt-seedingTimeLimit': -2,
        b'qBt-category': b'',
        b'qBt-tags': [],
        b'qBt-name': info['name'].encode('utf-8') if isinstance(info['name'], str) else info['name'],
        b'qBt-seedStatus': 1,
        b'qBt-contentLayout': b'Original',
        b'qBt-hasRootFolder': 1 if not 'length' in info else 0,
        b'qBt-firstLastPiecePriority': 0,
        b'qBt-queuePosition': 0,

        # Allocation
        b'allocation': b'full',

        # Trackers from torrent file
        b'trackers': [[tracker.encode('utf-8') if isinstance(tracker, str) else tracker
                       for tracker in tier]
                      for tier in torrent_data.get('announce-list', [[torrent_data.get('announce', '')]])],

        # Misc
        b'httpseeds': [],
        b'url-list': [],
        b'peers': b'',
        b'peers6': b'',
        b'num_complete': 0,
        b'num_downloaded': 0,
        b'num_incomplete': 0,
        b'share_mode': 0,
        b'stop_when_ready': 0,
    }

    # Write fastresume file
    with open(output_path, 'wb') as f:
        f.write(bencode.encode(fastresume))

    return output_path


def setup_preseeded_torrent(
    torrent_file_path: Path,
    data_path: Path,
    bt_backup_dir: Path,
    seeding_days: int = 0,
    ratio: float = 0.0,
    docker_save_path: Path = None
) -> str:
    """
    Set up a torrent to appear as already seeding when qBittorrent starts.

    Args:
        torrent_file_path: Path to .torrent file
        data_path: Path to the data file or directory (host path)
        bt_backup_dir: Path to qBittorrent's BT_backup directory
        seeding_days: Days the torrent has been seeding
        ratio: Upload/download ratio
        docker_save_path: Path as seen by Docker container (e.g., /torrents)

    Returns:
        Torrent hash (lowercase hex string)
    """
    import shutil

    bt_backup_dir.mkdir(parents=True, exist_ok=True)

    info_hash = calculate_info_hash(torrent_file_path)
    torrent_hash = info_hash.hex()

    torrent_dest = bt_backup_dir / f'{torrent_hash}.torrent'
    shutil.copy(torrent_file_path, torrent_dest)

    fastresume_path = bt_backup_dir / f'{torrent_hash}.fastresume'

    if docker_save_path:
        save_path = docker_save_path
    else:
        save_path = data_path.parent if data_path.is_file() else data_path

    generate_fastresume(
        torrent_file_path=torrent_file_path,
        save_path=save_path,
        seeding_days=seeding_days,
        ratio=ratio,
        output_path=fastresume_path
    )

    return torrent_hash
