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
