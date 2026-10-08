"""One frozen Core, two process modes. No Python installation is required."""
import sys
from pathlib import Path

def run():
    cli_mode=Path(sys.executable).stem.lower()=="studyflow" or "--cli" in sys.argv[1:]
    if cli_mode:
        if "--cli" in sys.argv:sys.argv.remove("--cli")
        from studyflow.cli import app
        app(prog_name="studyflow")
    else:
        from studyflow.engine import main
        main()
if __name__=="__main__":run()
