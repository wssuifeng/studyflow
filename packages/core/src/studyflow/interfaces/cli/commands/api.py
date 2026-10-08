"""A neutral JSON-file CLI transport for all versioned Engine capabilities."""
import json
from pathlib import Path
import typer
from ..registry import app
from ..runtime import output
from studyflow.interfaces.engine.dispatcher import StudyFlowEngine

@app.command("call")
def call(method: str=typer.Option(...,"--method"),file:Path|None=typer.Option(None,"--file"),format:str=typer.Option("json","--format")):
    engine=None
    try:
        if file and file.stat().st_size>4*1024*1024:raise ValueError("JSON请求超过4MiB")
        params=json.loads(file.read_text(encoding="utf-8-sig")) if file else {}
        if method=="system.schema":
            from studyflow.interfaces.engine.schemas import schemas
            output({"ok":True,**schemas(params.get("method"))},format)
            return
        engine=StudyFlowEngine()
        response=engine.handle({"id":"cli","method":method,"params":params})
        output({"ok":True,**response["data"]} if response["ok"] else {"ok":False,**response["error"]},format)
        if not response["ok"]:raise typer.Exit(1)
    except typer.Exit:raise
    except Exception as exc:
        from ..runtime import fail
        fail(exc)
    finally:
        if engine:engine.close()
