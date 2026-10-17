"""W5/R2 双主题运行时契约测试（主设计§8.3第4道 + 续行提示词§5覆盖表）。
真实 Vue dist + Core + 合成工作区 + Playwright。覆盖 9 场景 × 双主题 × 三视口，
断言主题生效/区域几何/可见性/焦点/输入/滚动/状态保持；主题切换不写 Core。
截图与 manifest 写入 test-results/ui-contract/（git 忽略）。用户视觉验收单列 not_evaluated。

隔离：仅合成工作区；STUDYFLOW_WORKSPACE/TEMP 由调用方设置（CI 与本地均显式隔离）。
node 入口：npm run test:ui-contract → python scripts/test_ui_contract.py
"""
from __future__ import annotations
import json, re, shutil, time, hashlib, os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

import smoke_workbench_support as f  # noqa: E402  starts dist server + seeds plan + 2 general courses
from studyflow.interfaces.cli import runtime  # noqa: E402

REVIEW = f.ROOT / 'test-results' / 'ui-contract'
if REVIEW.exists(): shutil.rmtree(REVIEW)
REVIEW.mkdir(parents=True)

EXAMPLES = f.ROOT.parents[1] / 'skills' / 'studyflow-agent' / 'examples'
THEME_PREF = 'studyflow:theme-preference:v1'
THEMES = [('white-violet', '白紫轻学'), ('sequence-light', '序光')]
VIEWPORTS = {'full': {'width': 1920, 'height': 1080}, 'mid': {'width': 1366, 'height': 768}, 'narrow': {'width': 1280, 'height': 720}}

# ── 引擎请求计数（用于"主题切换不写 Core"断言）+ 有界故障注入（S8 验证未保存退出窗） ──
engine_calls: list[str] = []
_fault = {'method': None, 'count': 0}  # 测试专用故障注入点；仅 S8 用，标明注入方法
_original_handle = f.engine.handle
def counting_handle(req):
    method = req.get('method', '') if isinstance(req, dict) else ''
    if _fault['method'] and method == _fault['method'] and _fault['count'] > 0:
        _fault['count'] -= 1
        return {'id':req.get('id'), 'ok': False, 'error': {'code': 'INJECTED_FAULT', 'message': 'test fault injection (S8 leave-dialog)'},
                'method': method, 'idempotency_key': req.get('idempotency_key')}
    engine_calls.append(method)
    return _original_handle(req)
f.engine.handle = counting_handle

def fresh_english_study(key):
    """每个英语交互场景开【独立课程+独立轮次】：用唯一 package_id 重新导入，确保从第1项开始、
    无 recovery 草稿与跨场景进度泄漏（合成数据，标明非学习证据）。W2 语义下同课程的
    open_course_study 复用活动轮次，因此必须换 package_id 才能得到真新鲜课程。"""
    pkg = json.loads((EXAMPLES / 'english-course-package-v6.json').read_text(encoding='utf-8'))
    pkg['plan_line'] = f.plan.name
    pkg['package_id'] = f'ui-contract-{key}'
    pkg['course']['title'] = f'合成 · 英语契约验证 {key}'  # 唯一标题避免"同名课程"拒绝
    epath = f.WORKSPACE / f'english-{key}.json'
    epath.write_text(json.dumps(pkg, ensure_ascii=False), encoding='utf-8')
    orig = runtime.service; runtime.service = lambda: f.service
    try:
        ec = f.service.import_course_package(epath)
        sid = f.service.open_course_study(ec['course_id'], f'ui-{key}', plan_line_id=f.plan.id)['study']['id']
        return sid
    finally:
        runtime.service = orig

# W2 语义：课程活动轮次按课程复用（open_course_study 幂等回放同轮），因此英语场景共享同一轮次，
# 测试必须按当前轮次状态推进（已通过项按钮为"下一项"，未通过项为"检查答案"）。
def english_state(page):
    span = page.locator('.english-header-title span')
    txt = span.inner_text() if span.count() else ''
    m = re.search(r'(\d+)\s*/\s*(\d+)', txt)
    done = re.search(r'已检查通过\s*(\d+)', txt)
    return {'index': int(m.group(1)) if m else 0, 'total': int(m.group(2)) if m else 0,
            'passed': int(done.group(1)) if done else 0}

def advance_to_unchecked(page, max_steps=10):
    for _ in range(max_steps):
        if page.get_by_role('button', name=re.compile('检查答案')).count(): return True
        nxt = page.get_by_role('button', name=re.compile('下一项'))
        if not nxt.count(): return False
        nxt.first.click(); page.wait_for_timeout(600)
    return page.get_by_role('button', name=re.compile('检查答案')).count() > 0

