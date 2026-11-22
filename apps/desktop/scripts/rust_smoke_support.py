"""Utilities for isolated native desktop smoke tests. The Rust CLI owns data writes."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.request import urlopen
import uuid

import psutil
from playwright.sync_api import Error as PlaywrightError


def isolated_env(workspace: Path) -> dict[str, str]:
    env = {name: value for name, value in os.environ.items() if not name.startswith(("STUDYFLOW_", "WEBVIEW2_"))}
    env["STUDYFLOW_WORKSPACE"] = str(workspace)
    return env


class NativeCli:
    def __init__(self, desktop: Path, workspace: Path, evidence: Path, *, record_receipts: bool = False):
        self.executable = desktop.parent / "binaries/studyflow.exe"
        self.workspace = workspace
        self.evidence = evidence
        self.env = isolated_env(workspace)
        self.count = 0
        self.record_receipts = record_receipts
        self.receipts: list[dict] = []

    def command(self, *args) -> dict:
        process = subprocess.run([str(self.executable), *map(str, args), "--format", "json"],
                                 cwd=self.workspace, env=self.env, capture_output=True, encoding="utf-8", timeout=60)
        assert process.returncode == 0, (args, process.returncode, process.stdout, process.stderr)
        body = json.loads(process.stdout)
        assert body["ok"], (args, body)
        if self.record_receipts:
            self.receipts.append({"args": list(map(str, args)), "exit_code": process.returncode, "response": body.copy()})
        return body

    def call(self, method: str, params: dict | None = None) -> dict:
        self.count += 1
        path = self.evidence / f"request-{self.count:03d}.json"
        path.write_text(json.dumps(params or {}, ensure_ascii=False), encoding="utf-8")
        result = self.command("call", "--method", method, "--file", path)
        result.pop("ok")
        return result


@contextmanager
def launch(desktop: Path, workspace: Path, evidence: Path, *, runtime: Path | None = None):
    runtime = runtime or evidence / f"native-{uuid.uuid4().hex[:8]}"
    runtime.mkdir(exist_ok=True)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = isolated_env(workspace)
    env.update(
        STUDYFLOW_WINDOW_STATE_DIR=str(runtime / "window-state"),
        STUDYFLOW_DIAGNOSTICS_DIR=str(runtime / "diagnostics"),
        WEBVIEW2_USER_DATA_FOLDER=str(runtime / "webview"),
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f"--remote-debugging-port={port} --remote-debugging-address=127.0.0.1",
        TEMP=str(runtime), TMP=str(runtime),
    )
    endpoint = f"http://127.0.0.1:{port}"
    with (runtime / "desktop.log").open("ab") as log:
        process = subprocess.Popen([str(desktop)], cwd=workspace, env=env, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"StudyFlow exited before WebView2 attached: {process.returncode}")
                try:
                    with urlopen(endpoint + "/json/version", timeout=0.5):
                        break
                except OSError:
                    time.sleep(0.15)
            else:
                raise TimeoutError("WebView2 did not expose its local test endpoint")
            yield endpoint, process
        finally:
            if process.poll() is None:
                children = psutil.Process(process.pid).children(recursive=True)
                process.terminate()
                process.wait(timeout=10)
                for child in children:
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass


def window(browser, label="main"):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        for context in browser.contexts:
            for page in context.pages:
                if page.is_closed():
                    continue
                try:
                    actual = page.evaluate("window.__TAURI_INTERNALS__?.metadata?.currentWindow?.label")
                except PlaywrightError as error:
                    if "Execution context was destroyed" not in str(error):
                        raise
                    continue
                if actual == label:
                    return page
        time.sleep(0.1)
    raise TimeoutError(f"Tauri webview not found: {label}")
