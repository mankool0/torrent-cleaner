"""qBittorrent API client wrapper."""

import qbittorrentapi
from qbittorrentapi import Client
import logging


class QBittorrentClient:
    """Wrapper for qBittorrent Web API client."""

    def __init__(self, host: str, port: int, username: str, password: str):
        """
        Initialize qBittorrent client.

        Args:
            host: qBittorrent host address
            port: qBittorrent port
            username: qBittorrent username
            password: qBittorrent password
        """
        self.logger = logging.getLogger(__name__)
        self.host = host
        self.port = port

        try:
            self.client = Client(
                host=host,
                port=port,
                username=username,
                password=password,
            )
            self.client.auth_log_in()
            self.logger.info(f"Successfully connected to qBittorrent at {host}:{port}")
        except qbittorrentapi.LoginFailed as e:
            self.logger.error(f"Failed to login to qBittorrent: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Failed to connect to qBittorrent: {e}")
            raise

    def delete_torrent(self, torrent_hash: str, delete_files: bool = True, dry_run: bool = True) -> bool:
        """
        Delete torrent from qBittorrent.

        Args:
            torrent_hash: Torrent hash
            delete_files: Whether to delete files from disk
            dry_run: If True, don't actually delete

        Returns:
            True if successful (or dry_run), False otherwise
        """
        try:
            if dry_run:
                self.logger.info(f"[DRY RUN] Would delete torrent {torrent_hash} (delete_files={delete_files})")
                return True

            self.client.torrents_delete(
                torrent_hashes=torrent_hash,
                delete_files=delete_files
            )
            self.logger.info(f"Deleted torrent {torrent_hash} (delete_files={delete_files})")
            return True
        except Exception as e:
            self.logger.error(f"Failed to delete torrent {torrent_hash}: {e}")
            return False

    def pause_torrent(self, torrent_hash: str):
        """
        Pause a torrent.

        Args:
            torrent_hash: Torrent hash
        """
        try:
            self.client.torrents_pause(torrent_hashes=torrent_hash)
            self.logger.debug(f"Paused torrent: {torrent_hash}")
        except Exception as e:
            self.logger.error(f"Failed to pause torrent {torrent_hash}: {e}")
            raise

    def resume_torrent(self, torrent_hash: str):
        """
        Resume a torrent.

        Args:
            torrent_hash: Torrent hash
        """
        try:
            self.client.torrents_resume(torrent_hashes=torrent_hash)
            self.logger.debug(f"Resumed torrent: {torrent_hash}")
        except Exception as e:
            self.logger.error(f"Failed to resume torrent {torrent_hash}: {e}")
            raise

    def close(self):
        """Close the client connection."""
        try:
            self.client.auth_log_out()
            self.logger.debug("Logged out from qBittorrent")
        except Exception as e:
            self.logger.warning(f"Error during logout: {e}")

    # API-standard methods with logging and error handling

    def torrents_info(self, **kwargs) -> qbittorrentapi.TorrentInfoList:
        """
        Get torrents info from qBittorrent.

        Args:
            **kwargs: Optional filters (status, category, tag, hashes, etc.)
                     See qbittorrentapi documentation for available parameters.

        Returns:
            TorrentInfoList
        """
        try:
            torrents = self.client.torrents_info(**kwargs)
            self.logger.debug(f"Retrieved {len(torrents)} torrents from qBittorrent")
            return torrents
        except Exception as e:
            self.logger.error(f"Failed to get torrents: {e}")
            raise

    def torrents_files(self, torrent_hash: str) -> qbittorrentapi.TorrentFilesList:
        """
        Get list of files for a specific torrent.

        Args:
            torrent_hash: Torrent hash

        Returns:
            TorrentFilesList
        """
        try:
            files = self.client.torrents_files(torrent_hash=torrent_hash)
            return files
        except Exception as e:
            self.logger.error(f"Failed to get files for torrent {torrent_hash}: {e}")
            raise

    def torrents_trackers(self, torrent_hash: str) -> qbittorrentapi.TrackersList:
        """
        Get list of trackers for a specific torrent.

        Args:
            torrent_hash: Torrent hash

        Returns:
            TrackersList
        """
        try:
            trackers = self.client.torrents_trackers(torrent_hash=torrent_hash)
            return trackers
        except Exception as e:
            self.logger.error(f"Failed to get trackers for torrent {torrent_hash}: {e}")
            raise

    def torrents_add(self, **kwargs):
        """
        Add a torrent to qBittorrent.

        Passthrough to client.torrents_add() with same parameters.
        See qbittorrentapi documentation for available parameters.
        """
        return self.client.torrents_add(**kwargs)

    def torrents_delete(self, torrent_hashes, delete_files: bool = True):
        """
        Delete torrents from qBittorrent.

        WARNING: This is a passthrough to the raw API. For safer deletion
        with dry-run support, use delete_torrent() instead.

        Args:
            torrent_hashes: Torrent hash(es) to delete
            delete_files: Whether to delete files from disk
        """
        self.logger.warning(f"Direct torrents_delete called for {torrent_hashes}")
        return self.client.torrents_delete(
            torrent_hashes=torrent_hashes,
            delete_files=delete_files
        )

    def auth_log_in(self):
        """
        Log in to qBittorrent.

        Passthrough to client.auth_log_in().
        Note: This is called automatically in __init__
        """
        return self.client.auth_log_in()

    def auth_log_out(self):
        """
        Log out from qBittorrent.

        Passthrough to client.auth_log_out().
        Prefer using close() instead.
        """
        return self.client.auth_log_out()
