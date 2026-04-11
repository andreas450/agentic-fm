#!/usr/bin/env python3
"""
clipboard_win.py -- FileMaker clipboard read/write for Windows via ctypes.

Works two ways:
  - Called directly by Windows Python (VS Code native on Windows)
  - Called via WSL interop: python.exe clipboard_win.py <command> <args>

Usage:
    Discover FM clipboard formats (run after Ctrl+C in FM Script Workspace):
        python clipboard_win.py discover

    Write XML to clipboard (class auto-detected):
        python clipboard_win.py write agent/sandbox/myscript.xml

    Write with explicit class override:
        python clipboard_win.py write agent/sandbox/myscript.xml --class XMSC

    Read FM objects from clipboard to file:
        python clipboard_win.py read agent/sandbox/output.xml
"""

import argparse
import ctypes
import ctypes.wintypes
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------------------
# Windows API — module-level references allow monkeypatching in tests
# ---------------------------------------------------------------------------

if sys.platform == 'win32':
    _user32 = ctypes.windll.user32    # type: ignore[attr-defined]
    _kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
else:
    # Non-Windows: set to None so the module is importable for testing.
    # Tests replace these via monkeypatch before calling any function.
    _user32 = None   # type: ignore[assignment]
    _kernel32 = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GMEM_MOVEABLE = 0x0002

FM_CLASSES = {
    'XMSS': 'Script Steps',
    'XMSC': 'Script',
    'XML2': 'Layout Objects',
    'XMLO': 'Layout Objects (legacy)',
    'XMFD': 'Field Definition',
    'XMFN': 'Custom Function',
    'XMTB': 'Table',
    'XMVL': 'Value List',
    'XMTH': 'Theme',
}

XML_ELEMENT_TO_CLASS = {
    'Step':           'XMSS',
    'Script':         'XMSC',
    'CustomFunction': 'XMFN',
    'Field':          'XMFD',
    'BaseTable':      'XMTB',
    'ValueList':      'XMVL',
    'Layout':         'XML2',
    'Theme':          'XMTH',
    'CustomMenu':     'ut16',
    'CustomMenuSet':  'ut16',
}

UT16_CLASSES = {'ut16'}

# ---------------------------------------------------------------------------
# Class detection (mirrors clipboard.py logic — kept local to avoid import chain)
# ---------------------------------------------------------------------------

def detect_class_from_xml(xml_text: str) -> str:
    """Infer the FM clipboard class code from the XML element content."""
    try:
        root = ET.fromstring(xml_text)
        if len(root) > 0:
            cls = XML_ELEMENT_TO_CLASS.get(root[0].tag)
            if cls:
                return cls
    except ET.ParseError:
        pass
    # Fallback regex — check menu types before Step to avoid false match
    for element in ('CustomMenuSet', 'CustomMenu'):
        if re.search(rf'<{element}[\s>/]', xml_text):
            return 'ut16'
    for element, cls in XML_ELEMENT_TO_CLASS.items():
        if element in ('CustomMenuSet', 'CustomMenu'):
            continue
        if re.search(rf'<{element}[\s>/]', xml_text):
            return cls
    return 'XMSS'
