"""Serialized real Core + Vue: 74-item typing, slow network, hints and reading."""
import argparse
import json
import mimetypes
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from fastapi.encoders import jsonable_encoder
from playwright.sync_api import sync_playwright, expect
from sqlalchemy.orm import sessionmaker
from studyflow.config import Settings
from studyflow.db import build_engine, init_db
from studyflow.engine import StudyFlowEngine
from studyflow.services import AppService
from studyflow.modules.audio.dictionary.provider import DictionaryProvider

parser = argparse.ArgumentParser()
parser.add_argument('--keyboard-asset', type=Path)
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'test-results' / 'training-comfort-20261013'
RESULTS.mkdir(parents=True, exist_ok=True)
workspace = Path(tempfile.mkdtemp(prefix='synthetic-', dir=RESULTS))
settings = Settings(workspace_root=workspace, database_url='sqlite:///' + (workspace / 'test.db').as_posix())
database = build_engine(settings)
init_db(database)
service = AppService(settings, sessionmaker(bind=database, autoflush=False, expire_on_commit=False))
service.create_plan_line('合成响应验证')
package = {'schema': 'studyflow.course-package/2', 'package_id': 'training-comfort', 'plan_line': '合成响应验证', 'course': {'title': '合成 · 74项响应验证', 'learning_mode': 'english'}, 'lessons': [{'id': 'word-group', 'title': '测试词组', 'blocks': [{'id': 'intro', 'type': 'concept', 'title': '测试说明', 'body': '这是软件响应测试，所有作答都是合成输入，不是用户学习记录。'}], 'exercises': [{'id': f'word-{i:02}', 'title': f'测试项{i:02}', 'prompt': f'输入测试单词 {i:02}', 'english': {'target': 'filter', 'objective_ids': ['synthetic-word']}} for i in range(1, 75)]}]}
source = workspace / 'english.json'
source.write_text(json.dumps(package, ensure_ascii=False), encoding='utf-8')
course = service.import_course_package(source)
reading_package = json.loads((ROOT.parents[1] / 'skills/studyflow-agent/examples/course-package-v5.json').read_text(encoding='utf-8'))
# Use Chinese prose and semantic components, not only a short English fixture.
reading_package['course']['title'] = '合成 · 处理器角色与执行过程'
reading_package['lessons'][0]['title'] = '处理器与指令执行 · 视觉样本'
concept = next(block for block in reading_package['lessons'][0]['blocks'] if block['type']=='concept')
concept['title'] = '建立角色，再串起过程'
concept['sections'][0]['title'] = '理解处理器、指令和存储的关系'
concept['sections'][0]['body'] = '处理器读取并执行指令，存储器保存程序和数据。学习这个关系时，先区分执行动作与保存内容，才能理解后续的信息流。\n\n指令说明一个要执行的操作；程序则由多条指令构成。把程序保存在存储器中，并不等于程序会自动运行，执行仍需要处理器参与。\n\n本例是合成的软件呈现样本，用于检查连续中文段落的行宽、层级和阅读字号，并不替代真实课程或学习记录。'
concept['sections'][1]['title'] = '进一步理解：从保存位置到执行动作'
concept['sections'][1]['summary'] = '先记住地址与内容的区别；展开后再看它们如何贯穿一次执行。'
concept['sections'][1]['body'] = '位置用于找到内容，内容则用于解释要完成的动作。两者经常同时出现，但回答的是不同问题。\n\n理解主线之后，再把寄存器、存储器和执行步骤联系起来，而不是一次背诵所有名字。'
service.create_plan_line(reading_package['plan_line'])
reading_source = workspace / 'reading.json'
reading_source.write_text(json.dumps(reading_package, ensure_ascii=False), encoding='utf-8')
reading = service.import_course_package(reading_source)
network_started, network_release, save_started = threading.Event(), threading.Event(), threading.Event()
def slow_dictionary(url):
    network_started.set()
    network_release.wait(4)
    return [{'phonetic': '/fɪltə/', 'meanings': []}]