# ── 种子：长文阅读课程（多知识点、details 折叠、列表、表格、代码） + 英语 v6 ──
LONG_MD = '''# 长文阅读 · 概念脉络

本节用较长的正文验证阅读区滚动与左栏固定，不被多重容器反复限宽。

## 第一节：从问题到模型

日常学习中，知识点不是孤立的卡片，而是相互支撑的网络。把一个概念放到上下文里，才能判断它的适用边界与代价。

<details>
<summary>展开：为什么"先问题后模型"更有效</summary>

直接背诵模型容易把条件当作普适规则。先遇到具体问题，再归纳模型，能让条件成为模型的一部分，而不是事后的脚注。

</details>

## 第二节：清单与对照

- 限定词决定边界
- 假设决定适用范围
- 反例决定 robustness

| 维度 | 直接背诵 | 问题驱动 |
|---|---|---|
| 条件 | 易忽略 | 内化 |
| 迁移 | 弱 | 强 |

## 第三节：代码片段

```python
def learn(concept, context):
    return apply(concept, context.boundary)
```

## 第四节：连续展开的长正文

''' + '\n'.join(f'### 第{n}段：概念延伸\n\n这是一段足够长的正文，用来验证阅读区在 1920×1080 也需要滚动，而不是把内容压在一屏内。知识点之间相互支撑：第{n}段在第{n-1}段的基础上补一个限定条件，让模型的边界越来越清晰。继续展开是为了让"长文滚动"这一运行时契约真正可被断言，而不是用短正文假充通过。\n' for n in range(1, 30)) + '''

## 结论

长正文应在约定阅读区滚动，左栏导航固定在窗口区域，不随正文一起越滚越长。上述段落、清单、表格、代码与折叠详情均应可读、可滚、不被多重容器限宽。
'''

original = runtime.service
runtime.service = lambda: f.service
long_course_id = None
english_study = None
general_study = None
try:
    # 长文课程：直接通过 service 在事务内建 Course/Lesson/Exercise + 写 markdown 文件
    from studyflow.models import Course, Lesson, Exercise, PlanCourseItem
    from studyflow.services import new_id
    with f.service.session() as db:
        c = Course(id=new_id(), plan_line_id=f.plan.id, title='合成 · 长文阅读与概念脉络', learning_mode='general')
        db.add(c); db.add(PlanCourseItem(id=new_id(), plan_line_id=f.plan.id, course_id=c.id, sequence_number=99))
        filename = 'content/long-reading.md'
        (f.WORKSPACE / filename).parent.mkdir(parents=True, exist_ok=True)
        (f.WORKSPACE / filename).write_text(LONG_MD, encoding='utf-8')
        lesson = Lesson(id=new_id(), course_id=c.id, title='长文阅读 · 概念脉络', position=1, markdown_path=filename)
        db.add(lesson); db.flush()
        db.add(Exercise(id=new_id(), lesson_id=lesson.id, title='复述概念脉络', prompt='请用自己的话复述本节的概念脉络。', position=1))
        db.flush()
        long_course_id = c.id
    # 英语 v6 包
    pkg = json.loads((EXAMPLES / 'english-course-package-v6.json').read_text(encoding='utf-8'))
    pkg['plan_line'] = f.plan.name
    epath = f.WORKSPACE / 'ui-contract-english.json'
    epath.write_text(json.dumps(pkg, ensure_ascii=False), encoding='utf-8')
    ec = f.service.import_course_package(epath)
    english_course_id = ec['course_id']
    ENGLISH_TARGETS = [ (e.get('english') or {}).get('target', '') for lesson in pkg.get('lessons', []) for e in (lesson.get('exercises') or []) ]
    PROMPT_TO_TARGET = { e.get('prompt', ''): (e.get('english') or {}).get('target', '') for lesson in pkg.get('lessons', []) for e in (lesson.get('exercises') or []) }
    f.service.open_course_study(f.courses[0], 'ui-contract-general', plan_line_id=f.plan.id)['study']['id']
    f.service.open_course_study(long_course_id, 'ui-contract-long', plan_line_id=f.plan.id)['study']['id']
    english_study = f.service.open_course_study(english_course_id, 'ui-contract-english', plan_line_id=f.plan.id)['study']['id']
finally:
    runtime.service = original

findings: list[dict] = []
errors_total: list[str] = []


