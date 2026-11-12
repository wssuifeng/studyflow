"""内置主题「国风朱红」真实 Vue + 真实 Core 浏览器核验。
仅合成数据与临时 loopback；国风朱红已提升为内置主题，通过设置页直接选择应用，
验证跨窗同步、学习状态保留、字体落地、装饰资产与窄窗行为，并截图留证。
运行：PYTHONPATH=<core/src>;<core venv site-packages> python scripts/smoke-cinnabar-paper.py
"""
import copy, json, time
from pathlib import Path
from typer.testing import CliRunner
from playwright.sync_api import sync_playwright, expect
import smoke_workbench_support as f
from studyflow.cli import app
from studyflow.interfaces.cli import runtime

BUILTIN = f.ROOT / 'src/shared/themes/builtin/cinnabar-paper.json'
EXAMPLES = f.ROOT.parents[1] / 'skills/studyflow-agent/examples'
EVIDENCE = f.ROOT / 'test-results/cinnabar-paper-20261112'
EVIDENCE.mkdir(parents=True, exist_ok=True)
checks = []
errors = []
requests = []


def check(name, condition, detail=''):
    checks.append({'name': name, 'passed': bool(condition), 'detail': str(detail)[:300]})
    if not condition:
        raise AssertionError(f'{name}: {detail}')


def import_package(filename, package_id, title=None):
    package = json.loads((EXAMPLES / filename).read_text(encoding='utf-8'))
    package['package_id'] = package_id
    package['plan_line'] = f.plan.name
    if title:
        package['course']['title'] = title
    file = f.WORKSPACE / f'{package_id}.json'
    file.write_text(json.dumps(package, ensure_ascii=False), encoding='utf-8')
    original = runtime.service
    runtime.service = lambda: f.service
    try:
        result = CliRunner().invoke(app, ['course', 'import-package', '--file', str(file), '--format', 'json'])
        assert result.exit_code == 0, result.output
        return json.loads(result.stdout)['course_id']
    finally:
        runtime.service = original


