# tests/test_clipboard_win.py
import pytest
import sys
import ctypes
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Class detection
# ---------------------------------------------------------------------------

class TestDetectClassFromXml:
    def setup_method(self):
        import clipboard_win
        self.detect = clipboard_win.detect_class_from_xml

    def test_step_element_returns_xmss(self):
        xml = '<fmxmlsnippet type="FMObjectList"><Step id="89"/></fmxmlsnippet>'
        assert self.detect(xml) == 'XMSS'

    def test_script_element_returns_xmsc(self):
        xml = '<fmxmlsnippet type="FMObjectList"><Script name="Test"/></fmxmlsnippet>'
        assert self.detect(xml) == 'XMSC'

    def test_custom_function_returns_xmfn(self):
        xml = '<fmxmlsnippet><CustomFunction name="Foo"/></fmxmlsnippet>'
        assert self.detect(xml) == 'XMFN'

    def test_field_returns_xmfd(self):
        xml = '<fmxmlsnippet><Field name="ID"/></fmxmlsnippet>'
        assert self.detect(xml) == 'XMFD'

    def test_base_table_returns_xmtb(self):
        xml = '<fmxmlsnippet><BaseTable name="Orders"/></fmxmlsnippet>'
        assert self.detect(xml) == 'XMTB'

    def test_value_list_returns_xmvl(self):
        xml = '<fmxmlsnippet><ValueList name="Status"/></fmxmlsnippet>'
        assert self.detect(xml) == 'XMVL'

    def test_custom_menu_returns_ut16(self):
        xml = '<fmxmlsnippet><CustomMenu name="MyMenu"/></fmxmlsnippet>'
        assert self.detect(xml) == 'ut16'

    def test_custom_menu_set_returns_ut16(self):
        xml = '<fmxmlsnippet><CustomMenuSet name="MySet"/></fmxmlsnippet>'
        assert self.detect(xml) == 'ut16'

    def test_unknown_element_defaults_to_xmss(self):
        xml = '<fmxmlsnippet><Unknown/></fmxmlsnippet>'
        assert self.detect(xml) == 'XMSS'

    def test_explicit_class_override_used_directly(self):
        # detect_class_from_xml always returns from XML — caller passes --class override
        # This test confirms the function itself doesn't read an override flag
        xml = '<fmxmlsnippet><Step/></fmxmlsnippet>'
        assert self.detect(xml) == 'XMSS'


# ---------------------------------------------------------------------------
# Shared fixture for mocking Windows API
# ---------------------------------------------------------------------------

@pytest.fixture
def win_api(monkeypatch):
    """Replace module-level _user32 and _kernel32 with mocks."""
    import clipboard_win

    u32 = MagicMock()
    k32 = MagicMock()

    u32.RegisterClipboardFormatW.return_value = 0xC123
    u32.OpenClipboard.return_value = 1
    u32.EmptyClipboard.return_value = 1
    u32.SetClipboardData.return_value = 0xABCD   # non-zero = success
    u32.CloseClipboard.return_value = 1

    k32.GlobalAlloc.return_value = 0xDEAD
    k32.GlobalLock.return_value = 0xBEEF
    k32.GlobalUnlock.return_value = 1

    monkeypatch.setattr(clipboard_win, '_user32', u32)
    monkeypatch.setattr(clipboard_win, '_kernel32', k32)
    monkeypatch.setattr(clipboard_win.ctypes, 'memmove', MagicMock())

    return {'u32': u32, 'k32': k32}


# ---------------------------------------------------------------------------
# Write command
# ---------------------------------------------------------------------------

class TestWriteToClipboard:
    def _make_xml_file(self, tmp_path, content=None):
        xml = content or '<fmxmlsnippet type="FMObjectList"><Step id="89"/></fmxmlsnippet>'
        f = tmp_path / 'test.xml'
        f.write_text(xml, encoding='utf-8')
        return str(f), xml

    def test_registers_correct_format_for_xmss(self, win_api, tmp_path):
        import clipboard_win
        path, _ = self._make_xml_file(tmp_path)
        clipboard_win.write_to_clipboard(path)
        win_api['u32'].RegisterClipboardFormatW.assert_called_once_with('XMSS')

    def test_registers_correct_format_for_xmsc(self, win_api, tmp_path):
        import clipboard_win
        xml = '<fmxmlsnippet><Script name="Test"/></fmxmlsnippet>'
        path, _ = self._make_xml_file(tmp_path, xml)
        clipboard_win.write_to_clipboard(path)
        win_api['u32'].RegisterClipboardFormatW.assert_called_once_with('XMSC')

    def test_explicit_class_overrides_auto_detect(self, win_api, tmp_path):
        import clipboard_win
        path, _ = self._make_xml_file(tmp_path)  # XMSS by content
        clipboard_win.write_to_clipboard(path, cls='XMSC')
        win_api['u32'].RegisterClipboardFormatW.assert_called_once_with('XMSC')

    def test_api_calls_in_correct_order(self, win_api, tmp_path):
        import clipboard_win
        path, _ = self._make_xml_file(tmp_path)

        call_log = []
        win_api['u32'].OpenClipboard.side_effect = lambda *a: call_log.append('open') or 1
        win_api['u32'].EmptyClipboard.side_effect = lambda: call_log.append('empty') or 1
        win_api['u32'].SetClipboardData.side_effect = lambda *a: call_log.append('set') or 0xABCD
        win_api['u32'].CloseClipboard.side_effect = lambda: call_log.append('close') or 1

        clipboard_win.write_to_clipboard(path)

        assert call_log == ['open', 'empty', 'set', 'close']

    def test_allocates_correct_byte_length(self, win_api, tmp_path):
        import clipboard_win
        path, xml = self._make_xml_file(tmp_path)
        clipboard_win.write_to_clipboard(path)
        expected_len = len(xml.encode('utf-8'))
        win_api['k32'].GlobalAlloc.assert_called_once_with(clipboard_win.GMEM_MOVEABLE, expected_len)

    def test_memmove_called_with_raw_utf8_bytes(self, win_api, tmp_path, monkeypatch):
        import clipboard_win
        path, xml = self._make_xml_file(tmp_path)
        expected = xml.encode('utf-8')

        captured = []
        monkeypatch.setattr(clipboard_win.ctypes, 'memmove',
                            lambda dst, src, n: captured.append((dst, src, n)))

        clipboard_win.write_to_clipboard(path)

        assert len(captured) == 1
        _dst, src, n = captured[0]
        assert src == expected
        assert n == len(expected)

    def test_close_clipboard_called_even_after_set_failure(self, win_api, tmp_path, monkeypatch):
        import clipboard_win
        monkeypatch.setattr(clipboard_win.ctypes, 'memmove', MagicMock())
        win_api['u32'].SetClipboardData.return_value = 0  # fail

        path, _ = self._make_xml_file(tmp_path)
        with pytest.raises(SystemExit):
            clipboard_win.write_to_clipboard(path)

        win_api['u32'].CloseClipboard.assert_called_once()
