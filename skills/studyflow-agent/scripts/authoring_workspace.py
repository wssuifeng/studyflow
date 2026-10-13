"""Run bounded authoring-material helpers; no StudyFlow database imports."""
import sys
sys.dont_write_bytecode = True
from authoring_support.cli import main
if __name__ == "__main__":
    raise SystemExit(main())
