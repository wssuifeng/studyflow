"""Compatibility alias for the optional development Web adapter."""
import sys
from studyflow.interfaces.web_compat import app as _implementation
sys.modules[__name__] = _implementation
