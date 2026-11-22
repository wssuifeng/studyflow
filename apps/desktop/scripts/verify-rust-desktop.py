"""Observe a Windows Tauri/WebView2 binary and the native Engine it actually starts."""
from __future__ import annotations

import argparse
import asyncio
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen
import uuid

import psutil
from playwright.async_api import Error as PlaywrightError, async_playwright, expect

from rust_smoke_support import NativeCli


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("BuildTree", "Installed"), required=True)
    parser.add_argument("--desktop", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True, help="isolated synthetic workspace")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--stale-engine", type=Path, help="legacy path supplied only to confirm release ignores the override")
    parser.add_argument("--product-code", help="ProductCode from the tested MSI")
    parser.add_argument("--exercise-business-flows", action="store_true")
    options = parser.parse_args()
    if options.mode == "Installed" and not options.product_code:
        parser.error("Installed requires the MSI --product-code")
    if options.mode == "BuildTree" and (options.product_code or not options.manifest):
        parser.error("BuildTree requires --manifest and expects no MSI --product-code")
    return options


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_registered_product(desktop: Path, code: str) -> dict[str, str]:
    code = "{" + str(uuid.UUID(code)).upper() + "}"
    get_property = ctypes.WinDLL("msi").MsiGetProductInfoW
    get_property.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    get_property.restype = wintypes.UINT
    values = {}
    for prop in ("ProductName", "VersionString", "InstallLocation"):
        value = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(value))
        result = get_property(code, prop, value, ctypes.byref(size))
        if result or not value.value:
            raise RuntimeError(f"MSI registration did not provide {prop} for {code} (status {result})")
        values[prop] = value.value
    install_root = Path(values["InstallLocation"]).resolve(strict=True)
    if values["ProductName"] != "StudyFlow" or desktop.resolve() != install_root / "studyflow-desktop.exe":
        raise RuntimeError("DesktopPath does not match the Windows Installer registration for this StudyFlow product")
    return {"product_code": code, **values}


def assert_payload(options: argparse.Namespace, binaries: Path) -> dict[str, str]:
    if options.mode == "Installed" and options.manifest is None:
        paths = ["studyflow.exe", "studyflow-engine.exe", "studyflow-agent/SKILL.md"]
        return {path: sha(binaries / path) for path in paths}
    manifest = json.loads(options.manifest.read_text(encoding="utf-8-sig"))
    assert manifest["format"] == 1 and manifest["profile"] == "release"
    expected = manifest["files"]
    files = {entry.relative_to(binaries).as_posix() for entry in binaries.rglob("*") if entry.is_file()}
    assert files == expected.keys(), (files - expected.keys(), expected.keys() - files)
    assert all(sha(binaries / file) == digest for file, digest in expected.items())
    return expected


async def endpoint(process: subprocess.Popen, port: int) -> str:
    address = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Desktop exited before WebView2 attached: {process.returncode}")
        try:
            with urlopen(f"{address}/json/version", timeout=0.5) as response:
                json.load(response)
            return address
        except (TimeoutError, URLError):
            await asyncio.sleep(0.15)
    raise TimeoutError("WebView2 did not expose its local test endpoint")


async def main_window(browser):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        for context in browser.contexts:
            for page in context.pages:
                if page.is_closed():
                    continue
                try:
                    label = await page.evaluate("window.__TAURI_INTERNALS__?.metadata?.currentWindow?.label")
                except PlaywrightError as error:
                    if "Execution context was destroyed" not in str(error):
                        raise
                    continue
                if label == "main":
                    return page
        await asyncio.sleep(0.15)
    raise TimeoutError("StudyFlow main window not found")


async def exercise(options: argparse.Namespace, process: subprocess.Popen, port: int, binaries: Path) -> dict:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(await endpoint(process, port))
        page = await main_window(browser)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        checks = []

        async def invoke(command, payload=None):
            return await page.evaluate("([name,params]) => window.__TAURI_INTERNALS__.invoke(name,params)", [command, payload or {}])

        async def call(method, params=None):
            response = await invoke("engine_call", {"request": {"id": f"native-verify-{method}", "method": method, "params": params or {}}})
            assert response["id"] == f"native-verify-{method}" and response["ok"], (method, response)
            checks.append(method)
            return response["data"]

        status = await invoke("engine_status")
        for _ in range(40):
            if not status.get("busy"):
                break
            await asyncio.sleep(0.25)
            status = await invoke("engine_status")
        assert status["running"] and status["managed"], status
        version = await call("system.version")
        assert version["protocol_version"] == "1.2" and version["runtime"] == "rust", version
        assert Path(version["workspace"]["root"]).resolve() == options.workspace.resolve()
        doctor = await call("system.doctor")
        assert doctor["database"]["status"] == "ready" and doctor["healthy"], doctor
        installation = await call("system.installation")
        assert installation["agent_ready"]
        assert Path(installation["cli_argv"][0]).resolve() == (binaries / "studyflow.exe").resolve()
        assert Path(installation["skill_path"]).resolve() == (binaries / "studyflow-agent/SKILL.md").resolve()
        await call("system.schema", {"method": "speech.profile.save"})
        await expect(page.get_by_role("heading", name="我的计划", exact=True)).to_be_visible(timeout=30000)
        checks.append("plans-home")
        await page.evaluate('location.hash="/settings"')
        await expect(page.get_by_role("button", name="复制Agent接入说明")).to_be_enabled(timeout=20000)
        await expect(page.get_by_text(str(binaries / "studyflow.exe"), exact=True)).to_be_visible()
        await page.evaluate("""() => {
            window.__smokeClipboard = '';
            Object.defineProperty(navigator.clipboard, 'writeText', {
                configurable: true, value: async text => {window.__smokeClipboard = text;}
            });
        }""")
        await page.get_by_role("button", name="复制Agent接入说明").click()
        await page.wait_for_function("typeof window.__smokeClipboard === 'string' && window.__smokeClipboard.length > 0")
        prompt = await page.evaluate("window.__smokeClipboard")
        for expected in (str(binaries / "studyflow.exe"), installation["skill_path"], installation["workspace"], "authoring_workspace_*"):
            assert expected in prompt
        checks.append("settings-cli-discovery")
        engines = [child for child in psutil.Process(process.pid).children() if child.name().lower() == "studyflow-engine.exe"]
        assert len(engines) == 1, engines
        image = Path(engines[0].exe()).resolve()
        assert image == (binaries / "studyflow-engine.exe").resolve(), image
        assert engines[0].cmdline()[1:4] == ["--managed-desktop", version["app_version"], "1.2"]
        checks.append("managed-child-image-and-launch")
        assert not errors, errors
        await page.screenshot(path=str(options.evidence / "settings.png"))
        image_hash = sha(image)
        engine = engines[0]
        try:
            await page.get_by_role("button", name="关闭窗口", exact=True).click()
        except Exception:
            if process.poll() is None and not page.is_closed():
                raise
        assert await asyncio.to_thread(process.wait, 15) == 0
        await asyncio.to_thread(engine.wait, 10)
        checks.append("native-close-stops-managed-engine")
        return {"checks": checks, "version": version["app_version"], "image": str(image), "engine_sha256": image_hash}


