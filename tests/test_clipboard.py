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


class TestDelegation:
    """Verify clipboard.py delegates to clipboard_win.py on Windows and WSL."""

    def _make_xml_file(self, tmp_path):
        xml = '<fmxmlsnippet type="FMObjectList"><Step id="89"/></fmxmlsnippet>'
        f = tmp_path / 'test.xml'
        f.write_text(xml, encoding='utf-8')
        return str(f)

    def test_write_delegates_on_windows(self, monkeypatch, tmp_path):
        import clipboard
        monkeypatch.setattr(sys, 'platform', 'win32')

        called = []
        monkeypatch.setattr(clipboard, '_call_win',
                            lambda args: called.append(args) or MagicMock(returncode=0, stdout='', stderr=''))

        clipboard.write_to_clipboard(self._make_xml_file(tmp_path))
        assert len(called) == 1
        assert called[0][0] == 'write'

    def test_write_delegates_on_wsl(self, monkeypatch, tmp_path):
        import clipboard
        monkeypatch.setattr(sys, 'platform', 'linux')
        monkeypatch.setattr(clipboard, '_is_wsl', lambda: True)

        called = []
        monkeypatch.setattr(clipboard, '_call_win',
                            lambda args: called.append(args) or MagicMock(returncode=0, stdout='', stderr=''))

        clipboard.write_to_clipboard(self._make_xml_file(tmp_path))
        assert len(called) == 1
        assert called[0][0] == 'write'

    def test_write_passes_class_arg_when_provided(self, monkeypatch, tmp_path):
        import clipboard
        monkeypatch.setattr(sys, 'platform', 'win32')

        called = []
        monkeypatch.setattr(clipboard, '_call_win',
                            lambda args: called.append(args) or MagicMock(returncode=0, stdout='', stderr=''))

        clipboard.write_to_clipboard(self._make_xml_file(tmp_path), cls='XMSC')
        assert '--class' in called[0]
        assert 'XMSC' in called[0]

    def test_write_exits_when_call_win_fails(self, monkeypatch, tmp_path):
        import clipboard
        monkeypatch.setattr(sys, 'platform', 'win32')
        monkeypatch.setattr(clipboard, '_call_win',
                            lambda args: MagicMock(returncode=1, stdout='', stderr='ERROR: test failure'))

        with pytest.raises(SystemExit):
            clipboard.write_to_clipboard(self._make_xml_file(tmp_path))

    def test_read_delegates_on_windows(self, monkeypatch, tmp_path):
        import clipboard
        monkeypatch.setattr(sys, 'platform', 'win32')

        called = []
        monkeypatch.setattr(clipboard, '_call_win',
                            lambda args: called.append(args) or MagicMock(returncode=0, stdout='', stderr=''))

        out = str(tmp_path / 'out.xml')
        clipboard.read_from_clipboard(out)
        assert len(called) == 1
        assert called[0][0] == 'read'

    def test_macos_path_not_affected(self, monkeypatch, tmp_path):
        import clipboard
        monkeypatch.setattr(sys, 'platform', 'darwin')
        monkeypatch.setattr(clipboard, '_is_wsl', lambda: False)

        call_win_called = []
        monkeypatch.setattr(clipboard, '_call_win',
                            lambda args: call_win_called.append(args))

        monkeypatch.setattr(clipboard, 'detect_class_from_xml', lambda x: 'XMSS')
        monkeypatch.setattr(clipboard, '_nspasteboard_write', lambda cls, data: True)
        monkeypatch.setattr(clipboard, '_HAS_APPKIT', True)

        clipboard.write_to_clipboard(self._make_xml_file(tmp_path))
        assert call_win_called == []
