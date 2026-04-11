# tests/conftest.py
import sys
import os
import ctypes
from unittest.mock import MagicMock
import pytest

# Make agent/scripts importable in tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent', 'scripts'))

# ctypes.windll does not exist on Linux — mock it before any import of clipboard_win
if not hasattr(ctypes, 'windll'):
    ctypes.windll = MagicMock()


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "windows: mark test as requiring a live Windows environment"
    )


def pytest_collection_modifyitems(config, items):
    if sys.platform != 'win32':
        skip = pytest.mark.skip(reason="requires Windows")
        for item in items:
            if 'windows' in item.keywords:
                item.add_marker(skip)
