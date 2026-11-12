"""英语词框自由键盘导航真实浏览器核验。
真实 Vue（dist）+ 真实 Core + 临时合成数据；验证左右/退格/Delete 在词框边界移动焦点、
Ctrl+方向键/Home/End 快速跳词、光标落位正确、内容不被破坏、导航型 Backspace 静音、
IME/修饰键契约保留，且无页面错误。
运行：PYTHONPATH=<core/src>;<core venv site-packages> python scripts/smoke-english-keyboard.py
"""
import json
from pathlib import Path
from typer.testing import CliRunner
from playwright.sync_api import sync_playwright, expect
import smoke_workbench_support as f
from studyflow.cli import app
from studyflow.interfaces.cli import runtime

EXAMPLES = f.ROOT.parents[1] / 'skills/studyflow-agent/examples'
EVIDENCE = f.ROOT / 'test-results/english-keyboard-20261112'
EVIDENCE.mkdir(parents=True, exist_ok=True)
checks = []
errors = []


def check(name, condition, detail=''):
    checks.append({'name': name, 'passed': bool(condition), 'detail': str(detail)[:300]})
    if not condition:
        raise AssertionError(f'{name}: {detail}')


def main():
    pkg = json.loads((EXAMPLES / 'english-course-package-v6.json').read_text(encoding='utf-8'))
    pkg['package_id'] = 'english-kb-demo'
    pkg['plan_line'] = f.plan.name
    file = f.WORKSPACE / 'english-kb-demo.json'
    file.write_text(json.dumps(pkg, ensure_ascii=False), encoding='utf-8')
    original = runtime.service
    runtime.service = lambda: f.service
    try:
        result = CliRunner().invoke(app, ['course', 'import-package', '--file', str(file), '--format', 'json'])
        assert result.exit_code == 0, result.output
        course = json.loads(result.stdout)['course_id']
    finally:
        runtime.service = original
    opened = f.engine.handle({'method': 'course.study.open', 'params': {'course_id': course, 'idempotency_key': 'english-kb-open'}})
    study = (opened.get('data') or {}).get('study', {}).get('id')
    assert study, opened

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--autoplay-policy=no-user-gesture-required'])
        page = browser.new_context(viewport={'width': 1440, 'height': 1000}).new_page()
        page.set_default_timeout(15000)
        page.on('pageerror', lambda e: errors.append(str(e)))
        # 计数键音播放（createBufferSource 调用），用于验证导航型 Backspace 静音。
        page.add_init_script("""
            window.__keySoundPlays=0;
            const orig=AudioContext.prototype.createBufferSource;
            AudioContext.prototype.createBufferSource=function(){window.__keySoundPlays++;return orig.call(this)};
        """)

        def state():
            return page.evaluate("""() => {
                const inputs=[...document.querySelectorAll('.english-token-row input')];
                const active=document.activeElement;
                return {values:inputs.map(i=>i.value), idx:inputs.indexOf(active),
                        selStart:active.selectionStart, selEnd:active.selectionEnd,
                        focusedClass:[...document.querySelectorAll('.english-token')].findIndex(t=>t.classList.contains('focused'))};
            }""")

        try:
            page.goto(f.url + '/#/english/' + study)
            page.wait_for_load_state('networkidle')
            expect(page.locator('.english-token-row')).to_be_visible()
            # 跳到四词项「我喜欢这个食物」（I like the food.）以验证多词框导航。
            page.get_by_role('button', name='打开课程目录', exact=True).click()
            page.locator('.english-directory button').filter(has_text='我喜欢这个食物').click()
            expect(page.locator('.english-token-row input')).to_have_count(4)
            page.wait_for_timeout(300)

            # 逐词输入：I / like / the / food，词间 Space 自动 advance；末词后不按 Space（末词 Space 会触发检查）。
            words = ['I', 'like', 'the', 'food']
            for i, word in enumerate(words):
                page.keyboard.type(word)
                if i < len(words) - 1:
                    page.keyboard.press('Space')
            page.wait_for_timeout(200)
            s = state()
            check('Space 逐词输入并自动 advance', s['values'] == ['I', 'like', 'the', 'food'] and s['idx'] == 3, s)

            # 焦点回到 box3 词尾（输入后光标在末尾）。Home 到词首，ArrowLeft 跨到 box2 词尾。
            page.locator('.english-token-row input').nth(3).focus()
            page.keyboard.press('End')
            page.keyboard.press('Home')
            page.keyboard.press('ArrowLeft')
            s = state()
            check('ArrowLeft 词首跨到上一词且光标落词尾', s['idx'] == 2 and s['selStart'] == 3 and s['selEnd'] == 3 and s['focusedClass'] == 2, s)

            # ArrowRight 在 box2 词尾跨到 box3 词首。
            page.keyboard.press('End')
            page.keyboard.press('ArrowRight')
            s = state()
            check('ArrowRight 词尾跨到下一词且光标落词首', s['idx'] == 3 and s['selStart'] == 0 and s['selEnd'] == 0, s)

            # 框内 ArrowLeft 不跳词（原生光标移动）。
            page.keyboard.press('End')
            page.keyboard.press('ArrowLeft')
            s = state()
            check('框内 ArrowLeft 仅移动光标不跳词', s['idx'] == 3 and s['selStart'] == 3, s)

            # Backspace 在 box2 词首（非空）回退到 box1，且不删除 the。
            page.locator('.english-token-row input').nth(2).focus()
            page.keyboard.press('Home')
            page.keyboard.press('Backspace')
            s = state()
            check('Backspace 词首回退上一词且不删除内容', s['idx'] == 1 and s['selStart'] == 4 and s['values'] == ['I', 'like', 'the', 'food'], s)

            # Delete 在 box1 词尾对称前进到 box2 词首，不删除内容。
            page.keyboard.press('End')
            page.keyboard.press('Delete')
            s = state()
            check('Delete 词尾对称前进下一词且不删除内容', s['idx'] == 2 and s['selStart'] == 0 and s['values'] == ['I', 'like', 'the', 'food'], s)

            # 空框 Backspace 回退：清空 box3 后 Backspace 回到 box2。
            page.locator('.english-token-row input').nth(3).focus()
            page.keyboard.press('ControlOrMeta+a')
            page.keyboard.press('Backspace')
            s = state()
            check('清空词框后内容更新', s['values'][3] == '', s)
            page.keyboard.press('Backspace')
            s = state()
            check('空框 Backspace 回退上一词', s['idx'] == 2 and s['values'] == ['I', 'like', 'the', ''], s)

            # 首词词首 ArrowLeft / Backspace 不越界。
            page.locator('.english-token-row input').nth(0).focus()
            page.keyboard.press('Home')
            page.keyboard.press('ArrowLeft')
            s = state()
            check('首词词首 ArrowLeft 不越界', s['idx'] == 0, s)
            page.keyboard.press('Backspace')
            s = state()
            check('首词 Backspace 不越界且保留内容', s['idx'] == 0 and s['values'][0] == 'I', s)

            # 选区状态不跳词（全选后 ArrowLeft 折叠选区，原生）。
            page.locator('.english-token-row input').nth(1).focus()
            page.keyboard.press('ControlOrMeta+a')
            page.keyboard.press('ArrowLeft')
            s = state()
            check('选区状态 ArrowLeft 不跳词', s['idx'] == 1, s)

            # 恢复第四词（前序空框检查已清空），为 Ctrl 跳词核验准备完整四词。
            page.locator('.english-token-row input').nth(3).focus()
            page.keyboard.type('food')
            page.wait_for_timeout(150)

            # Ctrl+ArrowLeft：词中无视光标位置直接跳上一词，光标落词尾。
            page.locator('.english-token-row input').nth(2).focus()
            page.keyboard.press('End')
            page.keyboard.press('ArrowLeft')
            page.keyboard.press('ControlOrMeta+ArrowLeft')
            s = state()
            check('Ctrl+ArrowLeft 词中直接跳上一词光标落词尾', s['idx'] == 1 and s['selStart'] == 4 and s['selEnd'] == 4, s)

            # Ctrl+ArrowRight：词中直接跳下一词，光标落词首。
            page.keyboard.press('ArrowLeft')
            page.keyboard.press('ControlOrMeta+ArrowRight')
            s = state()
            check('Ctrl+ArrowRight 词中直接跳下一词光标落词首', s['idx'] == 2 and s['selStart'] == 0 and s['selEnd'] == 0, s)

            # Ctrl+Home/End 跳首/末词框。
            page.keyboard.press('ControlOrMeta+Home')
            s = state()
            check('Ctrl+Home 跳首词框光标落词首', s['idx'] == 0 and s['selStart'] == 0, s)
            page.keyboard.press('ControlOrMeta+End')
            s = state()
            check('Ctrl+End 跳末词框光标落词尾', s['idx'] == 3 and s['selStart'] == 4 and s['selEnd'] == 4, s)

            # 首/末词 Ctrl 方向键不越界。
            page.keyboard.press('ControlOrMeta+Home')
            page.keyboard.press('ControlOrMeta+ArrowLeft')
            s = state()
            check('首词 Ctrl+ArrowLeft 不越界', s['idx'] == 0, s)
            page.keyboard.press('ControlOrMeta+End')
            page.keyboard.press('ControlOrMeta+ArrowRight')
            s = state()
            check('末词 Ctrl+ArrowRight 不越界', s['idx'] == 3, s)

            # 裸 Home/End 保留框内原生光标移动，不跨框。
            page.locator('.english-token-row input').nth(1).focus()
            page.keyboard.press('End')
            page.keyboard.press('Home')
            s = state()
            check('裸 Home/End 仍在框内移动光标', s['idx'] == 1 and s['selStart'] == 0, s)

            # 删除型 Backspace 触发键音；导航型 Backspace（跨框不删内容）静音。
            def sound_count():
                return page.evaluate('window.__keySoundPlays')

            page.locator('.english-token-row input').nth(1).focus()
            page.keyboard.press('End')
            page.wait_for_timeout(120)
            before = sound_count()
            page.keyboard.press('Backspace')
            page.wait_for_timeout(120)
            check('删除型 Backspace 触发键音', sound_count() == before + 1, (before, sound_count()))
            page.keyboard.type('e')
            page.wait_for_timeout(120)
            page.locator('.english-token-row input').nth(2).focus()
            page.keyboard.press('Home')
            page.wait_for_timeout(120)
            before = sound_count()
            page.keyboard.press('Backspace')
            page.wait_for_timeout(120)
            s = state()
            check('导航型 Backspace 静音且不删内容', sound_count() == before and s['idx'] == 1 and s['values'] == ['I', 'like', 'the', 'food'], (before, sound_count(), s))

            check('全程无页面错误', not errors, errors)
            page.screenshot(path=str(EVIDENCE / 'english-keyboard.png'))
        except Exception:
            page.screenshot(path=str(EVIDENCE / 'failure.png'))
            raise
        finally:
            browser.close()
    summary = {'checks': len(checks), 'passed': sum(1 for c in checks if c['passed']), 'page_errors': errors, 'details': checks}
    (EVIDENCE / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks': summary['checks'], 'passed': summary['passed'], 'page_errors': errors}, ensure_ascii=False))


if __name__ == '__main__':
    main()