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


# ---------------------------------------------------------------------------
# Low-level clipboard I/O
# ---------------------------------------------------------------------------

def _write_bytes_to_clipboard(format_id: int, data: bytes) -> None:
    """Write raw bytes to the Windows clipboard under the given format ID."""
    h_mem = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h_mem:
        _fail(f"GlobalAlloc failed (error {_last_error()})")

    ptr = _kernel32.GlobalLock(h_mem)
    if not ptr:
        _kernel32.GlobalFree(h_mem)
        _fail(f"GlobalLock failed (error {_last_error()})")

    ctypes.memmove(ptr, data, len(data))
    _kernel32.GlobalUnlock(h_mem)

    # Retry once if clipboard is locked by another process
    if not _user32.OpenClipboard(None):
        time.sleep(0.1)
        if not _user32.OpenClipboard(None):
            _kernel32.GlobalFree(h_mem)
            _fail(f"OpenClipboard failed (error {_last_error()}) — clipboard may be locked by another app")

    windows_owns_mem = False
    try:
        _user32.EmptyClipboard()
        result = _user32.SetClipboardData(format_id, h_mem)
        if not result:
            _fail(f"SetClipboardData failed (error {_last_error()})")
        windows_owns_mem = True
    finally:
        _user32.CloseClipboard()
        if not windows_owns_mem:
            _kernel32.GlobalFree(h_mem)


def _last_error() -> int:
    """Return the last Windows error code, or 0 on non-Windows."""
    if sys.platform == 'win32':
        return ctypes.get_last_error()  # type: ignore[attr-defined]
    return 0


def _fail(msg: str) -> None:
    """Print error to stderr and exit with code 1."""
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def _decode_file(raw_bytes: bytes) -> str:
    """Decode file bytes, honouring a UTF-16 BOM if present."""
    if raw_bytes[:2] in (b'\xff\xfe', b'\xfe\xff'):
        return raw_bytes.decode('utf-16')
    return raw_bytes.decode('utf-8', errors='replace')


# ---------------------------------------------------------------------------
# Write command
# ---------------------------------------------------------------------------

def write_to_clipboard(input_path: str, cls: str | None = None) -> None:
    """Write an fmxmlsnippet XML file to the Windows clipboard as FM objects."""
    with open(input_path, 'rb') as f:
        raw_bytes = f.read()

    xml_text = _decode_file(raw_bytes)

    if cls is None:
        cls = detect_class_from_xml(xml_text)

    cls = cls.lower() if cls.lower() in UT16_CLASSES else cls.upper()

    if cls in UT16_CLASSES:
        _write_ut16_to_clipboard(xml_text, input_path)
        return

    if cls not in FM_CLASSES:
        _fail(f"Unknown class '{cls}'. Valid options: {', '.join(FM_CLASSES)}")

    format_id = _user32.RegisterClipboardFormatW(cls)
    if not format_id:
        _fail(f"RegisterClipboardFormat('{cls}') failed (error {_last_error()})")

    _write_bytes_to_clipboard(format_id, raw_bytes)
    print(f"Clipboard ready → {input_path} as {cls} ({FM_CLASSES[cls]})", file=sys.stderr)


def _write_ut16_to_clipboard(xml_text: str, input_path: str) -> None:
    """Write a menu XML string to the clipboard as UTF-16 Unicode text."""
    # Strip XML declaration — FileMaker expects a clean UTF-16 payload
    xml_text = re.sub(r'<\?xml[^?]*\?>\s*', '', xml_text, count=1)
    utf16_bytes = xml_text.encode('utf-16')  # includes BOM automatically

    format_id = _user32.RegisterClipboardFormatW('ut16')
    if not format_id:
        _fail(f"RegisterClipboardFormat('ut16') failed (error {_last_error()})")

    _write_bytes_to_clipboard(format_id, utf16_bytes)
    print(f"Clipboard ready → {input_path} as ut16 (Menu)", file=sys.stderr)


# ---------------------------------------------------------------------------
# Read command
# ---------------------------------------------------------------------------

def _read_bytes_from_clipboard(format_id: int) -> bytes:
    """Read raw bytes for a given format ID from the Windows clipboard."""
    if not _user32.OpenClipboard(None):
        _fail(f"OpenClipboard failed (error {_last_error()}) — clipboard may be locked")

    try:
        h_mem = _user32.GetClipboardData(format_id)
        if not h_mem:
            _fail("No data for the requested clipboard format")

        size = _kernel32.GlobalSize(h_mem)
        ptr = _kernel32.GlobalLock(h_mem)
        if not ptr:
            _fail(f"GlobalLock failed (error {_last_error()})")

        try:
            data = ctypes.string_at(ptr, size)
        finally:
            _kernel32.GlobalUnlock(h_mem)

        return data
    finally:
        _user32.CloseClipboard()


def _detect_fm_format_on_clipboard() -> tuple | None:
    """Enumerate clipboard formats and return (format_id, class_code) for the first FM format found."""
    if not _user32.OpenClipboard(None):
        _fail(f"OpenClipboard failed (error {_last_error()})")

    try:
        fmt = _user32.EnumClipboardFormats(0)
        while fmt:
            name_buf = ctypes.create_unicode_buffer(256)
            _user32.GetClipboardFormatNameW(fmt, name_buf, 256)
            name = name_buf.value
            if name in FM_CLASSES or name in UT16_CLASSES:
                return fmt, name
            fmt = _user32.EnumClipboardFormats(fmt)
    finally:
        _user32.CloseClipboard()

    return None


def read_from_clipboard(output_path: str) -> None:
    """Read FM objects from the Windows clipboard and save as XML."""
    found = _detect_fm_format_on_clipboard()
    if not found:
        _fail("No FileMaker objects found on clipboard. "
              "Copy a script or object in FileMaker first (Ctrl+A, Ctrl+C).")

    format_id, cls = found
    data = _read_bytes_from_clipboard(format_id)

    if cls in UT16_CLASSES:
        xml = data.decode('utf-16')
    else:
        xml = data.decode('utf-8', errors='replace')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(xml)

    label = FM_CLASSES.get(cls, cls)
    print(f"Saved {cls} ({label}) to {output_path}", file=sys.stderr)
