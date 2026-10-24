"""Test setup: make the ``tools`` package importable from the locator suite.

Kept additive: the existing contract/config tests do not import tools, and
nothing here changes pytest behavior for them.
"""

import sys
from pathlib import Path

LOCATOR_ROOT = Path(__file__).resolve().parents[1]
if str(LOCATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(LOCATOR_ROOT))
