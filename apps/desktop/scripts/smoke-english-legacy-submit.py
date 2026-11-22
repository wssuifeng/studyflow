"""Native legacy-submit regression. Only disposable synthetic data; no installed-data writes.

The --binary option can launch the installed executable against the isolated fixture.
--expect blocked captures the pre-fix failure; completed is the normal regression gate.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.async_api import async_playwright, expect
from rust_smoke_support import NativeCli

ROOT = Path(__file__).resolve().parents[1]


def seed(cli, workspace: Path, check_new_round=False):
    cli.command("plan", "create", "--name", "合成旧轮次回归")
    fixtures = []
    for theme in ("序光", "白紫"):
        package = {
            "schema": "studyflow.course-package/2", "package_id": "legacy-submit-" + ("sequence" if theme == "序光" else "violet"),
            "plan_line": "合成旧轮次回归", "course": {"title": "旧轮次兼容 · " + theme, "learning_mode": "english"},
            "lessons": [{"id": "group", "title": "合成训练组", "blocks": [{"id": "intro", "type": "concept", "title": "说明", "body": "只用于旧状态兼容验证，不是用户课程。"}],
                         "exercises": [{"id": "ex-" + str(i), "title": "训练项 " + str(i + 1), "prompt": "我喜欢茶。",
                                        "english": {"target": "I like tea.", "objective_ids": ["synthetic-likes"], "evaluation_mode": "agent" if i == 73 else "local_exact"}}
                                       for i in range(74)]}],
        }
        path = workspace / ("fixture-" + theme + ".json")
        path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
        course = cli.command("course", "import-package", "--file", path)
        opened = cli.call("course.study.open", {"course_id": course["course_id"], "idempotency_key": "open-" + theme})
        sid = opened["study"]["id"]
        context = {"study_session_id": sid}
        for index, item in enumerate(cli.call("course.english.get", context)["items"]):
            answer = "My own sentence" if index == 73 else "I like tea"
            exercise = {**context, "exercise_id": item["exercise_id"]}
            saved = cli.call("course.english.save", exercise | {
                "answer_text": answer, "expected_version": 0, "idempotency_key": f"{theme}-save-{index}"})
            operation = "request-review" if index == 73 else "check"
            cli.call(f"course.english.{operation}", exercise | {
                "expected_version": saved["answer_version"], "idempotency_key": f"{theme}-{operation}-{index}"})
        before = cli.call("course.english.get", context)
        cli.call("course.english.navigate", context | {
            "position": 73, "expected_version": before["state_version"], "idempotency_key": theme + "-last"})
        if check_new_round:
            package["schema"] = "studyflow.course-package/6"
            for exercise in package["lessons"][0]["exercises"]:
                exercise["english"]["evaluation_mode"] = "local_exact"
            for index in range(74, 82):
                package["lessons"][0]["exercises"].append({"id": "ex-" + str(index), "title": "新版项 " + str(index + 1), "prompt": "学习需要练习。", "english": {"target": "Learning needs practice.", "objective_ids": ["synthetic-likes"]}})
            revised = workspace / ("revised-" + theme + ".json")
            revised.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
            request = {"course_id": course["course_id"], "path": str(revised), "expected_revision": 1}
            proposal = cli.call("course.update.preview", request)
            cli.call("course.update.apply", request | {"preview_hash": proposal["preview_hash"], "idempotency_key": "revise-" + theme})
        fixtures.append({"theme": theme, "study_id": sid, "course_id": course["course_id"], "queued": before["items"][73]})
    return fixtures


async def run(args):
    results = ROOT / "test-results" / "english-legacy-submit"
    results.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix=args.expect + "-", dir=results)).resolve()
    assert workspace.is_relative_to(results.resolve())
    binary = Path(args.binary).resolve()
    engine = binary.parent / "binaries/studyflow-engine.exe"
    assert binary.is_file() and engine.is_file()
    fixtures = seed(NativeCli(binary, workspace, workspace), workspace, args.check_new_round)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("STUDYFLOW_", "WEBVIEW2_"))}
    temp = workspace / "temp"
    temp.mkdir()
    env.update(STUDYFLOW_WORKSPACE=str(workspace), STUDYFLOW_WINDOW_STATE_DIR=str(workspace / "window-state"),
               WEBVIEW2_USER_DATA_FOLDER=str(workspace / "webview-profile"),
               WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f"--remote-debugging-port={port} --remote-debugging-address=127.0.0.1",
               TEMP=str(temp), TMP=str(temp))
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    checks, errors = [], []
    with (workspace / "native.log").open("w", encoding="utf-8") as log:
        proc = subprocess.Popen([str(binary)], cwd=workspace, env=env, startupinfo=startup, stdout=log, stderr=log)
        browser = None
        try:
            async with async_playwright() as playwright:
                deadline = time.monotonic() + 30
                while True:
                    if proc.poll() is not None:
                        raise RuntimeError(f"Native process exited {proc.returncode}")
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=.5) as response:
                            json.load(response)
                        break
                    except Exception:
                        if time.monotonic() > deadline:
                            raise
                        await asyncio.sleep(.2)
                browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
                context = browser.contexts[0]
                page = context.pages[0]
                page.set_default_timeout(15000)
                page.on("pageerror", lambda e: errors.append(str(e)))
                await expect(page.get_by_role("heading", name="我的计划", exact=True)).to_be_visible()

                async def invoke(method, params):
                    return await page.evaluate("""async ({method,params})=>{
                        const response=await window.__TAURI_INTERNALS__.invoke('engine_call',{request:{id:crypto.randomUUID(),method,params}});
                        if(!response.ok)throw Error(JSON.stringify(response.error));return response.data;
                    }""", {"method": method, "params": params})

                for fixture in fixtures:
                    await page.evaluate("location.hash='/settings'")
                    await page.locator(".theme-option").filter(has_text=fixture["theme"]).click()
                    await page.evaluate("(id)=>{location.hash='/course/'+id}", fixture["course_id"])
                    await expect(page.get_by_role("button", name="完成本课", exact=True)).to_be_visible()
                    await page.locator(".english-speech-settings").wait_for(state="hidden")
                    # Disable audio in this isolated test so a dictionary network failure cannot affect the gate.
                    await page.get_by_role("button", name="训练设置", exact=True).click()
                    await page.get_by_label("静音", exact=True).check()
                    await page.get_by_role("button", name="训练设置", exact=True).click()
                    if args.expect != "blocked":
                        await expect(page.locator(".english-stage")).to_contain_text("待审核不计为检查通过")
                        await page.screenshot(path=str(workspace / (fixture["theme"] + "-queued.png")))
                        await page.get_by_role("button", name="完成本课", exact=True).press("Control+Comma")
                        await expect(page.get_by_role("button", name="下一项 →", exact=True)).to_be_visible()
                        await page.get_by_role("button", name="下一项 →", exact=True).click()
                        await expect(page.get_by_role("button", name="完成本课", exact=True)).to_be_visible()
                    await page.get_by_role("button", name="完成本课", exact=True).click()
                    if args.expect == "blocked":
                        await expect(page.locator(".status-banner")).to_contain_text("已返回第 74 项")
                        assert await page.locator(".english-result").count() == 0
                        await page.screenshot(path=str(workspace / (fixture["theme"] + "-blocked.png")))
                    else:
                        await expect(page.get_by_role("heading", name="这门课的训练已确认", exact=True)).to_be_visible()
                        await expect(page.locator(".english-result")).to_contain_text("73 / 74 项已完成检查")
                        await expect(page.locator(".english-result")).to_contain_text("另有 1 项已提交，等待批改。")
                        assert await page.locator(".english-error").count() == 0
                        await page.screenshot(path=str(workspace / (fixture["theme"] + "-completed.png")))
                    after = await invoke("course.english.get", {"study_session_id": fixture["study_id"]})
                    assert after["completed"] == (args.expect != "blocked")
                    queued = after["items"][73]
                    for key in ("answer_text", "answer_version", "submission_id", "status", "matched"):
                        assert queued[key] == fixture["queued"][key], (key, queued[key], fixture["queued"][key])
                    assert queued["status"] == "WAITING_REVIEW" and queued["matched"] is False
                    checks.append(fixture["theme"] + ": " + args.expect + "; queued answer/version/status preserved")
                    if args.check_new_round and args.expect != "blocked":
                        await page.get_by_role("button", name="返回课程", exact=True).click()
                        revised_button = page.get_by_role("button", name="学习修订后的课程", exact=True)
                        if args.expect == "round-blocked":
                            await page.get_by_role("button", name="开启新的回顾轮次", exact=True).click()
                            await expect(page.locator(".status-banner.error")).to_contain_text("当前学习尚未收口")
                            current = await invoke("course.detail", {"course_id": fixture["course_id"]})
                            assert current["course"]["study_session_id"] == fixture["study_id"]
                            await page.screenshot(path=str(workspace / (fixture["theme"] + "-next-round-blocked.png")))
                            checks.append(fixture["theme"] + ": reproduced completed-training / new-round deadlock")
                        else:
                            await expect(revised_button).to_be_enabled()
                            await expect(page.locator(".english-overview")).to_contain_text("当前轮次使用版本 1（74 项）")
                            await page.screenshot(path=str(workspace / (fixture["theme"] + "-revision-overview.png")))
                            await revised_button.click()
                            await expect(page.locator(".english-header-title")).to_contain_text("1 / 82")
                            current = await invoke("course.detail", {"course_id": fixture["course_id"]})
                            new_id = current["course"]["study_session_id"]
                            assert new_id != fixture["study_id"]
                            fresh = await invoke("course.english.get", {"study_session_id": new_id})
                            assert len(fresh["items"]) == 82 and fresh["course"]["content_revision"] == 2
                            assert not fresh["completed"] and all(row["answer_text"] == "" and row["answer_version"] == 0 for row in fresh["items"])
                            retained = await invoke("course.english.get", {"study_session_id": fixture["study_id"]})
                            assert retained["completed"] is True and retained["items"][73] == after["items"][73]
                            await page.screenshot(path=str(workspace / (fixture["theme"] + "-new-round-empty.png")))
                            checks.append(fixture["theme"] + ": revision 2 / 82-item new round empty; old queued history unchanged")
                assert not errors, errors
                result = {"ok": True, "expect": args.expect, "binary": str(binary), "engine": str(engine),
                          "scope": "synthetic-only; actual Tauri/WebView2 + bundled Rust Engine", "workspace": str(workspace),
                          "checks": checks, "page_errors": errors}
                (workspace / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps(result, ensure_ascii=False))
        except Exception:
            if browser:
                for index, page in enumerate(browser.contexts[0].pages):
                    if not page.is_closed():
                        try:
                            await page.screenshot(path=str(workspace / f"failure-{index}.png"))
                            (workspace / f"failure-{index}.txt").write_text(await page.locator("body").inner_text(), encoding="utf-8")
                        except Exception:
                            pass
            print("NATIVE EVIDENCE:", workspace)
            raise
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=8)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default=str(ROOT / "src-tauri/target/release/studyflow-desktop.exe"))
    parser.add_argument("--expect", choices=("blocked", "completed", "round-blocked"), default="completed")
    parser.add_argument("--check-new-round", action="store_true")
    args = parser.parse_args()
    if args.expect == "round-blocked":
        args.check_new_round = True
    asyncio.run(run(args))
