"""Legacy Engine module alias, retaining public dispatcher and stdio entry."""
import sys
from studyflow.interfaces.engine import dispatcher as _implementation
from studyflow.interfaces.engine.stdio import main
_implementation.main = main
sys.modules[__name__] = _implementation
if __name__ == "__main__":
    main()