service.audio.provider = DictionaryProvider(fetch=slow_dictionary)
engine = StudyFlowEngine(service=service)
lane = threading.Lock()
fault = {'delay_save': False}
measurements, errors, checks, transition_ms, screenshots = [], [], [], [], []
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        with lane:
            started = time.monotonic()
            if fault['delay_save'] and request['method'] == 'course.english.save':
                fault['delay_save'] = False
                save_started.set()
                time.sleep(.9)
            response = engine.handle(request)
            measurements.append({'method': request['method'], 'ms': round((time.monotonic()-started)*1000, 2), 'ok': response['ok'], 'error': response.get('error'), 'params': request.get('params')})
        content = json.dumps(jsonable_encoder(response), ensure_ascii=False).encode()
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            pass
    def do_GET(self):
        file = (ROOT/'dist'/urlsplit(self.path).path.lstrip('/')).resolve()
        if not file.is_relative_to((ROOT/'dist').resolve()):
            self.send_error(400)
            return
        if not file.is_file():
            file = ROOT/'dist/index.html'
        content = file.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f'http://127.0.0.1:{server.server_port}'
def preference(theme):
    return "localStorage.setItem('studyflow:theme-preference:v1'," + json.dumps(json.dumps({'schema_version': 'studyflow.theme-preference/1', 'selected_theme_id': theme, 'custom_themes': [], 'revision': {'clock': 1, 'source': 'synthetic'}})) + ");"
def screenshot(page, name):
    page.wait_for_timeout(450)
    page.screenshot(path=str(RESULTS/name))
    screenshots.append(name)
try:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel='msedge' if os.name=='nt' else None)
        page = browser.new_page(viewport={'width': 1920, 'height': 1080})
        page.add_init_script(preference('sequence-light'))
        page.add_init_script("window.__typingStarts=0;const Original=window.AudioContext;window.AudioContext=class extends Original{createBufferSource(){const source=super.createBufferSource(),start=source.start.bind(source);source.start=(...args)=>{window.__typingStarts++;return start(...args)};return source}};")
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('https://dict.youdao.com/**', lambda route: route.abort())
        page.goto(url+'/#/course/'+course['course_id'])
        page.get_by_role('button', name='开始 / 继续训练 →').click()
        expect(page.get_by_role('heading', name='输入测试单词 01', exact=True)).to_be_visible()
        word = page.get_by_role('textbox', name='第 1 个单词')
        word.press_sequentially('filter', delay=65)
        assert page.evaluate('window.__typingStarts') >= 3
        checks.append('typing_sound_receives_real_character_events')
        word.press('Enter')
        expect(page.locator('.english-target')).to_have_text('filter')
        assert network_started.wait(2), 'automatic word pronunciation did not request dictionary metadata'
        started = time.monotonic()
        page.get_by_role('button', name='下一项 →', exact=True).press('Control+Period')
        expect(page.get_by_role('heading', name='输入测试单词 02', exact=True)).to_be_visible(timeout=1500)
        transition_ms.append(round((time.monotonic()-started)*1000, 2))
        assert not network_release.is_set()
        assert not page.locator('.english-error').count()
        checks.append('slow_dictionary_does_not_hold_next_or_save')
        initial_sid = page.url.split('/english/')[1].split('?')[0]
        assert service.english.get(initial_sid)['items'][0]['matched']
        assert not service.english.get(initial_sid)['items'][0]['skipped']
        checks.append('next_shortcut_after_correct_answer_does_not_resave_or_mark_skipped')
        word = page.get_by_role('textbox', name='第 1 个单词')
        word.press("Control+Semicolon")
        expect(page.locator('.english-breakdown')).to_contain_text('filter')
        expect(word).to_be_focused();expect(word).to_be_enabled()
        assert page.locator('.english-answer').count() == 0
        screenshot(page,'sequence-explicit-analysis-1920.png')
        word.fill('filt');expect(word).to_have_value('filt')
        expect(page.locator('.english-breakdown')).to_contain_text('filter')
        word.press('Control+Quote')
        expect(word).to_have_value('filt');expect(word).to_be_focused()
        checks.append('analysis_and_audio_shortcuts_preserve_input_and_focus')
        page.get_by_role('button', name='笔记', exact=True).click()
        note = page.get_by_role('textbox', name='连续笔记编辑器', exact=True)
        note.click()
        reveal_count = sum(m['method']=='course.english.reveal' for m in measurements)
        page.keyboard.press('Control+Quote')
        page.wait_for_timeout(150)
        assert reveal_count == sum(m['method']=='course.english.reveal' for m in measurements)
        page.get_by_role('button', name='关闭侧栏', exact=True).click()
        checks.append('training_shortcuts_do_not_capture_notebook_input')
        fault['delay_save'] = True
        word.fill('f')
        assert save_started.wait(2)
        expect(word).to_be_enabled()
        expect(word).to_be_focused()
        word.press_sequentially('ilter', delay=35)
        word.press('Control+Period')
        expect(page.get_by_role('heading', name='输入测试单词 03', exact=True)).to_be_visible(timeout=3000)
        sid = page.url.split('/english/')[1].split('?')[0]
        row = service.english.get(sid)['items'][1]
        assert row['answer_text'] == 'filter', row
        assert row['assisted'] and row['skipped']
        assert not page.locator('.english-error').count()
        checks.append('editing_during_autosave_and_skip_keep_latest_text')
        for number in range(3, 13):
            word = page.get_by_role('textbox', name='第 1 个单词')
            started = time.monotonic()
            word.fill('filter')
            word.press('Control+Period')
            expect(page.get_by_role('heading', name=f'输入测试单词 {number+1:02}', exact=True)).to_be_visible(timeout=1500)
            transition_ms.append(round((time.monotonic()-started)*1000, 2))
        checks.append('74_item_course_multiple_successive_transitions')
        assert max(transition_ms) < 1500
        metadata = [m for m in measurements if m['method']=='audio.dictionary.lookup']
        assert metadata and max(m['ms'] for m in metadata) < 150, metadata
        checks.append('serialized_engine_dictionary_request_below_150ms')
        page.get_by_role('button', name='训练设置', exact=True).click()
        if args.keyboard_asset:
            page.locator('input[type=file]').set_input_files(str(args.keyboard_asset.resolve()))
            expect(page.get_by_text('已使用本地键音，不会上传或访问网络。', exact=True)).to_be_visible()
            assert 'typing.mp3' in page.evaluate("JSON.parse(localStorage.getItem('studyflow:english-keyboard:v1')).name")
            checks.append('original_sound_import_is_local_and_decodable')
        screenshot(page, 'keyboard-and-shortcut-settings-1920.png')
        for theme in ['sequence-light', 'white-violet']:
            reading_page = browser.new_page(viewport={'width':1920,'height':1080})
            reading_page.add_init_script(preference(theme))
            reading_page.on('pageerror', lambda error: errors.append(str(error)))
            reading_page.goto(url+'/#/course/'+reading['course_id'])
            expect(reading_page.locator('.document-template')).to_be_visible()
            metrics = reading_page.locator('.document-template').evaluate("el=>({width:el.getBoundingClientRect().width,font:getComputedStyle(el.querySelector('.teaching-richtext')).fontSize})")
            assert metrics['width'] <= 742, metrics
            reading_page.locator('.study-material').evaluate("el=>el.style.setProperty('--reading-font','18px')")
            assert reading_page.locator('.teaching-richtext').first.evaluate('el=>getComputedStyle(el).fontSize') == '18px'
            screenshot(reading_page, theme+'-reading-comfort-1920.png')
            checks.append(theme+'_reading_width_and_font_preference')
            for button in reading_page.locator('.course-navigation-action').all():
                expect(button).to_have_css('background-color','rgba(0, 0, 0, 0)')
                expect(button).to_have_css('border-radius','8px')
                assert button.bounding_box()['height'] >= 32
                button.hover()
                reading_page.wait_for_timeout(200)
                assert button.evaluate('el=>getComputedStyle(el).backgroundColor') != 'rgba(0, 0, 0, 0)'
                reading_page.mouse.move(1900,1060)
                reading_page.wait_for_timeout(200)
            reading_page.keyboard.press('Tab')
            back=reading_page.locator('.sequence-return');back.focus()
            expect(back).to_be_focused();expect(back).to_have_css('outline-style','solid')
            screenshot(reading_page,theme+'-navigation-focus-1920.png')
            reading_page.locator('.teaching-block-heading').first.click()
            reading_page.mouse.move(1900,1060)
            checks.append(theme+'_return_buttons_transparent_hover_and_keyboard_focus')
            summary = reading_page.locator('.section-supplement').first
            assert summary.get_attribute('open') is None
            expect(summary.locator('.section-summary')).to_contain_text('地址与内容')
            summary.locator('summary').click()
            expect(summary.locator('.section-detail')).to_be_visible()
            screenshot(reading_page, theme+'-reading-expanded-1920.png')
            summary.locator('summary').click()
            reading_page.locator('.tools-toggle').click()
            screenshot(reading_page, theme+'-reading-tools-1920.png')
            reading_page.locator('.tools-toggle').click()
            checks.append(theme+'_fold_and_tools_preserve_continuous_reading')
            reading_page.get_by_role('tab',name='本节大纲',exact=True).click()
            heading_link=reading_page.locator('.sequence-outline-list .section-link').last
            heading_link.click();reading_page.wait_for_timeout(500)
            expect(reading_page.get_by_role('heading',name=heading_link.inner_text().strip(),exact=True)).to_be_in_viewport()
            outline_debug=reading_page.evaluate("()=>({links:[...document.querySelectorAll('.section-link')].map(x=>({text:x.textContent,current:x.getAttribute('aria-current')})),panes:[...document.querySelectorAll('.study-material-body,.study-material,.document-template')].map(x=>({class:x.className,top:x.scrollTop,height:x.clientHeight,scrollHeight:x.scrollHeight,overflow:getComputedStyle(x).overflowY})),headings:[...document.querySelectorAll('[data-outline-level]')].map(x=>({id:x.id,text:x.textContent,top:x.getBoundingClientRect().top}))})")
            (RESULTS/(theme+'-outline-debug.json')).write_text(json.dumps(outline_debug,ensure_ascii=False,indent=2),encoding='utf-8')
            screenshot(reading_page,theme+'-outline-click-1920.png')
            assert reading_page.locator('.study-material-body').evaluate('el=>el.scrollTop') > 0,outline_debug
            reading_page.get_by_role('tab',name='课程大纲',exact=True).click()
            checks.append(theme+'_actual_outline_button_scrolls_to_heading')
            reading_page.set_viewport_size({'width':900,'height':800})
            assert reading_page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
            screenshot(reading_page, theme+'-reading-comfort-900.png')
            checks.append(theme+'_narrow_reading_without_root_overflow')
            reading_page.set_viewport_size({'width':1920,'height':1080})
            reading_page.locator('.sequence-return').click();reading_page.wait_for_url('**/#/plan/*')
            expect(reading_page.locator('.document-template')).to_have_count(0)
            reading_page.goto(url+'/#/course/'+reading['course_id'])
            expect(reading_page.locator('.document-template')).to_be_visible()
            if theme=='sequence-light':
                reading_page.locator('.sequence-exit').click();reading_page.wait_for_url('**/#/plan/*')
                expect(reading_page.locator('.document-template')).to_have_count(0)
            checks.append(theme+'_return_controls_keep_existing_navigation')
            reading_page.close()
        browser.close()
    assert not errors, errors
    result = {'ok':True,'checks':checks,'page_errors':errors,'transition_ms':transition_ms,'dictionary_ms':metadata,'screenshots':screenshots,'workspace':str(workspace),'scope':'synthetic-only','business_acceptance':'not_evaluated'}
    (RESULTS/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
finally:
    (workspace/"requests.json").write_text(json.dumps(measurements,ensure_ascii=False,indent=2),encoding="utf-8")
    print("COMFORT_WORKSPACE",workspace)
    network_release.set()
    service.audio.provider.close()
    server.shutdown()
    engine.close()
    database.dispose()
