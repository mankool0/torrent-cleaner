"""Pytest fixtures for integration tests."""

import pytest
import subprocess
import time
import shutil
from pathlib import Path
from src.config import Config
import torf


@pytest.fixture(scope="session", autouse=True)
def docker_qbittorrent(tmp_path_factory):
    """Start qBittorrent Docker container before all tests."""
    # Create session-scoped temp directory (pytest auto-cleans this)
    test_data_dir = tmp_path_factory.mktemp("qbittorrent_test_data")

    # Create test data directories
    (test_data_dir / 'config').mkdir(exist_ok=True)
    (test_data_dir / 'downloads').mkdir(exist_ok=True)
    (test_data_dir / 'torrents').mkdir(exist_ok=True)
    (test_data_dir / 'media').mkdir(exist_ok=True)

    # Create qBittorrent config directory and copy pre-configured settings
    qbt_config_dir = test_data_dir / 'config' / 'qBittorrent'
    qbt_config_dir.mkdir(exist_ok=True)

    # Create config file with admin/adminadmin credentials
    config_content = """[LegalNotice]
Accepted=true

[Preferences]
WebUI\\Username=admin
WebUI\\Password_PBKDF2="@ByteArray(ARQ77eY1NUZaQsuDHbIMCA==:0WMRkYTUWVT9wVvdDtHAjU9b3b7uB8NR1Gur2hmQCvCDpm39Q+PsJRJPaCU51dEiz+dTzh8qbPsL8WkFljQYFQ==)"
"""
    (qbt_config_dir / 'qBittorrent.conf').write_text(config_content)

    # Start container with temp directory as volume
    import os
    os.environ['TEST_DATA_PATH'] = str(test_data_dir.absolute())

    # Use current user's UID/GID to avoid permission issues
    os.environ['PUID'] = str(os.getuid())
    os.environ['PGID'] = str(os.getgid())

    subprocess.run(
        ['docker', 'compose', '-f', 'docker-compose.test.yml', 'up', '-d'],
        check=True
    )

    # Wait for container to be healthy
    print("\nWaiting for qBittorrent to start...")
    max_wait = 60
    for i in range(max_wait):
        try:
            result = subprocess.run(
                ['docker', 'inspect', '--format={{.State.Health.Status}}', 'qbittorrent-test'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and 'healthy' in result.stdout:
                print("qBittorrent is ready!")
                break
        except:
            pass
        time.sleep(1)
    else:
        raise RuntimeError("qBittorrent failed to start within timeout")

    # Additional wait for API to be fully ready
    # TODO: Add a check that API is responsive instead of fixed sleep
    time.sleep(5)

    # Store test_data_dir for other fixtures
    docker_qbittorrent._test_data_dir = test_data_dir

    yield test_data_dir

    # Cleanup
    subprocess.run(
        ['docker', 'compose', '-f', 'docker-compose.test.yml', 'down', '-v'],
        check=True
    )

    # pytest auto-cleans tmp_path_factory directories


@pytest.fixture
def qb_client(docker_qbittorrent, monkeypatch, request):
    """
    Authenticated qBittorrent client with auto-cleanup and path translation.

    Automatically translates container paths (/data/torrents) to host paths
    when tests access torrent info.
    """
    from src.qbittorrent_client import QBittorrentClient
    import os

    qb_host = os.getenv('QBITTORRENT_HOST', 'localhost')
    qb_port = int(os.getenv('QBITTORRENT_PORT', '8080'))

    # Retry connection a few times in case API is not ready
    for attempt in range(5):
        try:
            client = QBittorrentClient(
                host=qb_host,
                port=qb_port,
                username='admin',
                password='adminadmin'
            )
            break
        except:
            if attempt == 4:
                raise RuntimeError("Failed to authenticate with qBittorrent")
            time.sleep(2)

    # Apply path translation patch
    # Get test_dirs if available (it won't be for some fixtures that run before test_dirs)
    test_dirs = None
    try:
        test_dirs = request.getfixturevalue('test_dirs')
    except:
        pass

    if test_dirs:
        original_torrents_info = client.torrents_info

        def patched_torrents_info(**kwargs):
            torrents = original_torrents_info(**kwargs)
            # Translate container paths to host paths
            for torrent in torrents:
                path_str = str(torrent.save_path)
                if path_str.startswith('/data/torrents'):
                    torrent.save_path = str(test_dirs['torrents'])
                elif path_str.startswith('/data/media'):
                    torrent.save_path = str(test_dirs['media'])
            return torrents

        monkeypatch.setattr(client, 'torrents_info', patched_torrents_info)

    yield client

    # Cleanup all torrents after each test
    try:
        for torrent in client.torrents_info():
            try:
                client.torrents_delete(
                    torrent_hashes=torrent.hash,
                    delete_files=True
                )
            except:
                pass
    except:
        pass

    try:
        client.close()
    except:
        pass


@pytest.fixture
def test_dirs(docker_qbittorrent, tmp_path):
    """Create test directory structure using Docker-mounted volumes."""
    # Use the session temp directory that Docker has mounted
    test_data_root = docker_qbittorrent
    torrents_dir = test_data_root / 'torrents'
    media_dir = test_data_root / 'media'

    # Ensure directories exist
    torrents_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)

    # Clean up from previous test
    for f in torrents_dir.glob('*'):
        if f.is_file():
            f.unlink()
        elif f.is_dir():
            shutil.rmtree(f)

    for f in media_dir.glob('*'):
        if f.is_file():
            f.unlink()
        elif f.is_dir():
            shutil.rmtree(f)

    return {
        'torrents': torrents_dir,
        'media': media_dir,
        'root': tmp_path
    }


@pytest.fixture
def torrent_creator(test_dirs):
    """Helper to create test torrents."""
    def create(name, content=b'test content', size_mb=None, multi_file=False):
        """
        Create test file(s) and torrent.

        Args:
            name: Name of the torrent/file
            content: File content (for single file)
            size_mb: Size in MB (overrides content)
            multi_file: Create multi-file torrent

        Returns:
            Dictionary with file/directory paths and torrent file path
        """
        if multi_file:
            # Create directory with multiple files
            torrent_dir = test_dirs['torrents'] / name
            torrent_dir.mkdir(exist_ok=True)

            # Main media file (large)
            main_file = torrent_dir / f"{name}.mkv"
            main_file.write_bytes(b'M' * (100 * 1024 * 1024))  # 100MB

            # Subtitle file
            srt_file = torrent_dir / f"{name}.srt"
            srt_file.write_bytes(b'1\n00:00:00 --> 00:00:02\nTest subtitle\n')

            # NFO/Info file
            nfo_file = torrent_dir / f"{name}.nfo"
            nfo_file.write_bytes(b'Release info\nCodec: x264\n')

            # Sample file (small media)
            sample_file = torrent_dir / "sample.mkv"
            sample_file.write_bytes(b'S' * (5 * 1024 * 1024))  # 5MB

            # Create torrent from directory
            torrent = torf.Torrent(
                path=str(torrent_dir),
                name=name,
                trackers=[['http://tracker.example.com:80/announce']],
                private=True,
                piece_size=16384
            )
            torrent.generate()

            torrent_file = test_dirs['root'] / f"{name}.torrent"
            torrent.write(str(torrent_file))

            return {
                'dir': torrent_dir,
                'files': {
                    'main': main_file,
                    'subtitle': srt_file,
                    'nfo': nfo_file,
                    'sample': sample_file
                },
                'torrent': torrent_file
            }
        else:
            # Single file torrent
            test_file = test_dirs['torrents'] / name

            if size_mb:
                test_file.write_bytes(b'\x00' * (size_mb * 1024 * 1024))
            else:
                test_file.write_bytes(content)

            torrent = torf.Torrent(
                path=str(test_file),
                name=name,
                trackers=[['http://tracker.example.com:80/announce']],
                private=True,
                piece_size=16384
            )
            torrent.generate()

            torrent_file = test_dirs['root'] / f"{name}.torrent"
            torrent.write(str(torrent_file))

            return {
                'file': test_file,
                'torrent': torrent_file,
                'content': content
            }

    return create


@pytest.fixture
def preseeded_torrent(docker_qbittorrent, torrent_creator, qb_client):
    """
    Helper to create torrents that appear as already seeding.

    This creates the torrent, generates fastresume files, and restarts
    qBittorrent so it loads the pre-seeded state.
    """
    from tests.fastresume_generator import setup_preseeded_torrent
    import subprocess

    def create_preseeded(name, content=b'test', size_mb=None, seeding_days=0, ratio=0.0, multi_file=False):
        # Create torrent using torrent_creator
        torrent_data = torrent_creator(name, content=content, size_mb=size_mb, multi_file=multi_file)

        bt_backup_dir = docker_qbittorrent / 'config' / 'qBittorrent' / 'BT_backup'
        docker_save_path = Path('/data/torrents')

        data_path = torrent_data.get('dir') or torrent_data.get('file')
        torrent_hash = setup_preseeded_torrent(
            torrent_file_path=torrent_data['torrent'],
            data_path=data_path,
            bt_backup_dir=bt_backup_dir,
            seeding_days=seeding_days,
            ratio=ratio,
            docker_save_path=docker_save_path
        )

        # Restart qBittorrent to load the new torrent
        subprocess.run(
            ['docker', 'restart', 'qbittorrent-test'],
            check=True,
            capture_output=True
        )
        time.sleep(10)  # Wait for restart, TODO: Improve this with health check

        # Reconnect client
        qb_client.auth_log_in()

        return {
            **torrent_data,
            'hash': torrent_hash
        }

    return create_preseeded


@pytest.fixture
def incomplete_torrent(qb_client, test_dirs):
    """
    Helper to create incomplete (0% downloaded) paused torrents.

    Creates a torrent file without the corresponding data file,
    then adds it to qBittorrent in a paused state. This simulates
    a torrent that hasn't started downloading yet.
    """
    import hashlib
    import bencode

    def create_incomplete(name, size_mb=1):
        """
        Create a torrent that's incomplete (0% downloaded, paused).

        Args:
            name: Name of the torrent/file
            size_mb: Size in MB

        Returns:
            Dictionary with torrent info and hash
        """
        # Create the data file temporarily to generate .torrent
        temp_file = test_dirs['torrents'] / name
        temp_file.write_bytes(b'\x00' * (size_mb * 1024 * 1024))

        # Generate .torrent file
        torrent = torf.Torrent(
            path=str(temp_file),
            name=name,
            trackers=[['http://tracker.example.com:80/announce']],
            private=True,
            piece_size=16384
        )
        torrent.generate()
        torrent_file = test_dirs['root'] / f"{name}.torrent"
        torrent.write(str(torrent_file))

        # Calculate torrent hash before deleting file
        with open(torrent_file, 'rb') as f:
            torrent_dict = bencode.decode(f.read())
            torrent_hash = hashlib.sha1(
                bencode.encode(torrent_dict['info'])
            ).hexdigest()

        # Delete the data file (makes it incomplete)
        temp_file.unlink()

        # Add torrent to qBittorrent in paused state
        qb_client.torrents_add(
            torrent_files=str(torrent_file),
            save_path=str(test_dirs['torrents']),
            is_paused=True
        )

        time.sleep(2)  # Wait for qBittorrent to process, TODO: Improve with check

        return {
            'name': name,
            'hash': torrent_hash,
            'torrent': torrent_file,
            'expected_path': test_dirs['torrents'] / name,
            'size_mb': size_mb
        }

    return create_incomplete
