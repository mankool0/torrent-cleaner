"""Unit tests for Config class."""

import pytest
import os
from datetime import timedelta
from src.config import Config


class TestParseDuration:
    """Test Config.parse_duration() method."""

    def test_parse_days(self):
        """Test parsing days format."""
        assert Config.parse_duration('30d') == timedelta(days=30)
        assert Config.parse_duration('1d') == timedelta(days=1)
        assert Config.parse_duration('365d') == timedelta(days=365)

    def test_parse_months(self):
        """Test parsing months format (30 days per month)."""
        assert Config.parse_duration('1m') == timedelta(days=30)
        assert Config.parse_duration('3m') == timedelta(days=90)
        assert Config.parse_duration('12m') == timedelta(days=360)

    def test_parse_years(self):
        """Test parsing years format (365 days per year)."""
        assert Config.parse_duration('1y') == timedelta(days=365)
        assert Config.parse_duration('2y') == timedelta(days=730)

    def test_parse_case_insensitive(self):
        """Test that parsing is case insensitive."""
        assert Config.parse_duration('30D') == timedelta(days=30)
        assert Config.parse_duration('3M') == timedelta(days=90)
        assert Config.parse_duration('1Y') == timedelta(days=365)

    def test_parse_with_whitespace(self):
        """Test parsing with leading/trailing whitespace."""
        assert Config.parse_duration('  30d  ') == timedelta(days=30)
        assert Config.parse_duration('\n3m\t') == timedelta(days=90)

    def test_parse_empty_string(self):
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError, match="Duration string is empty"):
            Config.parse_duration('')
        with pytest.raises(ValueError, match="Duration string is empty"):
            Config.parse_duration('   ')

    def test_parse_invalid_unit(self):
        """Test that invalid units raise ValueError."""
        with pytest.raises(ValueError, match="Invalid duration unit"):
            Config.parse_duration('30x')
        with pytest.raises(ValueError, match="Invalid duration unit"):
            Config.parse_duration('30')
        with pytest.raises(ValueError, match="Invalid duration unit"):
            Config.parse_duration('30days')

    def test_parse_invalid_value(self):
        """Test that non-numeric values raise ValueError."""
        with pytest.raises(ValueError, match="Invalid duration value"):
            Config.parse_duration('abcd')
        with pytest.raises(ValueError, match="Invalid duration value"):
            Config.parse_duration('d')
        with pytest.raises(ValueError, match="Invalid duration value"):
            Config.parse_duration('12.5d')

    def test_parse_negative_value(self):
        """Test that negative values raise ValueError."""
        with pytest.raises(ValueError, match="Duration value must be positive"):
            Config.parse_duration('-30d')
        with pytest.raises(ValueError, match="Duration value must be positive"):
            Config.parse_duration('-1m')

    def test_parse_zero_value(self):
        """Test that zero is allowed."""
        assert Config.parse_duration('0d') == timedelta(days=0)
        assert Config.parse_duration('0m') == timedelta(days=0)
        assert Config.parse_duration('0y') == timedelta(days=0)


class TestConfigValidation:
    """Test Config validation and error handling."""

    def test_invalid_port_non_numeric(self, tmp_path, monkeypatch):
        """Test that non-numeric QBITTORRENT_PORT raises ValueError."""
        monkeypatch.setenv('QBITTORRENT_HOST', 'localhost')
        monkeypatch.setenv('QBITTORRENT_PORT', 'abc')
        monkeypatch.setenv('QBITTORRENT_USERNAME', 'admin')
        monkeypatch.setenv('QBITTORRENT_PASSWORD', 'admin')
        monkeypatch.setenv('TORRENT_DIR', str(tmp_path))
        monkeypatch.setenv('MEDIA_LIBRARY_DIR', str(tmp_path))

        with pytest.raises(ValueError, match="QBITTORRENT_PORT must be an integer"):
            Config()

    def test_invalid_ratio_non_numeric(self, tmp_path, monkeypatch):
        """Test that non-numeric MIN_RATIO raises ValueError."""
        monkeypatch.setenv('QBITTORRENT_HOST', 'localhost')
        monkeypatch.setenv('QBITTORRENT_USERNAME', 'admin')
        monkeypatch.setenv('QBITTORRENT_PASSWORD', 'admin')
        monkeypatch.setenv('TORRENT_DIR', str(tmp_path))
        monkeypatch.setenv('MEDIA_LIBRARY_DIR', str(tmp_path))
        monkeypatch.setenv('MIN_RATIO', 'high')

        with pytest.raises(ValueError, match="MIN_RATIO must be a number"):
            Config()

    def test_missing_required_env_var_message(self, monkeypatch):
        """Test that missing required var error mentions the key name."""
        monkeypatch.delenv('QBITTORRENT_HOST', raising=False)

        with pytest.raises(ValueError, match="QBITTORRENT_HOST"):
            Config()

    def test_data_dir_validation(self, tmp_path, monkeypatch):
        """Test that unwritable DATA_DIR raises ValueError."""
        monkeypatch.setenv('QBITTORRENT_HOST', 'localhost')
        monkeypatch.setenv('QBITTORRENT_USERNAME', 'admin')
        monkeypatch.setenv('QBITTORRENT_PASSWORD', 'admin')
        monkeypatch.setenv('TORRENT_DIR', str(tmp_path))
        monkeypatch.setenv('MEDIA_LIBRARY_DIR', str(tmp_path))

        # Use a path under /proc which can't be created
        monkeypatch.setenv('DATA_DIR', '/proc/fake_data_dir')

        with pytest.raises(ValueError, match="Cannot create data directory"):
            Config()
