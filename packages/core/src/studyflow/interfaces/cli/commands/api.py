"""A neutral JSON-file CLI transport for all versioned Engine capabilities."""
import json
from pathlib import Path
import typer
from ..registry import app
from ..runtime import output
from studyflow.interfaces.engine.dispatcher import StudyFlowEngine
from studyflow.shared.domain import DomainError

@app.command("call")
def call(method: str=typer.Option(...,"--method"),file:Path|None=typer.Option(None,"--file"),format:str=typer.Option("json","--format")):
    engine=None
    read_only=True
    try:
        if file and file.stat().st_size>4*1024*1024:
            raise DomainError("INVALID_ARGUMENT", "JSON请求超过4MiB。")
        try:
            params=json.loads(file.read_text(encoding="utf-8-sig")) if file else {}
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise DomainError("INVALID_ARGUMENT", "call请求必须是有效的UTF-8 JSON。") from exc
        if not isinstance(params, dict):
            raise DomainError("INVALID_ARGUMENT", "call请求参数必须是JSON对象。")
        if method=="system.schema":
            from studyflow.interfaces.engine.schemas import schemas
            output({"ok":True,**schemas(params.get("method"))},format)
            return
        from studyflow.config import Settings
        from studyflow.interfaces.engine.protocol import all_capabilities, version_payload, capabilities_payload
        from studyflow.interfaces.engine.schemas import validate
        if method in {"system.version", "system.capabilities"}:
            payload = version_payload if method == "system.version" else capabilities_payload
            output({"ok": True, **payload(Settings.from_env())}, format)
            return
        if method == "system.doctor":
            from .system import doctor
            doctor(format=format)
            return
        kinds = {item["method"]: item["kind"] for item in all_capabilities()}
        if method not in kinds:
            raise DomainError("METHOD_NOT_FOUND", f"未知Engine方法：{method}", "先读取capabilities。")
        validate(method, params)
        read_only = kinds[method] == "read"
        engine=StudyFlowEngine(read_only=read_only)
        response=engine.handle({"id":"cli","method":method,"params":params})
        output({"ok":True,**response["data"]} if response["ok"] else {"ok":False,**response["error"]},format)
        if not response["ok"]:raise typer.Exit(1)
    except typer.Exit:raise
    except Exception as exc:
        from ..runtime import fail
        fail(exc, read_only=read_only)
    finally:
        if engine:engine.close()
