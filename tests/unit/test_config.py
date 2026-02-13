"""Unit tests for Config class."""

import pytest
import os
from datetime import timedelta
from src.config import Config
from src.models import DeletionRule


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


class TestParseDeletionCriteria:
    """Test Config._parse_deletion_criteria() method."""

    def test_single_rule_both_conditions(self):
        """Test single rule with both duration and ratio."""
        rules = Config._parse_deletion_criteria('30d 2.0')
        assert len(rules) == 1
        assert rules[0].min_duration == '30d'
        assert rules[0].min_ratio == 2.0

    def test_single_rule_duration_only(self):
        """Test single rule with duration only."""
        rules = Config._parse_deletion_criteria('90d')
        assert len(rules) == 1
        assert rules[0].min_duration == '90d'
        assert rules[0].min_ratio is None

    def test_single_rule_ratio_only(self):
        """Test single rule with ratio only."""
        rules = Config._parse_deletion_criteria('0.5')
        assert len(rules) == 1
        assert rules[0].min_duration is None
        assert rules[0].min_ratio == 0.5

    def test_multiple_rules(self):
        """Test multiple rules separated by pipe."""
        rules = Config._parse_deletion_criteria('30d 2.0 | 10d 0.5 | 90d')
        assert len(rules) == 3
        assert rules[0] == DeletionRule(min_duration='30d', min_ratio=2.0)
        assert rules[1] == DeletionRule(min_duration='10d', min_ratio=0.5)
        assert rules[2] == DeletionRule(min_duration='90d', min_ratio=None)

    def test_whitespace_handling(self):
        """Test that extra whitespace is handled correctly."""
        rules = Config._parse_deletion_criteria('  30d   2.0  |  10d  ')
        assert len(rules) == 2
        assert rules[0].min_duration == '30d'
        assert rules[0].min_ratio == 2.0
        assert rules[1].min_duration == '10d'

    def test_ratio_order_independent(self):
        """Test that ratio can come before duration."""
        rules = Config._parse_deletion_criteria('2.0 30d')
        assert len(rules) == 1
        assert rules[0].min_duration == '30d'
        assert rules[0].min_ratio == 2.0

    def test_months_and_years(self):
        """Test duration with months and years."""
        rules = Config._parse_deletion_criteria('3m 1.0 | 1y')
        assert len(rules) == 2
        assert rules[0].min_duration == '3m'
        assert rules[0].min_ratio == 1.0
        assert rules[1].min_duration == '1y'

    def test_invalid_token_raises(self):
        """Test that an invalid token raises ValueError."""
        with pytest.raises(ValueError, match="Invalid token"):
            Config._parse_deletion_criteria('30d abc')

    def test_empty_string_raises(self):
        """Test that empty string raises ValueError."""
        with pytest.raises(ValueError, match="DELETION_CRITERIA cannot be empty"):
            Config._parse_deletion_criteria('')
        with pytest.raises(ValueError, match="DELETION_CRITERIA cannot be empty"):
            Config._parse_deletion_criteria('   ')

    def test_empty_rule_raises(self):
        """Test that empty rule (double pipe) raises ValueError."""
        with pytest.raises(ValueError, match="empty rule"):
            Config._parse_deletion_criteria('30d 2.0 | | 10d')

    def test_trailing_pipe_raises(self):
        """Test that trailing pipe raises ValueError."""
        with pytest.raises(ValueError, match="empty rule"):
            Config._parse_deletion_criteria('30d 2.0 |')

    def test_duplicate_duration_raises(self):
        """Test that duplicate duration in one rule raises ValueError."""
        with pytest.raises(ValueError, match="Duplicate duration"):
            Config._parse_deletion_criteria('30d 10d')

    def test_duplicate_ratio_raises(self):
        """Test that duplicate ratio in one rule raises ValueError."""
        with pytest.raises(ValueError, match="Duplicate ratio"):
            Config._parse_deletion_criteria('2.0 0.5')

    def test_negative_ratio_raises(self):
        """Test that negative ratio raises ValueError."""
        with pytest.raises(ValueError, match="Ratio must be >= 0"):
            Config._parse_deletion_criteria('-1.0')

    def test_invalid_duration_raises(self):
        """Test that invalid duration format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid duration value"):
            Config._parse_deletion_criteria('abcd')

    def test_zero_ratio(self):
        """Test that zero ratio is allowed."""
        rules = Config._parse_deletion_criteria('30d 0.0')
        assert rules[0].min_ratio == 0.0


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

    def test_invalid_deletion_criteria(self, tmp_path, monkeypatch):
        """Test that invalid DELETION_CRITERIA raises ValueError."""
        monkeypatch.setenv('QBITTORRENT_HOST', 'localhost')
        monkeypatch.setenv('QBITTORRENT_USERNAME', 'admin')
        monkeypatch.setenv('QBITTORRENT_PASSWORD', 'admin')
        monkeypatch.setenv('TORRENT_DIR', str(tmp_path))
        monkeypatch.setenv('MEDIA_LIBRARY_DIR', str(tmp_path))
        monkeypatch.setenv('DELETION_CRITERIA', 'garbage')

        with pytest.raises(ValueError, match="Invalid token"):
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