def main():
    package = json.loads((EXAMPLES / 'course-package.json').read_text(encoding='utf-8'))
    package['package_id'] = 'cinnabar-demo'
    package['plan_line'] = f.plan.name
    package['course']['title'] = '合成主题验证课程'
    lesson = package['lessons'][0]
    lesson['title'] = '计算机系统 · 七种教学组件'
    lesson['blocks'][0]['title'] = 'CPU 的职责与边界'
    lesson['blocks'][0]['body'] = 'CPU 负责执行指令，**程序计数器 PC** 指向下一条指令的地址。\n\n' + '\n\n'.join(
        '这是纯合成的长正文，用于验证内置主题下中文阅读位置、编辑状态和组件层次保持不变。' for _ in range(8))
    lesson['blocks'][2]['items'].extend([{'title': '译码', 'body': '识别指令和操作数。'}, {'title': '执行', 'body': '执行指令，再推进到下一条指令。'}])
    lesson['blocks'][3]['given'] = '程序计数器 PC 的初始值为 8。\n\n```java\nint pc = 8;\npc += 4;\n```'
    lesson['blocks'][4]['body'] = '地址不是指令本身。反馈颜色只表达状态，不改变题目、轮次或学习记录。'
    next_lesson = copy.deepcopy(lesson)
    next_lesson['id'] = 'memory'
    next_lesson['title'] = '存储与地址'
    package['lessons'].append(next_lesson)
    file = f.WORKSPACE / 'cinnabar-demo.json'
    file.write_text(json.dumps(package, ensure_ascii=False), encoding='utf-8')
    original = runtime.service
    runtime.service = lambda: f.service
    try:
        result = CliRunner().invoke(app, ['course', 'import-package', '--file', str(file), '--format', 'json'])
        assert result.exit_code == 0, result.output
        course = json.loads(result.stdout)['course_id']
    finally:
        runtime.service = original
    english_course = import_package('english-course-package-v6.json', 'cinnabar-english-demo', '合成英语训练课程')

    methods = []
    original_handle = f.engine.handle

    def tracked(request):
        methods.append(request.get('method'))
        return original_handle(request)

    f.engine.handle = tracked
    tokens = json.loads(BUILTIN.read_text(encoding='utf-8'))['tokens']

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000})
        page = context.new_page()
        peer = context.new_page()
        for tab in (page, peer):
            tab.set_default_timeout(15000)
            tab.on('pageerror', lambda error: errors.append(str(error)))
            tab.on('request', lambda request: requests.append((request.url, request.resource_type)))
        try:
            # 0) 主窗先加载真实课程（默认白紫），设置窗随后直选内置国风朱红，验证跨窗同步到学习中的页面。
            page.goto(f.url + '/#/course/' + course)
            page.wait_for_load_state('networkidle')
            expect(page.locator('.teaching-block')).to_have_count(7)
            check('选择前课程页以默认白紫渲染七教学块', page.locator('html').get_attribute('data-theme-id') == 'white-violet')

            # 1) 选择前：内置目录已含三套主题（序光/白紫/国风朱红），默认白紫。
            peer.goto(f.url + '/#/settings')
            peer.wait_for_load_state('networkidle')
            expect(peer.locator('.theme-option')).to_have_count(3)
            check('内置主题含序光、白紫与国风朱红', peer.locator('.theme-option').count() == 3)
            check('默认主题为白紫', peer.locator('html').get_attribute('data-theme-id') == 'white-violet')

            # 2) 通过设置页直接选择内置国风朱红卡片（无需导入）。
            peer.locator('.theme-option').filter(has_text='国风朱红').click()
            expect(peer.locator('html')).to_have_attribute('data-theme-id', 'cinnabar-paper')
            expect(page.locator('html')).to_have_attribute('data-theme-id', 'cinnabar-paper')
            expect(peer.locator('.theme-option')).to_have_count(3)
            card = peer.locator('.theme-option').filter(has_text='国风朱红')
            check('内置主题经直选应用并跨窗同步', True)
            check('内置卡片不标记本地导入', '本地导入' not in card.inner_text())
            peer.screenshot(path=str(EVIDENCE / '03-settings-theme.png'))

            # 3) 令牌落地：根自定义属性与 JSON 一致（自定义属性保留原始色值字符串）。
            landed = page.evaluate("""() => {
                const root = getComputedStyle(document.documentElement);
                return Object.fromEntries(['--theme-surface-canvas','--theme-surface-panel','--theme-accent-primary','--theme-text-primary','--theme-text-muted','--theme-radius','--theme-nav-width','--theme-reading-width'].map(k => [k, root.getPropertyValue(k).trim()]));
            }""")
            check('画布/面板/朱砂/墨色令牌落地', landed['--theme-surface-canvas'] == tokens['surface.canvas'] and landed['--theme-surface-panel'] == tokens['surface.panel'] and landed['--theme-accent-primary'] == tokens['accent.primary'] and landed['--theme-text-primary'] == tokens['text.primary'], landed)
            check('展示包几何落地（圆角6/导航252/阅读900）', landed['--theme-radius'] == '6px' and landed['--theme-nav-width'] == '252px' and landed['--theme-reading-width'] == '900px', landed)

            # 4) 字体落地：思源宋体标题 + 思源黑体正文（本机已安装族名）。
            fonts = page.evaluate("""() => ({
                serif: document.fonts.check('700 30px "Noto Serif SC"'),
                sans: document.fonts.check('15px "Noto Sans SC"'),
                heading: getComputedStyle(document.documentElement).getPropertyValue('--theme-heading-font'),
                body: getComputedStyle(document.documentElement).getPropertyValue('--theme-body-font')
            })""")
            check('思源宋体/黑体真实可用且进入字族栈', fonts['serif'] and fonts['sans'] and 'Noto Serif SC' in fonts['heading'] and 'Noto Sans SC' in fonts['body'], fonts)

            # 5) 课程阅读面：七教学块、印章插画、回纹侧栏、签名落款。
            page.goto(f.url + '/#/course/' + course)
            page.wait_for_load_state('networkidle')
            expect(page.locator('.teaching-block')).to_have_count(7)
            check('结构化课程七教学块渲染', page.locator('.teaching-block').count() == 7)
            page.wait_for_timeout(400)
            seal = page.evaluate("""() => {
                const img = document.querySelector('.theme-reading-artwork img');
                return img ? { width: img.naturalWidth, visible: img.getBoundingClientRect().width > 0 } : null;
            }""")
            check('题首朱文方印真实加载', seal and seal['width'] > 0 and seal['visible'], seal)
            sidebar = page.evaluate("""() => {
                const el = document.querySelector('.sidebar');
                const style = getComputedStyle(el);
                const after = getComputedStyle(el, '::after');
                const signature = document.querySelector('.sidebar-signature');
                return {
                    texture: style.getPropertyValue('--sidebar-landscape').trim(),
                    afterImage: after.backgroundImage,
                    signature: signature ? getComputedStyle(signature, '::after').content : '',
                    svgVisible: getComputedStyle(document.querySelector('.nav-icon-svg')).display !== 'none',
                    glyphHidden: getComputedStyle(document.querySelector('.nav-icon-glyph')).display === 'none'
                };
            }""")
            check('回纹锦绫资产接入侧栏装饰槽', sidebar['texture'].startswith('url(') and sidebar['afterImage'] != 'none', sidebar)
            check('签名落款「朱红 · 开卷有益」', '朱红' in sidebar['signature'], sidebar['signature'])
            check('线描SVG图标启用、字形variant隐藏', sidebar['svgVisible'] and sidebar['glyphHidden'], sidebar)
            heading_font = page.locator('.study-unit-heading h3').evaluate('el => getComputedStyle(el).fontFamily')
            check('知识点标题使用衬线字族', 'Noto Serif SC' in heading_font, heading_font)
            page.screenshot(path=str(EVIDENCE / '04-course-reader.png'))

            # 6) 工具面板：真实作答/笔记，主题切换不丢状态、不写 Core。
            sid = f.service.course_detail(course)['course']['study_session_id']
            page.get_by_role('button', name='打开答题与笔记', exact=True).click()
            answer = page.locator('.knowledge-question textarea').first
            answer.fill('合成答案：内置主题核验，尚未提交。')
            page.get_by_role('tab', name='笔记').click()
            # 笔记v2为连续Tiptap编辑面（无旧版“＋ 写笔记”入口），直接输入真实内容。
            note = page.get_by_role('textbox', name='连续笔记编辑器')
            note.click()
            page.keyboard.type('合成笔记：国风朱红不应创建新的编辑器。')
            page.wait_for_timeout(800)
            body = page.locator('.study-material-body')
            body.evaluate('el => { el.scrollTop = 210; el.dispatchEvent(new Event("scroll")) }')
            before_scroll = body.evaluate('el => el.scrollTop')
            page.screenshot(path=str(EVIDENCE / '05-course-panel-open.png'))
            # 等待输入触发的自动保存 debounce 落定，避免把既有草稿保存误计为主题切换写入。
            last = len(methods)
            stable = 0
            while stable < 3:
                time.sleep(0.3)
                cur = len(methods)
                if cur == last:
                    stable += 1
                else:
                    stable = 0
                    last = cur
            writes_before = len([m for m in methods if m.endswith(('.save', '.submit', '.create', '.write', '.update'))])
            for theme_id in ('white-violet', 'cinnabar-paper'):
                peer.locator('.theme-option').filter(has_text={'white-violet': '白紫轻学', 'cinnabar-paper': '国风朱红'}[theme_id]).click()
                expect(page.locator('html')).to_have_attribute('data-theme-id', theme_id)
                expect(peer.locator('html')).to_have_attribute('data-theme-id', theme_id)
            page.get_by_role('tab', name='笔记').click()
            expect(note).to_contain_text('合成笔记：国风朱红不应创建新的编辑器。')
            check('主题往返切换保留笔记内容', True)
            page.get_by_role('tab', name='学习工具').click()
            expect(answer).to_have_value('合成答案：内置主题核验，尚未提交。')
            check('主题往返切换保留答案草稿', True)
            after_scroll = body.evaluate('el => el.scrollTop')
            check('主题切换保留阅读位置', abs(after_scroll - before_scroll) <= 2, (before_scroll, after_scroll))
            writes_after = len([m for m in methods if m.endswith(('.save', '.submit', '.create', '.write', '.update'))])
            current_sid = f.service.course_detail(course)['course']['study_session_id']
            check('主题切换不产生Core业务写入', current_sid == sid and writes_after == writes_before, {'sid': sid, 'current_sid': current_sid, 'writes_before': writes_before, 'writes_after': writes_after})
            page.screenshot(path=str(EVIDENCE / '10-cinnabar-after-roundtrip.png'))

            # 7) 普通页面与窄窗。
            page.goto(f.url + '/#/today')
            page.wait_for_load_state('networkidle')
            page.wait_for_timeout(800)
            page.screenshot(path=str(EVIDENCE / '01-today.png'), animations='disabled')
            check('学习控制台无横向溢出', page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1'))
            page.goto(f.url + '/#/plans')
            page.wait_for_load_state('networkidle')
            page.wait_for_timeout(800)
            page.screenshot(path=str(EVIDENCE / '02-plans.png'), animations='disabled')
            page.goto(f.url + '/#/course/' + course)
            page.wait_for_load_state('networkidle')
            page.set_viewport_size({'width': 1024, 'height': 768})
            page.wait_for_timeout(400)
            page.screenshot(path=str(EVIDENCE / '06-course-1024.png'))
            check('1024宽无横向溢出', page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1'))
            page.set_viewport_size({'width': 800, 'height': 900})
            page.wait_for_timeout(400)
            page.screenshot(path=str(EVIDENCE / '07-course-800.png'))
            check('800宽无横向溢出', page.evaluate('document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1'))
            page.goto(f.url + '/#/today')
            page.wait_for_load_state('networkidle')
            page.wait_for_timeout(800)
            page.screenshot(path=str(EVIDENCE / '08-today-800.png'), animations='disabled')
            page.set_viewport_size({'width': 1440, 'height': 1000})

            # 8) 英语专注训练页同主题渲染。真实入口经 course.study.open 取得学习会话ID，
            #    /english/<id> 的 id 是学习会话而非课程ID（与 EnglishCourseOverview 一致）。
            opened = f.engine.handle({'method': 'course.study.open', 'params': {'course_id': english_course, 'idempotency_key': 'cinnabar-english-open'}})
            english_study = (opened.get('data') or {}).get('study', {}).get('id')
            check('英语学习会话经真实入口开启', bool(english_study), str(opened)[:200])
            page.goto(f.url + '/#/english/' + english_study)
            page.wait_for_load_state('networkidle')
            page.wait_for_timeout(800)
            english_ok = page.locator('.english-learning').count() > 0
            check('英语训练页在内置主题下渲染', english_ok, page.locator('body').inner_text()[:200] if not english_ok else '')
            page.screenshot(path=str(EVIDENCE / '09-english.png'))

            # 9) 新上下文默认仍白紫；内置国风朱红不可移除（无移除入口），切回白紫后目录不变。
            fresh = browser.new_context(viewport={'width': 1280, 'height': 900})
            fresh_page = fresh.new_page()
            fresh_page.goto(f.url + '/#/settings')
            fresh_page.wait_for_load_state('networkidle')
            check('新窗口默认主题仍白紫', fresh_page.locator('html').get_attribute('data-theme-id') == 'white-violet')
            check('新窗口内置目录含国风朱红', fresh_page.locator('.theme-option').count() == 3)
            fresh.close()
            peer.locator('.theme-option').filter(has_text='国风朱红').click()
            expect(peer.locator('html')).to_have_attribute('data-theme-id', 'cinnabar-paper')
            check('内置主题无自定义移除入口', peer.get_by_role('button', name='移除此自定义主题', exact=True).count() == 0)
            peer.locator('.theme-option').filter(has_text='白紫轻学').click()
            expect(peer.locator('html')).to_have_attribute('data-theme-id', 'white-violet')
            expect(peer.locator('.theme-option')).to_have_count(3)
            check('切回白紫后内置目录不变', True)

            check('全程无页面错误', not errors, errors)
            # 主题资产必须全本地：样式/脚本/图片/字体不得有外部请求。
            # 英语页的词典发音（dictvoice）是既有产品功能，不属于主题资源，单独如实登记。
            external_assets = [u for u, t in requests if t in ('stylesheet', 'script', 'image', 'font') and not (u.startswith('http://127.0.0.1') or u.startswith('data:') or u.startswith('blob:'))]
            check('主题资产全本地（无外部样式/脚本/图片/字体请求）', not external_assets, external_assets[:5])
            audio = [u for u, t in requests if 'dictvoice' in u]
            checks.append({'name': '英语词典发音为既有产品功能（如实登记，非主题资源）', 'passed': True, 'detail': str(audio[:3])})
        except Exception:
            page.screenshot(path=str(EVIDENCE / 'failure.png'))
            peer.screenshot(path=str(EVIDENCE / 'failure-peer.png'))
            raise
        finally:
            browser.close()
    summary = {'checks': len(checks), 'passed': sum(1 for c in checks if c['passed']), 'page_errors': errors, 'evidence': str(EVIDENCE), 'details': checks}
    (EVIDENCE / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'checks': summary['checks'], 'passed': summary['passed'], 'page_errors': errors}, ensure_ascii=False))


if __name__ == '__main__':
    main()