def run(options: argparse.Namespace) -> None:
    binaries = options.desktop.parent / "binaries"
    installed = verify_registered_product(options.desktop, options.product_code) if options.mode == "Installed" else None
    payload = assert_payload(options, binaries)
    cli = NativeCli(options.desktop, options.workspace, options.evidence)
    version = cli.call("system.version")
    assert version["protocol_version"] == "1.2" and version["runtime"] == "rust", version
    if installed:
        assert version["app_version"] == installed["VersionString"], (version, installed)
    installation = cli.call("system.installation")
    assert Path(installation["cli_argv"][0]).resolve() == cli.executable.resolve()
    schema = cli.call("system.schema", {"method": "practice.author.preview"})
    assert schema, schema
    runtime = options.evidence / f"runtime-{time.time_ns()}"
    runtime.mkdir()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {name: value for name, value in os.environ.items() if not name.startswith(("STUDYFLOW_", "WEBVIEW2_"))}
    environment.update(
        STUDYFLOW_WORKSPACE=str(options.workspace),
        STUDYFLOW_WINDOW_STATE_DIR=str(runtime / "window-state"),
        STUDYFLOW_DIAGNOSTICS_DIR=str(runtime / "diagnostics"),
        WEBVIEW2_USER_DATA_FOLDER=str(runtime / "webview"),
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f"--remote-debugging-port={port} --remote-debugging-address=127.0.0.1",
        TEMP=str(runtime),
        TMP=str(runtime),
    )
    if options.stale_engine:
        environment["STUDYFLOW_ENGINE_PATH"] = str(options.stale_engine)
    with (runtime / "desktop.log").open("wb") as log:
        process = subprocess.Popen([str(options.desktop)], cwd=options.workspace, env=environment, stdout=log, stderr=log)
        try:
            result = asyncio.run(exercise(options, process, port, binaries))
        finally:
            if process.poll() is None:
                # Only the current test process and its own descendants are torn down.
                children = psutil.Process(process.pid).children(recursive=True)
                process.terminate()
                process.wait(timeout=10)
                for child in children:
                    try:
                        child.terminate()
                    except psutil.NoSuchProcess:
                        pass
    report = {"mode": options.mode, "desktop": str(options.desktop), "workspace": str(options.workspace),
              "stale_override_supplied": bool(options.stale_engine), "resources_checked": len(payload),
              "installed_product": installed, "cli_version": version["app_version"], **result}
    assert result["version"] == version["app_version"]
    if options.exercise_business_flows:
        report["scenarios"] = run_business_flows(options)
    (options.evidence / "desktop-smoke.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{options.mode}: {len(result['checks'])} desktop checks; {len(payload)} resources verified")


def run_business_flows(options: argparse.Namespace) -> dict[str, dict[str, str]]:
    fixtures = Path(tempfile.mkdtemp(prefix="sf-scenarios-", dir=options.workspace.parent))
    scenarios = {}
    scripts = {
        "english-cli": "smoke-english-cli.py",
        "learning-cli": "smoke-learning-experience-cli.py",
        "focused-english": "smoke-english-focused.py",
        "course-shell": "smoke-rust-course-shell.py",
    }
    for name, script in scripts.items():
        log_path = options.evidence / f"{name}.log"
        with log_path.open("wb") as log:
            args = [sys.executable, "-X", "utf8", str(Path(__file__).with_name(script)),
                    "--desktop", str(options.desktop), "--workspace", str(fixtures / name),
                    "--evidence", str(options.evidence / name)]
            result = subprocess.run(args, stdout=log, stderr=log, check=False, timeout=180)
        if result.returncode:
            raise RuntimeError(f"{name} exited {result.returncode}. See {log_path}")
        scenarios[name] = {"log": str(log_path), "workspace": str(fixtures / name)}
    return scenarios


if __name__ == "__main__":
    run(parse_args())
