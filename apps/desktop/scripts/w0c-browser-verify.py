"""W0c browser verification: real Vue dist + Core + synthetic workspace + Playwright.
Dual-theme screenshots of key routes with content assertions, P1 empty-input check,
theme toolbar parity, page errors. Synthetic workspace under test-results/ only."""
from __future__ import annotations
import json, re, shutil
from pathlib import Path
from playwright.sync_api import sync_playwright

import smoke_workbench_support as f  # noqa: E402  starts dist server, seeds plan + 2 general courses
from studyflow.interfaces.cli import runtime  # noqa: E402

REVIEW = f.ROOT / 'test-results' / 'w0c-review'
if REVIEW.exists(): shutil.rmtree(REVIEW)
REVIEW.mkdir(parents=True)

EXAMPLES = f.ROOT.parents[1] / 'skills' / 'studyflow-agent' / 'examples'

# Seed an English course and open study sessions for reader + english routes.
english_pkg = json.loads((EXAMPLES / 'english-course-package-v6.json').read_text(encoding='utf-8'))
english_pkg['plan_line'] = f.plan.name
epath = f.WORKSPACE / 'english-seed.json'
epath.write_text(json.dumps(english_pkg, ensure_ascii=False), encoding='utf-8')
original = runtime.service
runtime.service = lambda: f.service
try:
    ec = f.service.import_course_package(epath)
    english_course_id = ec['course_id']
    f.service.open_course_study(f.courses[0], 'w0c-general-open', plan_line_id=f.plan.id)
    english_study = f.service.open_course_study(english_course_id, 'w0c-english-open', plan_line_id=f.plan.id)['study']['id']
finally:
    runtime.service = original

THEMES = [('white-violet', '白紫轻学'), ('sequence-light', '序光')]
THEME_PREF = 'studyflow:theme-preference:v1'
findings: list[dict] = []
errors_total: list[str] = []


def open_route(browser, theme_id, route, assert_text=None, assert_selector=None, wait_ms=500):
    page = browser.new_page(viewport={'width': 1580, 'height': 1050})
    page.set_default_timeout(12000)
    page.on('pageerror', lambda e: errors_total.append(f'[{theme_id}:{route}] {e}'))
    # ThemeSnapshot 形状见 controller.ts: {schema_version, selected_theme_id, custom_themes, revision}
    snapshot = {"schema_version": "studyflow.theme-preference/1", "selected_theme_id": theme_id,
                "custom_themes": [], "revision": {"clock": 0, "source": "w0c"}}
    script = "try{localStorage.setItem('%s',JSON.stringify(%s))}catch(e){}" % (THEME_PREF, json.dumps(snapshot, ensure_ascii=False))
    page.add_init_script(script)
    page.goto(f.url + '/#' + route)
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(wait_ms)
    applied = page.locator('[data-theme-display="%s"]' % theme_id).count() > 0
    content_ok = True
    if assert_selector is not None:
        content_ok = page.locator(assert_selector).count() > 0
    if assert_text is not None:
        content_ok = content_ok and page.get_by_text(assert_text, exact=False).first.is_visible()
    return page, applied, content_ok


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)

    routes = [
        ('today', '/today', '学习控制台', None, '.today-workspace, [class*="today"], main'),
        ('plans', '/plans', '计划列表', None, '.plan-list-filters'),
        ('plan', f'/plan/{f.plan.id}', '计划详情', f.plan.name, '.detail-heading'),
        ('course', f'/course/{f.courses[0]}', '课程阅读', None, '.reader-toolbar'),
        ('english', f'/english/{english_study}', '英语训练', None, '.english-learning'),
    ]
    for theme_id, theme_label in THEMES:
        for key, route, label, text, selector in routes:
            try:
                page, applied, content_ok = open_route(browser, theme_id, route, text, selector)
                shot = REVIEW / f'{theme_id}-{key}.png'
                page.screenshot(path=str(shot), full_page=True)
                findings.append({'theme': theme_id, 'route': key, 'label': label,
                                 'screenshot': str(shot), 'ok': applied and content_ok,
                                 'theme_applied': applied, 'content_ok': content_ok})
                page.close()
            except Exception as exc:
                findings.append({'theme': theme_id, 'route': key, 'label': label,
                                 'screenshot': None, 'ok': False, 'error': str(exc)[:200]})

        # W3/W4 claim: the unified reader toolbar exposes the sound toggle in BOTH themes (P3 fix)
        try:
            page, applied, content_ok = open_route(browser, theme_id, f'/course/{f.courses[0]}')
            sound_any = page.locator('[aria-label*="操作音效"]').count()
            findings.append({'theme': theme_id, 'route': 'course', 'label': '阅读页音效开关(统一骨架)',
                             'screenshot': None, 'ok': applied and sound_any > 0,
                             'detail': f'音效开关元素数={sound_any}; 主题生效={applied}'})
            page.close()
        except Exception as exc:
            findings.append({'theme': theme_id, 'route': 'course', 'label': '阅读页音效开关(统一骨架)',
                             'screenshot': None, 'ok': False, 'error': str(exc)[:200]})

    # P1 empty-input: click 检查答案 with empty input -> no save-failure banner, near-input status notice
    try:
        page, applied, content_ok = open_route(browser, 'white-violet', f'/english/{english_study}', wait_ms=800)
        page.get_by_role('button', name=re.compile('检查答案')).click()
        page.wait_for_timeout(700)
        banner = page.locator('.english-error').count()
        notice = page.get_by_text('先输入答案', exact=False).count()
        retry_buttons = page.get_by_role('button', name='重试原请求', exact=True).count()
        shot = REVIEW / 'p1-empty-input.png'
        page.screenshot(path=str(shot), full_page=True)
        findings.append({'theme': 'white-violet', 'route': 'english', 'label': 'P1空输入(检查答案)',
                         'screenshot': str(shot), 'ok': banner == 0 and notice > 0,
                         'detail': f'english-error横幅={banner}; 输入附近提示={notice}; 重试按钮={retry_buttons}'})
        page.close()
    except Exception as exc:
        findings.append({'theme': 'white-violet', 'route': 'english', 'label': 'P1空输入(检查答案)',
                         'screenshot': None, 'ok': False, 'error': str(exc)[:200]})
    browser.close()

summary = {
    'findings': findings,
    'page_errors': errors_total,
    'screenshots_dir': str(REVIEW),
    'ok': sum(1 for x in findings if x.get('ok')),
    'failed': [x for x in findings if not x.get('ok')],
}
(REVIEW / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'screenshots_dir': str(REVIEW), 'ok': summary['ok'], 'failed': summary['failed'],
                  'page_errors': errors_total}, ensure_ascii=False, indent=2))
f.server.shutdown(); f.database.dispose()
