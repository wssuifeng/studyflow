"""Exercise mixed and standalone English courses in the production Tauri webview."""
import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import re
from threading import Thread
import time
import uuid
import wave

from playwright.sync_api import expect, sync_playwright

from rust_smoke_support import NativeCli, launch, window

ROOT = Path(__file__).resolve().parents[3]


@contextmanager
def simulated_supplier(seconds=4):
    data = BytesIO()
    with wave.open(data, 'wb') as file:
        file.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        file.writeframes(b'\x00\x00' * (8000 * seconds))
    audio = data.getvalue()
    requests = []

    class Supplier(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            assert self.path == '/v1/audio/speech'
            requests.append((self.headers.get('Authorization'), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            self.send_response(200)
            self.send_header('Content-Type', 'audio/wav')
            self.send_header('Content-Length', str(len(audio)))
            self.end_headers()
            self.wfile.write(audio)

    with ThreadingHTTPServer(('127.0.0.1', 0), Supplier) as supplier:
        server = Thread(target=supplier.serve_forever, daemon=True)
        server.start()
        try:
            yield f'http://127.0.0.1:{supplier.server_port}/v1/audio/speech', requests
        finally:
            supplier.shutdown()
            server.join()


def adopted_audio(cli):
    with simulated_supplier() as (endpoint, requests):
        profile = cli.call('speech.profile.save', {'profile_id':str(uuid.uuid4()), 'name':'Offline fixture', 'provider': 'compatible', 'endpoint':endpoint,
                               'model':'fixture', 'voice':'speaker', 'format':'wav', 'credential':'synthetic-smoke-key', 'expected_version':0})
        job = {'job_id':str(uuid.uuid4())}
        cli.call('speech.job.start', job | {'profile_id':profile['profile_id'], 'expected_profile_version':profile['version'], 'text':'Meet at the library. Bring your library card.'})
        deadline = time.monotonic() + 10
        while True:
            status = cli.call('speech.job.get', job)
            if status['status'] == 'ready':
                break
            assert status['status'] == 'running' and time.monotonic() < deadline, status
            time.sleep(0.05)
        adoption = cli.call('speech.asset.adopt', job)
    assert len(requests) == 1 and requests[0][0] == 'Bearer synthetic-smoke-key'
    return adoption['audio']


def wait_for_audio(audio):
    expect(audio).to_be_visible()
    deadline = time.monotonic() + 10
    while audio.evaluate('(element) => element.readyState') < 1:
        assert time.monotonic() < deadline, 'Audio did not load'
        time.sleep(0.1)


def verify_ui_speech(cli, settings):
    with simulated_supplier(seconds=1) as (endpoint, requests):
        profiles = settings.get_by_label('语音服务')
        profiles.select_option('new')
        settings.get_by_label('服务名称').fill('Native simulated service')
        settings.get_by_label('完整接口地址').fill(endpoint)
        settings.get_by_label('模型', exact=True).fill('fixture')
        settings.get_by_label('音色 ID').fill('speaker-one')
        settings.get_by_label('文件格式').select_option('wav')
        settings.get_by_label('API Key', exact=True).fill('fake-settings-smoke-key')
        settings.get_by_role('button', name='保存配置').click()
        expect(settings.get_by_text('配置已保存。生成音频后可试听。')).to_be_visible()
        assert not requests
        settings.get_by_role('button', name='测试并试听').click()
        wait_for_audio(settings.locator('audio'))
        assert len(requests) == 1 and requests[0][0] == 'Bearer fake-settings-smoke-key'
        settings.get_by_label('台词', exact=True).fill('Meet at the library.')
        settings.get_by_role('button', name='添加对话段').click()
        second = settings.get_by_role('group', name='第 2 段')
        second.get_by_label('台词', exact=True).fill('Bring your ticket.')
        second.get_by_label('音色覆盖').fill('speaker-two')
        settings.get_by_role('button', name='生成音频', exact=True).click()
        expect(settings.get_by_text('已生成 2 秒音频。', exact=True)).to_be_visible(timeout=12000)
        settings.get_by_role('button', name='采用为课程音频').click()
        reference = json.loads(settings.get_by_label('课程包的 audio 引用').input_value(timeout=10000))
        assert [data['voice'] for _, data in requests] == ['speaker-one', 'speaker-one', 'speaker-two']
    assert reference['format'] == 'wav' and isinstance(reference['sha256'], str) and len(reference['sha256']) == 64
    assert any(data['endpoint'] == endpoint and data['has_credential']
               for data in cli.call('speech.profile.list')['profiles'])


def main(desktop, workspace, evidence):
    cli = NativeCli(desktop, workspace, evidence)
    plan = cli.command('plan', 'create', '--name', 'Native English smoke')
    plan_id = plan['id']
    package = json.loads((ROOT / 'skills/studyflow-agent/examples/course-package-v8.json').read_text(encoding='utf-8'))
    package['plan_line'] = plan['name']
    reference = adopted_audio(cli)

    def publish(draft):
        path = evidence / (draft['package_id'] + '.json')
        path.write_text(json.dumps(draft, ensure_ascii=False), encoding='utf-8')
        return cli.command('course', 'import-package', '--file', path)['course_id']

    lesson = package['lessons'][0]
    reading, word, essay = lesson['exercises']
    sample = reading['reading']['questions'][0]
    listening = {'id': 'listen', 'title': 'Travel dialogue', 'type': 'LISTENING_GROUP', 'prompt': 'Listen carefully.',
                 'listening': {'title': 'Travel dialogue', 'transcript': 'Meet at the library. Bring your library card.',
                               'captions': [{'start': 0, 'end': 0.7, 'text': 'Meet at the library.'},
                                            {'start': 1.2, 'end': 4, 'text': 'Bring your library card.'}],
                               'audio': reference, 'questions': [
                                   {k: v for k, v in sample.items() if k != 'evidence'},
                                   {'id': 'cloze', 'prompt': 'Complete the sentence.',
                                    'parts': [{'text': 'Bring your '}, {'blank_id': 'b1'}, {'text': '.'}],
                                    'blanks': [{'id': 'b1', 'accepted': ['library card']}], 'explanation': 'Bring your library card.'}]}}
    lesson['exercises'] = [word, listening, reading, essay]
    lesson['blocks'][1]['exercise_ids'] = [item['id'] for item in lesson['exercises']]
    mixed_id = publish(package)
    standalone = {label: publish({**package, 'package_id': 'standalone-' + item['id'], 'course': {
        'title': label, 'learning_mode': 'english'}, 'lessons': [{**lesson, 'exercises': [item], 'blocks': lesson['blocks'][:1]}]})
        for label, item in [('Standalone listening', listening), ('Standalone reading', reading), ('Standalone essay', essay)]}

    legacy_ids = {}
    legacy_text = {'id': 'short', 'title': 'Meeting time', 'type': 'SHORT_ANSWER', 'prompt': 'When will we meet?'}
    legacy_reading = {**reading, 'reading': {**reading['reading'], 'questions': [sample]}}
    legacy_listening = {**listening, 'listening': {**listening['listening'], 'questions': [
        listening['listening']['questions'][0], {**listening['listening']['questions'][1],
        'blanks': [{'id': 'b1', 'accepted': ['card']}]}]}}
    legacy_listening['listening'].pop('captions')
    for label, exercises in [('Legacy mixed', [legacy_listening, legacy_text, legacy_reading, essay]),
                             ('Legacy essay', [essay]), ('Legacy reading', [legacy_reading]),
                             ('Legacy listening', [legacy_listening]), ('Theory course', [legacy_text])]:
        old = {**package, 'schema': 'studyflow.course-package/7', 'package_id': label.lower().replace(' ', '-'),
               'course': {'title': label}, 'lessons': [{**lesson, 'blocks': lesson['blocks'][:1], 'exercises': exercises}]}
        legacy_ids[label] = publish(old)
    words = json.loads((ROOT / 'skills/studyflow-agent/examples/english-course-package-v6.json').read_text(encoding='utf-8'))
    words['plan_line'] = plan['name']
    word_course = publish(words)
    preexisting = cli.call('course.study.open', {'course_id':legacy_ids['Legacy mixed'], 'plan_line_id':plan_id, 'idempotency_key':'pre-existing-theory-round'})
    study_id = preexisting['study']['id']
    seeded = next(exercise for exercise in preexisting['lessons'][0]['exercises'] if exercise['type'] == 'SHORT_ANSWER')
    cli.call('course.answers.draft.save', {'course_id':legacy_ids['Legacy mixed'], 'study_session_id':study_id,
             'answers':[{'exercise_id':seeded['id'], 'answer_text':'Existing draft at nine.'}], 'idempotency_key':'pre-existing-draft'})

    with sync_playwright() as runner, launch(desktop, workspace, evidence) as (endpoint, _process):
        browser = runner.chromium.connect_over_cdp(endpoint)
        page = window(browser)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        expect(page.get_by_role('heading', name='我的计划', exact=True)).to_be_visible(timeout=30000)
        expect(page.get_by_role('button', name='学习控制台', exact=True)).to_have_count(0)
        page.evaluate("location.hash = '/today'")
        expect(page).to_have_url(re.compile(r'#/plans$'))

        def open_course(title, course_id, *, legacy=False, theory=False, return_to_plan=False):
            route = '/plan/' + plan_id
            if not return_to_plan:
                page.evaluate('(route) => {location.hash = route}', route)
            row = page.locator('.path-list li').filter(has=page.get_by_role('heading', name=title, exact=True))
            try:
                row.get_by_role('button', name=re.compile(r'进入课程|查看内容与反馈|查看课程')).click(timeout=8000)
            except Exception:
                print(page.url, page.locator('body').inner_text()[:2800], flush=True)
                raise
            if theory:
                expect(page.locator('.study-material')).to_be_visible()
                return
            if legacy:
                expect(page).to_have_url(re.compile(r'/course/' + re.escape(course_id) + r'(?:\?|$)'))
            else:
                expect(page).to_have_url(re.compile(r'#/english/[^?]+$'))
            expect(page.get_by_role('region', name='英语专注训练')).to_be_visible()
            expect(page.get_by_role('button', name='打开答题与笔记')).to_have_count(0)
            expect(page.get_by_role('button', name='开始 / 继续训练')).to_have_count(0)

        open_course(words['course']['title'], word_course)
        expect(page.locator('.english-token-row input')).not_to_have_count(0)
        expect(page.get_by_role('button', name='检查答案')).to_be_visible()

        title = package['course']['title']
        open_course(title, mixed_id)
        token_inputs = page.locator('.english-token-row input')
        expect(token_inputs).to_have_count(5)
        for index, value in enumerate(['We', 'will', 'meet', 'at', 'nine']):
            token_inputs.nth(index).fill(value)
        page.get_by_role('button', name='检查答案').click()
        page.get_by_role('button', name='下一项 →', exact=True).click()
        stage = page.locator('main.english-stage')
        expect(stage.get_by_role('heading', name='Travel dialogue')).to_be_visible()
        current_number = stage.locator('.practice-index [aria-current="step"]')
        assert current_number.evaluate('''(button) => {
            const style = getComputedStyle(button);
            const next = getComputedStyle(button.nextElementSibling);
            return parseFloat(style.borderTopWidth) > 0 && style.backgroundColor !== next.backgroundColor;
        }''')
        toggle = stage.get_by_role('button', name='当前句', exact=True)
        captions = stage.get_by_role('group', name='听力当前句')
        expect(toggle).to_have_attribute('aria-pressed', 'false')
        expect(stage.get_by_text('Meet at the library.', exact=True)).to_have_count(0)
        toggle.press('Space')
        expect(captions).to_contain_text('播放音频后显示当前句。')
        caption_height = captions.bounding_box()['height']
        expect(toggle).to_have_attribute('aria-controls', re.compile(r'.+'))
        stage.get_by_role('button', name='播放音频').click()
        player = stage.locator('audio')
        wait_for_audio(player)
        expect(captions).to_have_text('Meet at the library.')
        expect(captions).to_have_text('Bring your library card.', timeout=5000)
        assert captions.bounding_box()['height'] == caption_height
        assert captions.evaluate('(el) => el.getAnimations().length') == 0
        player.evaluate('(audio) => { audio.pause(); audio.currentTime = 0.9 }')
        expect(captions).to_have_text('等待下一句…')
        player.evaluate('(audio) => { audio.currentTime = 2 }')
        expect(captions).to_have_text('Bring your library card.')
        toggle.click()
        expect(captions).to_be_hidden()
        toggle.click()
        expect(captions).to_have_text('Bring your library card.')
        page.screenshot(path=str(evidence / 'english-listening.png'))
        player.evaluate('(audio) => { audio.currentTime = 3.85; return audio.play() }')
        expect(captions).to_have_text('音频已播放完毕。')
        stage.get_by_role('button', name='从头重听').click()
        expect(captions).to_have_text('Meet at the library.')
        radio = stage.get_by_role('radio', name='B. At the library')
        radio.check()
        radio.press('Enter')
        blank = stage.get_by_role('textbox', name='填空 1')
        expect(toggle).to_have_attribute('aria-pressed', 'true')
        expect(player).to_be_visible()
        blank.fill('LiBrArY CaRd')
        page.get_by_role('button', name='返回学习计划', exact=True).click()
        open_course(title, mixed_id, return_to_plan=True)
        expect(blank).to_have_value('LiBrArY CaRd')
        expect(toggle).to_have_attribute('aria-pressed', 'false')
        expect(page.locator('.english-header-progress')).to_have_text('2 / 4')
        blank.press('Enter')
        expect(stage.get_by_text('答对 2 / 2 题')).to_be_visible()
        stage.get_by_role('button', name='继续下一项').click()
        expect(stage.get_by_text('The group will meet at the library at nine.')).to_be_visible()
        practice = stage.locator('.practice-workspace')
        original_width = practice.evaluate('(el) => el.style.maxWidth')
        practice.evaluate("(el) => {el.style.maxWidth = '440px'}")
        assert practice.locator('.practice-layout').evaluate(
            "(el) => getComputedStyle(el).gridTemplateColumns.split(' ').length") == 1
        practice.evaluate('(el, width) => {el.style.maxWidth = width}', original_width)
        expect(toggle).to_have_count(0)
        page.screenshot(path=str(evidence / 'english-reading.png'))
        radio.check()
        radio.press('Enter')
        blank.fill('THE LIBRARY')
        blank.press('Enter')
        expect(stage.get_by_text('答对 2 / 2 题')).to_be_visible()
        expect(stage.get_by_text('补全答对 1 / 1 空')).to_be_visible()
        stage.get_by_role('button', name='查看第 1 段依据').click()
        expect(stage.locator('[data-paragraph="p1"]')).to_be_focused()
        stage.get_by_role('button', name='继续下一项').click()
        writing = stage.get_by_role('region', name='写作练习', exact=True)
        expect(writing.get_by_role('button', name='检查答案')).to_have_count(0)
        essay_text = writing.locator('textarea')
        essay_text.fill('Meet at the entrance.')
        essay_text.press('End')
        essay_text.press('Enter')
        essay_text.press('Enter')
        essay_text.press_sequentially('Bring a notebook.')
        expect(essay_text).to_have_value('Meet at the entrance.\n\nBring a notebook.')
        page.get_by_role('button', name='返回学习计划', exact=True).click()
        open_course(title, mixed_id, return_to_plan=True)
        expect(essay_text).to_have_value('Meet at the entrance.\n\nBring a notebook.')
        page.screenshot(path=str(evidence / 'english-writing.png'))
        stage.get_by_role('button', name='提交作文').click()
        expect(writing.get_by_text('等待批改', exact=False)).to_be_visible()
        stage.get_by_role('button', name='完成本课').click()
        expect(stage.get_by_role('heading', name='这门课的训练已确认')).to_be_visible()
        expect(stage.get_by_text('3 / 3 项已完成检查')).to_be_visible()
        for label, course_id in standalone.items():
            open_course(label, course_id)
            expect(page.locator('.english-header-progress')).to_have_text('1 / 1')
            if label == 'Standalone essay':
                expect(writing.locator('textarea')).to_be_visible()
                writing.locator('textarea').fill('Bring a notebook to record your observations.')
                writing.get_by_role('button', name='提交作文').click()
                expect(writing.get_by_text('等待批改', exact=False)).to_be_visible()
                queue = cli.call('assignment.summary', {'course_id':course_id, 'role':'agent'})
                assert len(queue['items']) == 1, queue
                cli.call('review.write', {'submission_id':queue['items'][0]['id'], 'summary':'写作目标已达成',
                         'detail_markdown':'理由具体，建议再补一条参观前准备。', 'decision':'PASSED', 'idempotency_key':'native-essay-review'})
                page.get_by_role('button', name='返回学习计划', exact=True).click()
                open_course(label, course_id, return_to_plan=True)
                expect(writing.get_by_role('heading', name='写作目标已达成')).to_be_visible()
                expect(writing.get_by_text('理由具体，建议再补一条参观前准备。')).to_be_visible()
            else:
                expect(stage.get_by_role('radio', name='B. At the library')).to_be_visible()
                if label == 'Standalone listening':
                    stage.get_by_role('button', name='播放音频').click()
                    wait_for_audio(player)
                    assert player.evaluate('(element) => element.duration') == 4
        open_course('Legacy mixed', legacy_ids['Legacy mixed'], legacy=True)
        expect(stage.get_by_role('heading', name='Travel dialogue')).to_be_visible()
        expect(page.locator('.english-header-progress')).to_have_text('1 / 4')
        stage.get_by_role('button', name='播放音频').click()
        wait_for_audio(player)
        toggle.click()
        player.evaluate('(audio) => { audio.pause(); audio.currentTime = 2.75 }')
        expect(captions).to_contain_text('估算同步')
        expect(captions).to_contain_text('Bring your library card.')
        player.evaluate('(audio) => { audio.currentTime = 0.25 }')
        expect(captions).to_contain_text('Meet at the library.')
        radio.check()
        radio.press('Enter')
        blank.fill('CaRD')
        blank.press('Enter')
        expect(stage.get_by_text('答对 2 / 2 题')).to_be_visible()
        forward = page.get_by_role('button', name='下一项 →', exact=True)
        forward.click()
        expect(stage.get_by_text('When will we meet?')).to_be_visible()
        expect(stage.get_by_role('textbox', name='我的答案')).to_have_value('Existing draft at nine.')
        stage.get_by_role('textbox', name='我的答案').fill('Nine o’clock.')
        forward.click()
        radio.check()
        radio.press('Enter')
        expect(stage.get_by_text('答对 1 / 1 题')).to_be_visible()
        forward.click()
        expect(stage.locator('textarea')).to_be_visible()
        stage.locator('textarea').fill('Bring a notebook and write down the opening hours.')
        stage.get_by_role('button', name='提交作文').click()
        expect(stage.get_by_text('等待批改')).to_be_visible()
        page.get_by_role('button', name='提交本课').click()
        expect(page.get_by_role('button', name='返回学习计划', exact=True)).to_have_count(2)
        persisted = cli.call('course.study.get', {'study_session_id':study_id})
        assert persisted['course']['learning_submitted'], persisted['course']
        assert any(ex['draft'] is None and ex['latest_submission'] is not None
                   for ex in persisted['lessons'][0]['exercises'] if ex['type'] == 'SHORT_ANSWER')
        for label in ['Legacy essay', 'Legacy reading', 'Legacy listening']:
            open_course(label, legacy_ids[label], legacy=True)
            expect(page.locator('.english-header-progress')).to_have_text('1 / 1')
        open_course('Theory course', legacy_ids['Theory course'], theory=True)
        page.evaluate("location.hash = '/queue'")
        page.get_by_role('button', name='已通过历史', exact=True).click()
        row = page.locator('.feedback-row').filter(has_text='Standalone essay').first
        expect(row).to_be_visible()
        expect(page.get_by_role('button', name='已通过历史', exact=True)).to_have_attribute('aria-pressed', 'true')
        rows = page.locator('.feedback-rows')
        rows.evaluate("(el) => {el.style.maxWidth = '370px'}")
        expect(row.locator('div').first).to_have_css('grid-row-start', '2')
        assert rows.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1')
        page.screenshot(path=str(evidence / 'feedback-narrow.png'))
        page.evaluate("location.hash = '/settings'")
        settings = page.get_by_role('region', name='语音生成')
        provider = settings.get_by_label('接入方式')
        endpoint = settings.get_by_label('完整接口地址')
        password = settings.get_by_label('API Key')
        save_profile = settings.get_by_role('button', name='保存配置')
        clear = settings.get_by_role('button', name='清除 Key')
        default = cli.call('speech.profile.get')
        assert default['provider'] == 'step_plan' and not default['has_credential']
        expect(provider).to_have_value('step_plan')
        expect(settings.locator('.speech-endpoint code')).to_have_text('https://api.stepfun.com/step_plan/v1/audio/speech')
        provider.select_option('compatible')
        fixture_endpoint = 'http://127.0.0.1:12345/v1/audio/speech'
        endpoint.fill(fixture_endpoint)
        password.fill('offline-ui-test-key')
        save_profile.click()
        expect(clear).to_be_visible()
        expect(password).to_have_value('')
        compatible = cli.call('speech.profile.get')
        assert compatible['provider'] == 'compatible' and compatible['endpoint'] == fixture_endpoint
        assert compatible['has_credential'] and 'offline-ui-test-key' not in json.dumps(compatible)
        clear.click()
        expect(clear).to_have_count(0)
        assert not cli.call('speech.profile.get')['has_credential']
        provider.select_option('step_plan')
        expect(endpoint).to_have_count(0)
        save_profile.click()
        expect(save_profile).to_be_disabled()
        assert cli.call('speech.profile.get')['provider'] == 'step_plan'
        page.screenshot(path=str(evidence / 'speech-settings.png'))
        preview = page.get_by_role('region', name='题组预览')
        picker = preview.get_by_label('课程包 JSON')
        for name in ('legacy-listening', package['package_id']):
            picker.set_input_files(evidence / (name + '.json'))
            preview.get_by_role('button', name='打开预览').click()
            practice = preview.get_by_role('region', name='题组练习')
            expect(practice.get_by_text('Travel dialogue', exact=True)).to_be_visible()
            practice.get_by_role('button', name='播放音频').click()
            wait_for_audio(practice.locator('audio'))
            practice.get_by_role('button', name='退出预览', exact=False).click()
        page.screenshot(path=str(evidence / 'practice-author-preview.png'))
        verify_ui_speech(cli, settings)

        assert not errors, errors
        print(json.dumps({'ok': True, 'mixed': mixed_id, 'standalone': list(standalone), 'workspace': str(evidence)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True, help='new synthetic workspace directory')
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    evidence = args.evidence.resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    main(args.desktop.resolve(strict=True), workspace, evidence)
