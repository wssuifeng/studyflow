"""Release Tauri/WebView2 checks for the course shell and native notebook handoff."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

from playwright.sync_api import Error, expect, sync_playwright

from rust_smoke_support import NativeCli, launch, window

ROOT = Path(__file__).resolve().parents[3]


def fixture(cli, evidence):
    plan = cli.command('plan', 'create', '--name', 'Native workspace smoke')
    source = ROOT / 'skills/studyflow-agent/examples/course-package.json'
    course = json.loads(source.read_text(encoding='utf-8'))
    course['plan_line'] = plan['name']
    course['course']['title'] = 'Native theory shell'
    course['lessons'][0]['blocks'][0]['body'] += '\n\n' + '\n\n'.join(f'滚动验证段落 {i}。' for i in range(32))
    path = evidence / 'native-theory.json'
    path.write_text(json.dumps(course, ensure_ascii=False), encoding='utf-8')
    first = cli.command('course', 'import-package', '--file', path)['course_id']
    course['package_id'] += '-second'
    course['course']['title'] = 'Second theory course'
    path = evidence / 'native-theory-second.json'
    path.write_text(json.dumps(course, ensure_ascii=False), encoding='utf-8')
    second = cli.command('course', 'import-package', '--file', path)['course_id']
    return plan['id'], first, second


def show_course(page, course_id):
    page.evaluate('(id) => {location.hash = `/course/${id}`}', course_id)
    expect(page.locator('.study-material')).to_be_visible(timeout=20_000)
    assert page.url.split('#')[-1].split('?')[0] == '/course/' + course_id, page.url


def show_notes(page, *, editable=True):
    opener = page.get_by_role('button', name='打开答题与笔记', exact=True)
    tab = page.get_by_role('tab', name='笔记', exact=True)
    expect(opener.or_(tab).first).to_be_visible()
    if opener.is_visible():
        opener.click()
    tab.click()
    editor = page.get_by_role('textbox', name='连续笔记编辑器', exact=True)
    expect(editor).to_have_attribute('contenteditable', 'true' if editable else 'false')
    return editor


def quit_desktop(page, process):
    try:
        page.get_by_role('button', name='关闭窗口', exact=True).click(timeout=5000)
    except Error:
        if not page.is_closed() and process.poll() is None:
            raise
    assert process.wait(timeout=12) == 0


def main(desktop, workspace, evidence):
    cli = NativeCli(desktop, workspace, evidence)
    plan, first, second = fixture(cli, evidence)
    errors, checks = [], []
    params = {'plan_line_id': plan, 'limit': 100}
    runtime = evidence / 'runtime'
    with sync_playwright() as runner:
        with launch(desktop, workspace, evidence, runtime=runtime) as (endpoint, process):
            browser = runner.chromium.connect_over_cdp(endpoint)
            page = window(browser)
            page.on('pageerror', lambda err: errors.append(str(err)))
            page.set_default_timeout(10_000)
            page.emulate_media(reduced_motion='no-preference')
            page.evaluate('location.hash = "/settings"')
            for theme, theme_id in [('序光', 'sequence-light'), ('国风朱红', 'cinnabar-paper'), ('白紫', 'white-violet')]:
                page.locator('.theme-option').filter(has_text=theme).click()
                expect(page.locator('html')).to_have_attribute('data-theme-id', theme_id)
                show_course(page, first)
                outline = page.locator('#course-sidebar-content')
                page.get_by_role('button', name='收起目录', exact=True).press('Enter')
                expect(outline).to_be_hidden()
                expand = page.get_by_role('button', name='展开目录', exact=True)
                expect(expand).to_have_attribute('aria-expanded', 'false')
                expand.press('Space')
                expect(outline).to_be_visible()
                page.get_by_role('button', name='打开答题与笔记', exact=True).click()
                sidebar = page.get_by_role('complementary', name='学习工具侧栏')
                expect(sidebar).to_be_visible()
                expect(page.locator('#workspace-tool-panel')).to_have_css('animation-duration', '0.15s')
                sidebar.get_by_role('button', name='收起学习工具', exact=True).click()
                expect(sidebar).to_be_hidden()
                expect(page.locator('.study-material')).to_be_visible()
                marker = page.get_by_text('滚动验证段落 31。', exact=True)
                marker.scroll_into_view_if_needed()
                expect(marker).to_be_in_viewport()
                page.screenshot(path=str(evidence / f'{theme_id}.png'))
                checks.append(f'{theme_id}: keyboard navigation, both panels, long document scroll')
                page.evaluate('location.hash = "/settings"')
                expect(page.locator('.theme-settings')).to_be_visible()

            wide_viewport = page.evaluate('({width: innerWidth, height: innerHeight})')
            page.set_viewport_size({'width': 720, 'height': 640})
            for route, surface in [('/plans', '.plan-grid'), (f'/plan/{plan}', '.path-list li'),
                                   ('/settings', '.workspace-settings')]:
                page.evaluate('(route) => {location.hash = route}', route)
                expect(page.locator(surface).first).to_be_visible()
                assert page.locator('.main-content').evaluate('(el) => el.scrollWidth <= el.clientWidth + 1'), route
                page.screenshot(path=str(evidence / f'narrow-{route.split("/")[1]}.png'))
            page.set_viewport_size(wide_viewport)
            checks.append('720px plan list, course list and settings fit the workspace without horizontal scrolling')

            show_course(page, first)
            show_notes(page)
            scope = page.get_by_role('button', name='当前笔记位置')
            scope.press('Enter')
            picker = page.get_by_role('dialog', name='选择笔记位置')
            expect(picker).to_have_css('animation-duration', '0.15s')
            search = picker.get_by_role('textbox')
            search.fill('Native')
            search.press('Home')
            assert search.evaluate('(input) => input.selectionStart === 0')
            search.press('ArrowDown')
            expect(picker.get_by_role('button', name='全计划', exact=True)).to_be_focused()
            page.keyboard.press('Escape')
            expect(picker).to_be_hidden()
            expect(scope).to_be_focused()
            page.emulate_media(reduced_motion='reduce')
            scope.press('Enter')
            expect(picker).to_have_css('animation-name', 'none')
            page.keyboard.press('Escape')
            page.emulate_media(reduced_motion='no-preference')
            checks.append('notebook scope supports short entrance, reduced motion, text caret and Escape focus')
            page.get_by_role('button', name='其他工具操作', exact=True).click()
            page.get_by_role('menuitem', name='拆为独立窗口 ↗', exact=True).click()
            notes = window(browser, 'tool-notes')
            notes.on('pageerror', lambda err: errors.append(str(err)))
            expect(notes.locator('html')).to_have_attribute('data-theme-id', 'white-violet')
            editor = notes.get_by_role('textbox', name='连续笔记编辑器', exact=True)
            expect(editor).to_have_attribute('contenteditable', 'true')
            expect(page.locator('[data-tool="notes"] [contenteditable="true"]')).to_have_count(0)
            editor.locator('.card-prose').first.click()
            notes.keyboard.insert_text('独立窗已保存标记。')
            notes.keyboard.press('Control+s')
            deadline = time.monotonic() + 10
            while '独立窗已保存标记。' not in json.dumps(cli.call('plan.notebook.read', params), ensure_ascii=False):
                assert time.monotonic() < deadline, 'Detached notebook did not persist via the Rust engine'
                time.sleep(0.1)
            page.evaluate('location.hash = "/settings"')
            expect(page.locator('.theme-settings')).to_be_visible()
            theme = json.loads((ROOT / 'apps/desktop/src/shared/themes/builtin/white-violet.json').read_text(encoding='utf-8'))
            theme.update(id='native-test-theme', name='Native smoke custom theme')
            path = evidence / 'native-test-theme.json'
            path.write_text(json.dumps(theme, ensure_ascii=False), encoding='utf-8')
            page.get_by_label('导入主题配置文件').set_input_files(path)
            expect(page.locator('html')).to_have_attribute('data-theme-id', theme['id'])
            expect(notes.locator('html')).to_have_attribute('data-theme-id', theme['id'])
            show_course(page, first)
            notes.get_by_role('button', name='放回侧栏 ↙', exact=True).click()
            editor = page.get_by_role('textbox', name='连续笔记编辑器', exact=True)
            expect(editor).to_have_attribute('contenteditable', 'true')
            expect(editor).to_contain_text('独立窗已保存标记。')
            checks.append('native notes window follows theme and returns the same saved edit to the main window')

            show_course(page, second)
            expect(page.get_by_text('Second theory course', exact=True).first).to_be_visible()
            show_course(page, first)
            show_notes(page)
            expect(editor).to_contain_text('独立窗已保存标记。')
            checks.append('course switching keeps the notebook entries mapped to their original course')

            before = cli.call('plan.notebook.read', params)
            competing = json.loads((ROOT / 'skills/studyflow-agent/examples/notebook-v2-apply.json').read_text(encoding='utf-8'))
            competing.update(plan_line_id=plan, expected_version=before['version'], idempotency_key='native-competing-notebook-edit')
            assert cli.call('plan.notebook.apply', competing)['version'] > before['version']
            editor.locator('.card-prose').first.click()
            page.keyboard.press('Control+End')
            page.keyboard.insert_text('未保存标记。')
            page.keyboard.press('Control+s')
            expect(page.locator('footer.notebook-alert')).to_be_visible()
            page.evaluate('location.hash = "/plans"')
            expect(page.get_by_role('alertdialog')).to_be_visible()
            page.screenshot(path=str(evidence / 'native-save-failure.png'))
            page.get_by_role('button', name='不保存并离开', exact=True).click()
            expect(page.get_by_role('heading', name='我的计划', exact=True)).to_be_visible()
            assert '未保存标记。' not in json.dumps(cli.call('plan.notebook.read', params), ensure_ascii=False)
            checks.append('a competing CLI write causes a real version conflict and allows explicit discard')
            quit_desktop(page, process)

        with launch(desktop, workspace, evidence, runtime=runtime) as (endpoint, process):
            page = window(runner.chromium.connect_over_cdp(endpoint))
            page.on('pageerror', lambda err: errors.append(str(err)))
            expect(page.locator('html')).to_have_attribute('data-theme-id', 'native-test-theme')
            show_course(page, first)
            editor = show_notes(page, editable=False)
            expect(editor).to_contain_text('独立窗已保存标记。')
            expect(editor).not_to_contain_text('未保存标记。')
            expect(page.get_by_text('检测到未确认的本机内容。')).to_be_visible()
            page.get_by_role('button', name='按记录比较并恢复', exact=True).click()
            expect(editor).to_have_attribute('contenteditable', 'true')
            expect(editor).to_contain_text('未保存标记。')
            page.keyboard.press('Control+s')
            quit_desktop(page, process)
            saved = json.dumps(cli.call('plan.notebook.read', params), ensure_ascii=False)
            assert '未保存标记。' in saved and 'Learner-authorized note' in saved
            checks.append('relaunch restores the theme and lets the learner merge the local draft without overwriting the competing edit')
    assert not errors, errors
    report = {'ok': True, 'checks': checks, 'page_errors': errors, 'workspace': str(workspace)}
    (evidence / 'native-shell.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    options = argparse.ArgumentParser(description=__doc__)
    for name in ('desktop', 'workspace', 'evidence'):
        options.add_argument(f'--{name}', type=Path, required=True)
    args = options.parse_args()
    args.workspace.mkdir(parents=True, exist_ok=False)
    args.evidence.mkdir(parents=True, exist_ok=True)
    main(args.desktop.resolve(strict=True), args.workspace.resolve(), args.evidence.resolve())
