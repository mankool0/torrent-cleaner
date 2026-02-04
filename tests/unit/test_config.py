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