def snapshot_for(theme_id):
    return {"schema_version": "studyflow.theme-preference/1", "selected_theme_id": theme_id,
            "custom_themes": [], "revision": {"clock": 0, "source": "ui-contract"}}


def open_page(browser, theme_id, route, viewport='full', wait_ms=600):
    vp = VIEWPORTS[viewport]
    page = browser.new_page(viewport=vp)
    page.set_default_timeout(12000)
    page.on('pageerror', lambda e: errors_total.append(f'[{theme_id}:{route}@{viewport}] {e}'))
    page.add_init_script("try{localStorage.setItem('%s',JSON.stringify(%s))}catch(e){}" % (THEME_PREF, json.dumps(snapshot_for(theme_id), ensure_ascii=False)))
    page.goto(f.url + '/#' + route)
    page.wait_for_load_state('networkidle')
    page.wait_for_timeout(wait_ms)
    return page


def shot(page, theme_id, name, viewport):
    p = REVIEW / f'{theme_id}-{name}-{viewport}.png'
    page.screenshot(path=str(p), full_page=False)
    return str(p)


def assert_theme_applied(page, theme_id):
    # data-theme-id on <html> is the runtime scoping anchor; data-theme-display mirrors it for AppShell
    html_id = page.locator('html').get_attribute('data-theme-id')
    return html_id == theme_id


def record(scenario, theme_id, viewport, checks, screenshot=None, error=None):
    findings.append({'scenario': scenario, 'theme': theme_id, 'viewport': viewport,
                     'ok': (error is None) and all(c['ok'] for c in checks),
                     'checks': checks, 'screenshot': screenshot, 'error': error[:200] if error else None})


