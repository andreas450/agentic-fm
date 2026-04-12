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


from unittest.mock import MagicMock, call
import subprocess


class TestCallWin:
    def _get_win_script_path(self):
        """Return the expected path to clipboard_win.py."""
        import clipboard
        import os
        return os.path.join(os.path.dirname(clipboard.__file__), 'clipboard_win.py')

    def test_on_windows_uses_sys_executable(self, monkeypatch):
        import clipboard
        monkeypatch.setattr(sys, 'platform', 'win32')

        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr(subprocess, 'run', mock_run)

        clipboard._call_win(['write', 'C:\\some\\file.xml'])

        call_args = mock_run.call_args[0][0]
        assert call_args[0] == sys.executable

    def test_on_windows_passes_args_unchanged(self, monkeypatch):
        import clipboard
        monkeypatch.setattr(sys, 'platform', 'win32')

        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr(subprocess, 'run', mock_run)

        clipboard._call_win(['write', 'C:\\some\\file.xml'])

        call_args = mock_run.call_args[0][0]
        assert 'write' in call_args
        assert 'C:\\some\\file.xml' in call_args

    def test_on_wsl_uses_python_exe(self, monkeypatch):
        import clipboard
        monkeypatch.setattr(sys, 'platform', 'linux')
        monkeypatch.setattr(clipboard, '_is_wsl', lambda: True)

        def fake_check_output(cmd, **kw):
            if '-w' in cmd:
                path = cmd[-1]
                return f'C:\\wsl{path.replace("/", "\\")}\n'.encode()
            return b''

        monkeypatch.setattr(subprocess, 'check_output', fake_check_output)
        mock_run = MagicMock(return_value=MagicMock(returncode=0))
        monkeypatch.setattr(subprocess, 'run', mock_run)

        clipboard._call_win(['write', '/home/user/file.xml'])

        call_args = mock_run.call_args[0][0]
        assert call_args[0] == 'python.exe'

    def test_on_wsl_raises_clear_error_when_python_exe_not_found(self, monkeypatch):
        import clipboard
        monkeypatch.setattr(sys, 'platform', 'linux')
        monkeypatch.setattr(clipboard, '_is_wsl', lambda: True)

        def fake_check_output(cmd, **kw):
            if '-w' in cmd:
                return b'C:\\path\\clipboard_win.py\n'
            return b''
        monkeypatch.setattr(subprocess, 'check_output', fake_check_output)
        monkeypatch.setattr(subprocess, 'run', MagicMock(side_effect=FileNotFoundError))

        with pytest.raises(SystemExit):
            clipboard._call_win(['write', 'test.xml'])

    def test_on_wsl_converts_posix_paths_to_windows(self, monkeypatch):
        import clipboard
        monkeypatch.setattr(sys, 'platform', 'linux')
        monkeypatch.setattr(clipboard, '_is_wsl', lambda: True)

        converted = {}

        def fake_check_output(cmd, **kw):
            if '-w' in cmd:
                posix = cmd[-1]
                win = f'C:\\Users\\user\\{posix.split("/")[-1]}'
                converted[posix] = win
                return (win + '\n').encode()
            return b''

        monkeypatch.setattr(subprocess, 'check_output', fake_check_output)

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix='.xml', delete=False) as tf:
            tf_path = tf.name

        try:
            mock_run = MagicMock(return_value=MagicMock(returncode=0))
            monkeypatch.setattr(subprocess, 'run', mock_run)

            clipboard._call_win(['write', tf_path])

            call_args = mock_run.call_args[0][0]
            assert any('\\' in a for a in call_args)
        finally:
            os.unlink(tf_path)
