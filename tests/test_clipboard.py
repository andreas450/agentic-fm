# tests/test_clipboard.py
import sys
import pytest
from unittest.mock import patch, mock_open


class TestIsWsl:
    def test_returns_true_when_proc_version_contains_microsoft(self):
        import clipboard
        m = mock_open(read_data='Linux version 5.15.0-microsoft-standard-WSL2')
        with patch('builtins.open', m):
            assert clipboard._is_wsl() is True

    def test_returns_false_when_proc_version_does_not_contain_microsoft(self):
        import clipboard
        m = mock_open(read_data='Linux version 5.15.0-generic')
        with patch('builtins.open', m):
            assert clipboard._is_wsl() is False

    def test_returns_false_when_proc_version_missing(self):
        import clipboard
        with patch('builtins.open', side_effect=OSError):
            assert clipboard._is_wsl() is False

    def test_case_insensitive_microsoft_check(self):
        import clipboard
        m = mock_open(read_data='Linux version 5.15 Microsoft Corporation')
        with patch('builtins.open', m):
            assert clipboard._is_wsl() is True


class TestIsWindows:
    def test_returns_true_on_win32(self, monkeypatch):
        import clipboard
        monkeypatch.setattr(sys, 'platform', 'win32')
        assert clipboard._is_windows() is True

    def test_returns_false_on_linux(self, monkeypatch):
        import clipboard
        monkeypatch.setattr(sys, 'platform', 'linux')
        assert clipboard._is_windows() is False

    def test_returns_false_on_darwin(self, monkeypatch):
        import clipboard
        monkeypatch.setattr(sys, 'platform', 'darwin')
        assert clipboard._is_windows() is False
