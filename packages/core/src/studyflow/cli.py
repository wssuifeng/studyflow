"""Legacy CLI module alias; preserves service override and discovery hooks."""
import sys
from studyflow.interfaces.cli import runtime as _implementation
sys.modules[__name__] = _implementation
if __name__ == "__main__":
    _implementation.app()