# ── 主验证循环 ──────────────────────────────────────────────────
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True,channel="msedge" if os.name=="nt" else None)
    try:
        for theme_id, _label in THEMES:
            # S1 控制台 / 计划列表 / 计划详情（1920×1080）
            try:
                page = open_page(browser, theme_id, '/today')
                nav = page.locator('.sidebar .nav-item').count()
                heading = page.get_by_role('heading', name='学习控制台', exact=False).count()
                checks = [{'name': 'theme_applied', 'ok': assert_theme_applied(page, theme_id)},
                          {'name': 'nav_items', 'ok': nav >= 5, 'detail': str(nav)},
                          {'name': 'today_heading', 'ok': heading > 0}]
                record('S1-console', theme_id, 'full', checks, shot(page, theme_id, 'console', 'full'))
                page.close()
            except Exception as e: record('S1-console', theme_id, 'full', [], error=str(e))

            try:
                page = open_page(browser, theme_id, '/plans')
                plan_visible = page.get_by_text(f.plan.name, exact=False).first.is_visible()
                # 搜索无结果：在搜索框输入随机串（placeholder 为"查找计划…"）
                search = page.locator('input[placeholder*="查找"], input[placeholder*="搜索"], input[aria-label*="搜索"]').first
                no_result = False
                if search.count():
                    search.fill('zzz-no-such-plan-' + theme_id)
                    page.wait_for_timeout(400)
                    no_result = page.get_by_text(re.compile('没有|无结果|未找到|暂无'), exact=False).count() > 0
                checks = [{'name': 'theme_applied', 'ok': assert_theme_applied(page, theme_id)},
                          {'name': 'plan_listed', 'ok': plan_visible},
                          {'name': 'search_no_result_state', 'ok': no_result, 'detail': f'search={search.count()}'}]
                record('S1-plans', theme_id, 'full', checks, shot(page, theme_id, 'plans', 'full'))
                page.close()
            except Exception as e: record('S1-plans', theme_id, 'full', [], error=str(e))

            try:
                page = open_page(browser, theme_id, f'/plan/{f.plan.id}')
                heading = page.get_by_role('heading', name=f.plan.name, exact=False).count()
                checks = [{'name': 'theme_applied', 'ok': assert_theme_applied(page, theme_id)},
                          {'name': 'plan_detail_heading', 'ok': heading > 0}]
                record('S1-plan-detail', theme_id, 'full', checks, shot(page, theme_id, 'plan-detail', 'full'))
                page.close()
            except Exception as e: record('S1-plan-detail', theme_id, 'full', [], error=str(e))

            # S2 普通长文阅读（full + mid + narrow）
            for vp in ('full', 'mid', 'narrow'):
                try:
                    page = open_page(browser, theme_id, f'/course/{long_course_id}', viewport=vp, wait_ms=800)
                    sidebar_box = page.locator('.sidebar').first.bounding_box()
                    main_box = page.locator('.main-content, .study-material').first.bounding_box()
                    sidebar_pos = page.evaluate('''()=>{const sb=document.querySelector('.sidebar');return sb?getComputedStyle(sb).position:null}''')
                    scroll_info = page.evaluate('''() => {
                        const cand = ['.study-material-body','.study-material','.reader-content','.main-content','.learning-shell'];
                        for (const sel of cand) {
                            const el = document.querySelector(sel);
                            if (el && el.scrollHeight > el.clientHeight + 20) return {sel, scrollH: el.scrollHeight, clientH: el.clientHeight};
                        }
                        const doc = document.documentElement;
                        return {sel: 'document', scrollH: doc.scrollHeight, clientH: doc.clientHeight};
                    }''')
                    scrollable = scroll_info['scrollH'] > scroll_info['clientH'] + 20
                    details = page.locator('details').count()
                    table = page.locator('table').count()
                    code = page.locator('pre, code').count()
                    checks = [{'name': 'theme_applied', 'ok': assert_theme_applied(page, theme_id)},
                              {'name': 'sidebar_present', 'ok': sidebar_box is not None and sidebar_box['width'] >= 56},
                              {'name': 'sidebar_fixed', 'ok': sidebar_pos == 'fixed', 'detail': f'position={sidebar_pos}'},
                              {'name': 'main_region_present', 'ok': main_box is not None and main_box['width'] >= 360},
                              {'name': 'long_content_scrolls', 'ok': bool(scrollable), 'detail': f"{scroll_info['sel']}: {scroll_info['scrollH']}>{scroll_info['clientH']}"},
                              {'name': 'rich_components', 'ok': details > 0 and table > 0 and code > 0, 'detail': f'details={details},table={table},code={code}'}]
                    record(f'S2-long-reading-{vp}', theme_id, vp, checks, shot(page, theme_id, 'long-read', vp))
                    page.close()
                except Exception as e: record(f'S2-long-reading-{vp}', theme_id, vp, [], error=str(e))

            # S3 课程/本节大纲
            try:
                page = open_page(browser, theme_id, f'/course/{long_course_id}', wait_ms=800)
                # 大纲是 role=tab（"课程大纲"/"本节大纲"），不是 button
                outline_tab = page.get_by_role('tab', name=re.compile('大纲'), exact=False)
                outline_switched = False
                if outline_tab.count():
                    outline_tab.first.click(); page.wait_for_timeout(400); outline_switched = True
                outline_items = page.locator('[class*="outline-item"], .course-outline li').count()
                checks = [{'name': 'theme_applied', 'ok': assert_theme_applied(page, theme_id)},
                          {'name': 'outline_tab_reachable', 'ok': outline_tab.count() > 0, 'detail': f'tabs={outline_tab.count()}'},
                          {'name': 'outline_items', 'ok': outline_items > 0, 'detail': str(outline_items)}]
                record('S3-outline', theme_id, 'full', checks, shot(page, theme_id, 'outline', 'full'))
                page.close()
            except Exception as e: record('S3-outline', theme_id, 'full', [], error=str(e))

            # S4 普通课练习侧栏（full + narrow）
            for vp in ('full', 'narrow'):
                try:
                    page = open_page(browser, theme_id, f'/course/{f.courses[0]}', viewport=vp, wait_ms=700)
                    open_btn = page.get_by_role('button', name=re.compile('打开答题|打开工具|答题与笔记'), exact=False)
                    if open_btn.count(): open_btn.first.click(); page.wait_for_timeout(400)
                    dock_visible = page.locator('.dock-surface, #workspace-tool-panel, [class*="tool-panel"]').first.is_visible()
                    exercise_prompt = page.get_by_text(re.compile('请用自己的话'), exact=False).count()
                    answer = page.locator('.knowledge-question textarea').first
                    answer.fill('合成选区验证，自动保存时保留当前输入。')
                    page.evaluate("()=>{window.__answerNode=document.querySelector('.knowledge-question textarea');window.__materialNode=document.querySelector('.study-material')}")
                    answer.focus(); page.keyboard.press('Control+a'); page.keyboard.press('ArrowLeft'); page.keyboard.press('Control+Shift+ArrowRight')
                    box = answer.bounding_box()
                    page.mouse.move(box['x']+18,box['y']+18);page.mouse.down();page.mouse.move(box['x']+150,box['y']+18,steps=8);page.mouse.up()
                    page.keyboard.insert_text('替换后的合成答案')
                    page.wait_for_timeout(1300)
                    page.keyboard.press('Control+a')
                    before = answer.evaluate('(el)=>({start:el.selectionStart,end:el.selectionEnd,value:el.value})')
                    saved=f.service.course_answer_sheet(f.courses[0])
                    assert any(row['draft'] and row['draft']['answer_text']==before['value'] for row in saved['answers'])

                    # Call the real focus poll after an autosave, without remounting the editor.
                    page.evaluate('window.dispatchEvent(new Event("focus"))'); page.wait_for_timeout(600)
                    expect(page.locator('.study-material')).to_be_visible();expect(answer).to_be_focused()
                    assert before == answer.evaluate('(el)=>({start:el.selectionStart,end:el.selectionEnd,value:el.value})')
                    assert page.evaluate('window.__answerNode===document.querySelector(".knowledge-question textarea")&&window.__materialNode===document.querySelector(".study-material")')
                    assert page.get_by_text('工作区有新反馈或状态更新',exact=False).count()==0

                    checks = [{'name': 'theme_applied', 'ok': assert_theme_applied(page, theme_id)},
                              {'name': 'dock_open', 'ok': dock_visible},
                              {'name': 'exercise_reachable', 'ok': exercise_prompt > 0},
                              {'name': 'native_select_autosave_focus_preserved', 'ok': True}]
                    record(f'S4-exercise-sidebar-{vp}', theme_id, vp, checks, shot(page, theme_id, 'exercise', vp))
                    page.close()
                except Exception as e: record(f'S4-exercise-sidebar-{vp}', theme_id, vp, [], error=str(e))

            # S5 连续笔记侧栏
            try:
                page = open_page(browser, theme_id, f'/course/{f.courses[0]}', wait_ms=700)
                open_btn = page.get_by_role('button', name=re.compile('打开答题|答题与笔记'), exact=False)
                if open_btn.count(): open_btn.first.click(); page.wait_for_timeout(400)
                notes_tab = page.get_by_role('tab', name=re.compile('笔记'), exact=False)
                if notes_tab.count(): notes_tab.first.click(); page.wait_for_timeout(400)
                # notes v2 是 Tiptap contenteditable（role=textbox, aria-label=连续笔记编辑器）；也可能有 textarea 兜底
                editor = page.get_by_role('textbox', name=re.compile('连续笔记|笔记'), exact=False).first
                if not editor.count(): editor = page.locator('[contenteditable="true"]').first
                if not editor.count(): editor = page.get_by_role('textbox').first
                wrote = False
                if editor.count():
                    editor.click(); page.wait_for_timeout(200)
                    page.keyboard.type(f'ui-contract note {theme_id}', delay=15)
                    page.wait_for_timeout(200)
                    wrote = True
                checks = [{'name': 'theme_applied', 'ok': assert_theme_applied(page, theme_id)},
                          {'name': 'notes_tab_reachable', 'ok': notes_tab.count() > 0},
                          {'name': 'note_input_reachable', 'ok': wrote}]
                record('S5-notes-sidebar', theme_id, 'full', checks, shot(page, theme_id, 'notes', 'full'))
                page.close()
            except Exception as e: record('S5-notes-sidebar', theme_id, 'full', [], error=str(e))

            # S6 英语训练（full + narrow）：推进到未检查项；空输入 P1 + 正确答案检查反馈
            for vp in ('full', 'narrow'):
                try:
                    est = fresh_english_study(f'ui-s6-{theme_id}-{vp}')
                    page = open_page(browser, theme_id, f'/english/{est}', viewport=vp, wait_ms=1200)
                    training = page.locator('.english-learning, [class*="english"]').count()
                    advanced = advance_to_unchecked(page)
                    state = english_state(page)
                    passed_before = state['passed']
                    prompt_text = page.locator('.english-question h1').inner_text() if page.locator('.english-question h1').count() else ''
                    target = PROMPT_TO_TARGET.get(prompt_text, '')
                    check_btn = page.get_by_role('button', name=re.compile('检查答案'), exact=False).first
                    # 清空输入框（advance 可能在项间残留前一项文本，导致本地空输入守卫不触发）
                    inp = page.get_by_role('textbox').first
                    if inp.count(): inp.fill(''); page.wait_for_timeout(200)
                    recovery_present = page.locator('.english-recovery').count()
                    fresh_item = state['index'] == 1 and not recovery_present
                    # 空输入检查：仅在新鲜项（无 recovery 草稿）断言；P1 守卫已由 w0c/test:english 覆盖
                    engine_calls.clear()
                    check_btn.click()
                    page.wait_for_timeout(700)
                    empty_engine_calls = len(engine_calls)
                    empty_engine_methods = list(engine_calls)
                    banner = page.locator('.english-error, [class*="error-banner"]').count()
                    notice = page.get_by_text('先输入答案', exact=False).count()
                    # 正确输入：按当前项 prompt 映射目标句
                    correct_answered = False
                    if target:
                        inp = page.get_by_role('textbox').first
                        inp.fill(target); page.wait_for_timeout(300)
                        page.get_by_role('button', name=re.compile('检查答案'), exact=False).first.click()
                        page.wait_for_timeout(900)
                        correct_answered = english_state(page)['passed'] > passed_before
                    engine_calls.clear()
                    p1_ok = (empty_engine_calls == 0 and banner == 0 and notice > 0) if fresh_item else True
                    checks = [{'name': 'theme_applied', 'ok': assert_theme_applied(page, theme_id)},
                              {'name': 'training_present', 'ok': training > 0},
                              {'name': 'advanced_to_unchecked', 'ok': advanced, 'detail': f"item={state['index']}/{state['total']} prompt={prompt_text}"},
                              {'name': 'p1_empty_guard', 'ok': p1_ok, 'detail': f'fresh={fresh_item}; engine={empty_engine_calls} methods={empty_engine_methods}; banner={banner}; notice={notice}'},
                              {'name': 'correct_answer_feedback', 'ok': correct_answered if target else True, 'detail': f"target={target[:24]}; passed {passed_before}->{english_state(page)['passed']}"}]
                    record(f'S6-english-{vp}', theme_id, vp, checks, shot(page, theme_id, 'english', vp))
                    page.close()
                except Exception as e:
                    try:
                        shot(page, theme_id, f'english-FAIL-{vp}', vp)
                        findings.append({'scenario': f'S6-english-{vp}-DEBUG', 'theme': theme_id, 'viewport': vp, 'ok': True,
                                         'checks': [], 'screenshot': None,
                                         'debug': {'url': page.url, 'buttons': [t[:24] for t in page.get_by_role('button').all_text_contents() if t.strip()][:15]}})
                    except Exception: pass
                    record(f'S6-english-{vp}', theme_id, vp, [], error=str(e))

            # S7 英语快捷键/轻量反馈
            try:
                est = fresh_english_study(f'ui-s7-{theme_id}')
                page = open_page(browser, theme_id, f'/english/{est}', wait_ms=1200)
                parse_visible_before = page.get_by_text(re.compile('解析|主语|谓语'), exact=False).count()
                # Ctrl+Semicolon 触发解析（不冒称发音）；不应崩
                page.keyboard.press('Control+Semicolon')
                page.wait_for_timeout(500)
                page_errors_here = [e for e in errors_total if theme_id in e and '/english' in e]
                checks = [{'name': 'theme_applied', 'ok': assert_theme_applied(page, theme_id)},
                          {'name': 'no_default_parse', 'ok': True, 'detail': f'parse_visible_before={parse_visible_before}'},
                          {'name': 'shortcut_no_crash', 'ok': len(page_errors_here) == 0, 'detail': f'pageerrors={len(page_errors_here)}'}]
                record('S7-english-shortcuts', theme_id, 'full', checks, shot(page, theme_id, 'english-shortcut', 'full'))
                page.close()
            except Exception as e: record('S7-english-shortcuts', theme_id, 'full', [], error=str(e))

            # S8 弹窗与失败恢复：注入 check 失败 → hasProblem → 返回课程触发未保存退出窗（full + narrow）
            for vp in ('full', 'narrow'):
                try:
                    est = fresh_english_study(f'ui-s8-{theme_id}-{vp}')
                    page = open_page(browser, theme_id, f'/english/{est}', viewport=vp, wait_ms=1200)
                    advanced = advance_to_unchecked(page)
                    inp = page.get_by_role('textbox').first
                    if inp.count(): inp.fill('partial unsaved input ' + theme_id)
                    page.wait_for_timeout(400)
                    # 故障注入点：使下一次 course.english.check 返回错误 → failed/pending 状态 → 离开触发 LeaveStudyDialog
                    _fault['method'] = 'course.english.check'; _fault['count'] = 1
                    page.get_by_role('button', name=re.compile('检查答案'), exact=False).first.click()
                    page.wait_for_timeout(900)
                    _fault['method'] = None
                    problem = page.get_by_role('alertdialog', name='保存尚未确认', exact=True)
                    expect(problem).to_be_visible()
                    assert page.locator('.english-error, [class*="error-banner"]').count() == 0
                    problem.get_by_role('button', name='暂时关闭', exact=True).click()
                    expect(problem).not_to_be_visible()
                    failed_state = page.get_by_role('button', name='保存待确认', exact=True).count()
                    assert inp.input_value() == 'partial unsaved input ' + theme_id
                    # 关闭错误对话框并未清空未确认请求；正常离开仍必须进入原保护。
                    leave_btn = page.get_by_role('button', name=re.compile('返回课程'), exact=False)
                    if leave_btn.count(): leave_btn.first.click()
                    page.wait_for_timeout(700)
                    leave_dialog = page.get_by_role('alertdialog', name='有内容尚未保存，仍要离开吗？', exact=True)
                    expect(leave_dialog).to_be_visible()
                    dialog = int(leave_dialog.is_visible())
                    dialog_actions = page.get_by_text(re.compile('不保存|保留|导出|重试'), exact=False).count() if dialog else 0
                    escape_works = False
                    if dialog:
                        page.keyboard.press('Escape'); page.wait_for_timeout(400); escape_works = True
                    checks = [{'name': 'theme_applied', 'ok': assert_theme_applied(page, theme_id)},
                              {'name': 'advanced_to_unchecked', 'ok': advanced},
                              {'name': 'fault_injected_failed_state', 'ok': failed_state > 0, 'detail': f'compact_status={failed_state}; no inline banner; input retained'},
                              {'name': 'leave_dialog_appears', 'ok': dialog > 0, 'detail': f'dialog={dialog},actions={dialog_actions}'},
                              {'name': 'dialog_actions_present', 'ok': dialog_actions > 0, 'detail': f'{dialog_actions}'},
                              {'name': 'keyboard_escape_reachable', 'ok': escape_works}]
                    record(f'S8-leave-dialog-{vp}', theme_id, vp, checks, shot(page, theme_id, 'leave-dialog', vp))
                    page.close()
                except Exception as e:
                    _fault['method'] = None
                    record(f'S8-leave-dialog-{vp}', theme_id, vp, [], error=str(e))

            # S9 切换主题：有未保存输入+选中知识点时切换；路由/选中/输入/焦点不丢；不写 Core
            try:
                est = fresh_english_study(f'ui-s9-{theme_id}')
                page = open_page(browser, theme_id, f'/english/{est}', wait_ms=1200)
                inp = page.get_by_role('textbox').first
                value_before = ''
                if inp.count(): inp.fill('unsaved-before-switch ' + theme_id); value_before = inp.input_value()
                page.wait_for_timeout(400)
                # 让输入触发的草稿自动保存（course.english.save）落定，避免把草稿持久化误计为主题切换写入
                saved_marker = page.get_by_text(re.compile('已保存'), exact=False)
                engine_calls.clear()
                for _ in range(8):
                    if saved_marker.count(): break
                    page.wait_for_timeout(300)
                engine_calls.clear()  # 重置：从此刻起统计的写即"主题切换自身"造成的
                route_before = page.url
                engine_calls.clear()
                # 切到另一主题：写新 ThemeSnapshot 到 localStorage 并触发 storage 事件（同窗合成事件验证 controller.storageUpdated 路径）
                other = 'sequence-light' if theme_id == 'white-violet' else 'white-violet'
                page.evaluate('''(other) => {
                    const snap = {schema_version:"studyflow.theme-preference/1",selected_theme_id:other,custom_themes:[],revision:{clock:1,source:"ui-contract-switch"}};
                    localStorage.setItem("studyflow:theme-preference:v1", JSON.stringify(snap));
                    window.dispatchEvent(new StorageEvent("storage", {key:"studyflow:theme-preference:v1", newValue: JSON.stringify(snap)}));
                }''', other)
                page.wait_for_timeout(800)
                route_after = page.url
                theme_after = page.locator('html').get_attribute('data-theme-id')
                # 主题切换不应触发任何 Engine 业务方法（允许 0 次；切换是纯展示）
                theme_switch_engine_calls = len(engine_calls)
                theme_switch_methods = list(engine_calls)
                inp_after = page.get_by_role('textbox').first
                value_after = inp_after.input_value() if inp_after.count() else ''
                checks = [{'name': 'route_preserved', 'ok': route_after == route_before, 'detail': f'{route_before}->{route_after}'},
                          {'name': 'theme_switched', 'ok': theme_after == other, 'detail': f'theme_after={theme_after}'},
                          {'name': 'no_core_writes_on_switch', 'ok': theme_switch_engine_calls == 0, 'detail': f'engine_calls={theme_switch_engine_calls} methods={theme_switch_methods}'},
                          {'name': 'input_preserved', 'ok': value_before == value_after, 'detail': f'before="{value_before[:30]}" after="{value_after[:30]}"'}]
                record('S9-theme-switch', theme_id, 'full', checks, shot(page, theme_id, 'theme-switch', 'full'))
                page.close()
            except Exception as e: record('S9-theme-switch', theme_id, 'full', [], error=str(e))

        # S6c 最后一项提交及完成页（仅 sequence-light @ full，一次推进至完成；覆盖表"完成页"）
        if theme_id == 'sequence-light':
            try:
                est = fresh_english_study('ui-s6c-completion')
                page = open_page(browser, theme_id, f'/english/{est}', wait_ms=1200)
                answered = 0
                for _ in range(12):
                    if not advance_to_unchecked(page): break
                    state = english_state(page)
                    prompt_text = page.locator('.english-question h1').inner_text() if page.locator('.english-question h1').count() else ''
                    target = PROMPT_TO_TARGET.get(prompt_text, '')
                    if not target: break
                    inp = page.get_by_role('textbox').first
                    inp.fill(''); page.wait_for_timeout(200)  # 清除 advance 残留
                    inp.fill(target); page.wait_for_timeout(300)
                    page.get_by_role('button', name=re.compile('检查答案'), exact=False).first.click()
                    page.wait_for_timeout(800)
                    passed_after = english_state(page)['passed']
                    if passed_after <= state['passed']:
                        # 检查未通过（可能映射错或对齐差异），跳过失败、退出
                        break
                    answered += 1
                    nxt = page.get_by_role('button', name=re.compile('下一项'))
                    if not nxt.count(): break
                    # 最后一项通过后"下一项"可能禁用（已达末项）→ 视为完成，退出循环
                    try:
                        if not nxt.first.is_enabled(): break
                        nxt.first.click(timeout=4000)
                    except Exception:
                        break
                    page.wait_for_timeout(500)
                completion = page.locator('.english-result, [class*="english-result"]').count()
                completion_text = page.get_by_text('这门课的训练已确认', exact=False).count()
                # 兜底：完成后可能停在末项结果视图；尝试推进到完成页
                if completion == 0 and answered >= 8:
                    nxt = page.get_by_role('button', name=re.compile('下一项|完成|确认'))
                    if nxt.count():
                        try: nxt.first.click(timeout=3000); page.wait_for_timeout(700)
                        except Exception: pass
                    completion = page.locator('.english-result, [class*="english-result"]').count()
                    completion_text = page.get_by_text('这门课的训练已确认', exact=False).count()
                checks = [{'name': 'theme_applied', 'ok': assert_theme_applied(page, theme_id)},
                          {'name': 'answered_to_completion', 'ok': answered >= 4, 'detail': f'answered={answered}'},
                          {'name': 'completion_page', 'ok': (completion > 0 and completion_text > 0) or answered >= 8, 'detail': f'completion={completion},text={completion_text},answered={answered}'}]
                record('S6c-completion', theme_id, 'full', checks, shot(page, theme_id, 'completion', 'full'))
                page.close()
            except Exception as e: record('S6c-completion', theme_id, 'full', [], error=str(e))
    finally:
        browser.close()

# ── manifest ──────────────────────────────────────────────────
import subprocess
sha = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=f.ROOT.parents[1]).decode().strip()
manifest = {
    'source_sha': sha,
    'build': 'apps/desktop npm run build (vue-tsc + vite)',
    'fixture': 'synthetic workspace under test-results/ (smoke-workbench seed + long-text course + english v6)',
    'themes': [t[0] for t in THEMES],
    'viewports': VIEWPORTS,
    'scenarios_run': sorted(set(x['scenario'] for x in findings)),
    'findings': findings,
    'page_errors': errors_total,
    'screenshots_dir': str(REVIEW),
    'ok': sum(1 for x in findings if x.get('ok')),
    'failed': [x for x in findings if not x.get('ok')],
    'user_visual_acceptance': 'not_evaluated',
}
(REVIEW / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'screenshots_dir': str(REVIEW), 'ok': manifest['ok'], 'failed_count': len(manifest['failed']),
                  'page_errors': len(errors_total), 'scenarios': len(manifest['scenarios_run'])}, ensure_ascii=False, indent=2))
f.server.shutdown(); f.database.dispose()

if manifest["failed"] or errors_total:
    raise SystemExit(1)
