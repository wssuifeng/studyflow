"""Real Vue/Core theme smoke check. Synthetic data and ephemeral loopback fixture only."""
import copy, json, time, re
from pathlib import Path
from typer.testing import CliRunner
from playwright.sync_api import sync_playwright, expect
import smoke_workbench_support as f
from studyflow.cli import app
from studyflow.interfaces.cli import runtime

KEY = 'studyflow:theme-preference:v1'

def main():
    package = json.loads((f.ROOT.parents[1]/'skills/studyflow-agent/examples/course-package.json').read_text(encoding='utf-8'))
    package['package_id'] = 'theme-smoke-demo'
    package['plan_line'] = f.plan.name
    package['course']['title'] = '合成主题验证课程'
    lesson = package['lessons'][0]
    lesson['title'] = '计算机系统 · 七种教学组件'
    lesson['blocks'][0]['title'] = 'CPU 的职责与边界'
    lesson['blocks'][0]['body'] = 'CPU 负责执行指令，**程序计数器 PC** 指向下一条指令的地址。\n\n' + '\n\n'.join('这是纯合成的长正文，用于验证主题切换时中文阅读位置、编辑状态和组件层次保持不变。' for _ in range(8))
    lesson['blocks'][2]['items'].extend([{'title':'译码','body':'识别指令和操作数。'},{'title':'执行','body':'执行指令，再推进到下一条指令。'}])
    lesson['blocks'][3]['given'] = '程序计数器 PC 的初始值为 8。\n\n```java\nint pc = 8;\npc += 4;\n```'
    lesson['blocks'][4]['body'] = '地址不是指令本身。反馈颜色只表达状态，不改变题目、轮次或学习记录。'
    next_lesson = copy.deepcopy(lesson);next_lesson['id']='memory';next_lesson['title']='存储与地址';package['lessons'].append(next_lesson)
    file=f.WORKSPACE/'theme-demo.json';file.write_text(json.dumps(package,ensure_ascii=False),encoding='utf-8')
    original=runtime.service;runtime.service=lambda:f.service
    try:
        result=CliRunner().invoke(app,['course','import-package','--file',str(file),'--format','json'])
        assert result.exit_code==0,result.output
        course=json.loads(result.stdout)['course_id']
    finally:runtime.service=original
    methods=[]; original_handle=f.engine.handle
    def tracked(request):
        methods.append(request.get('method'))
        return original_handle(request)
    f.engine.handle=tracked
    evidence=f.ROOT/'test-results/theme-builtins-20261006';evidence.mkdir(exist_ok=True)
    checks=[];errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
        page=context.new_page();peer=context.new_page()
        for tab in (page,peer):
            tab.set_default_timeout(10000);tab.on('pageerror',lambda error:errors.append(str(error)))
        try:
            page.goto(f.url+'/#/course/'+course);page.wait_for_load_state('networkidle')
            try:
                expect(page.locator('.teaching-block')).to_have_count(7)
            except Exception:
                page.screenshot(path=str(evidence/'startup-failure.png'),full_page=True)
                print(json.dumps({'page_errors':errors,'body':page.locator('body').inner_text()[:4000]},ensure_ascii=False))
                raise
            sid=f.service.course_detail(course)['course']['study_session_id']
            expect(page.locator('html')).to_have_attribute('data-theme-id','white-violet')
            page.get_by_role('button',name='打开答题与笔记',exact=True).click()
            answer=page.locator('.knowledge-question textarea');answer.fill('合成答案：尚未提交，不代表真实学习。')
            page.get_by_role('tab',name='笔记',exact=True).click()
            page.get_by_role('button',name='＋ 写笔记',exact=True).click()
            note=page.get_by_role('textbox',name='笔记：计划',exact=True);note.fill('合成笔记：主题切换不应创建新的编辑器。')
            # Theme changes may switch between distinct Vue presentation templates; preserve note content, not DOM identity.
            body=page.locator('.study-material-body');body.evaluate('el=>{el.scrollTop=210;el.dispatchEvent(new Event("scroll"))}')
            before_scroll=body.evaluate('el=>el.scrollTop')
            peer.goto(f.url+'/#/settings');peer.wait_for_load_state('networkidle')
            expect(peer.locator('.theme-option')).to_have_count(2)
            expect(peer.locator('.theme-settings')).to_be_visible()
            time.sleep(1)
            write_before=len([m for m in methods if m.endswith(('.save','.submit','.create','.write','.update'))])
            for id,name in [('sequence-light','序光'),('white-violet','白紫轻学')]:
                peer.locator('.theme-option').filter(has_text=name).click()
                expect(page.locator('html')).to_have_attribute('data-theme-id',id)
                expect(peer.locator('html')).to_have_attribute('data-theme-id',id)
                if id=='sequence-light': page.locator('#sequence-notes-tab').click()
                expect(note).to_have_value('合成笔记：主题切换不应创建新的编辑器。')
                after_scroll=body.evaluate('el=>el.scrollTop')
                assert abs(after_scroll-before_scroll)<=2,(id,before_scroll,after_scroll)
                assert f.service.course_detail(course)['course']['study_session_id']==sid
                colors=page.evaluate("""(keys)=>{const root=getComputedStyle(document.documentElement);const el=document.createElement("i");document.body.append(el);const css=hex=>{el.style.color=hex;return getComputedStyle(el).color};const result=Object.fromEntries(keys.map(key=>[key,css(root.getPropertyValue(key).trim())]));el.remove();return result}""", ["--theme-surface-canvas","--theme-surface-panel","--theme-surface-raised"])
                background=page.locator('.main-content').evaluate('el=>getComputedStyle(el).backgroundColor')
                assert background in colors.values(), (id, background, colors)
                if id=='sequence-light':
                    body.evaluate('el=>{el.scrollTop=0}')
                    page.locator('#sequence-tools-tab').click()
                    expect(page.locator('.sequence-tools-panel')).to_be_visible()
                    expect(page.locator('.sequence-progress-card')).to_be_visible()
                    expect(page.locator('.sequence-next-card')).to_be_visible()
                    page.screenshot(path=str(evidence/'sequence-light-course-tools.png'))
                    page.locator('#sequence-notes-tab').click()
                    page.screenshot(path=str(evidence/'sequence-light-course-notes-viewport.png'))
                page.screenshot(path=str(evidence/f'{id}-course-notes.png'),full_page=True)
                peer.locator('.theme-settings').screenshot(path=str(evidence/f'{id}-settings.png'))
            after=len([m for m in methods if m.endswith(('.save','.submit','.create','.write','.update'))])
            assert after==write_before,(write_before,after,methods)
            checks.append('two adopted themes cover real Vue teaching and tools; note content, round and reading scroll preserved; no theme-triggered Core writes')
            page.get_by_role('tab',name=re.compile('^练习')).click()
            expect(answer).to_have_value('合成答案：尚未提交，不代表真实学习。')
            # Local config imported by the actual file input; no CSS or script evaluation.
            custom=json.loads((f.ROOT/'src/shared/themes/builtin/sequence-light.json').read_text(encoding='utf-8'))
            custom['id']='theme-smoke-custom';custom['name']='合成自定义主题'
            custom.pop('display',None)  # Legacy v1 input remains supported.
            peer.locator('input[type=file]').set_input_files({'name':'local.theme.json','mimeType':'application/json','buffer':json.dumps(custom,ensure_ascii=False).encode()})
            expect(page.locator('html')).to_have_attribute('data-theme-id',custom['id'])
            expect(peer.locator('.theme-option')).to_have_count(3)
            with peer.expect_download() as download:peer.get_by_role('button',name='导出当前主题',exact=True).click()
            exported=evidence/'exported.theme.json';download.value.save_as(exported)
            exported_value=json.loads(exported.read_text(encoding='utf-8'))
            expected_display={'layout':'rail','navigation_width':184,'reading_width':820,'tools_width':420,'reading_shell':'workbench','teaching_style':'clean','note_style':'inline','type_scale':1,'heading_family':'modern','body_family':'ui','surface_treatment':'matte','radius':12,'elevation':'none','outline':'hairline','assets':[]}
            assert exported_value == {**custom,'display':expected_display}
            # Legacy v1 theme input is exported in the canonical v2-compatible display shape.
            bad=copy.deepcopy(custom);bad['tokens']['text.primary']='url(https://invalid.test/a)'
            peer.locator('input[type=file]').set_input_files({'name':'bad.json','mimeType':'application/json','buffer':json.dumps(bad).encode()})
            expect(peer.locator('.theme-action-message.error')).to_be_visible()
            expect(page.locator('html')).to_have_attribute('data-theme-id',custom['id'])
            checks.append('local JSON import/export, validation failure is nonblocking and does not change selection')
            # Newly opened same-origin window restores the selected custom palette.
            fresh=context.new_page();fresh.goto(f.url+'/#/settings');fresh.wait_for_load_state('networkidle')
            expect(fresh.locator('html')).to_have_attribute('data-theme-id',custom['id']);fresh.close()
            peer.reload();peer.wait_for_load_state('networkidle')
            expect(peer.locator('html')).to_have_attribute('data-theme-id',custom['id'])
            peer.get_by_role('button',name='移除此自定义主题',exact=True).click();peer.get_by_role('button',name='确认移除',exact=True).click()
            expect(page.locator('html')).to_have_attribute('data-theme-id','white-violet')
            checks.append('reload and new window restore custom theme; removing active custom theme falls back across windows')
            # Reading and audio preferences are separate; switching does not mutate their keys.
            prefs={'studyflow:interaction-sound:v1':'off','studyflow-reading-preferences':'{"font":18,"lineHeight":2,"width":780}'}
            page.evaluate('(p)=>{for(const [key,value] of Object.entries(p))localStorage.setItem(key,value)}',prefs)
            peer.locator('input[type=range]').first.evaluate('el=>{el.value=18;el.dispatchEvent(new Event("input",{bubbles:true}))}')
            reading_before=peer.evaluate('["--reading-font","--reading-line-height","--reading-width"].map(key=>document.documentElement.style.getPropertyValue(key))')
            before=page.evaluate('Object.fromEntries(Object.entries(localStorage).filter(([key])=>!key.includes("theme")))')
            peer.locator('.theme-option').filter(has_text='序光').click()
            expect(page.locator('html')).to_have_attribute('data-theme-id','sequence-light')
            after=page.evaluate('Object.fromEntries(Object.entries(localStorage).filter(([key])=>!key.includes("theme")))')
            assert before==after
            assert peer.evaluate('["--reading-font","--reading-line-height","--reading-width"].map(key=>document.documentElement.style.getPropertyValue(key))')==reading_before
            page.emulate_media(reduced_motion='reduce')
            duration=page.locator('.sequence-outline-item, .knowledge-step').first.evaluate('el=>getComputedStyle(el).transitionDuration')
            assert all(float(v.strip().rstrip('s'))==0 for v in duration.split(',')),duration
            page.set_viewport_size({'width':730,'height':1000});page.screenshot(path=str(evidence/'sequence-light-narrow.png'),full_page=True)
            page.set_viewport_size({'width':1440,'height':1000})
            for zoom in (1.5,2):
                peer.evaluate('(zoom)=>{document.documentElement.style.zoom=zoom}',zoom)
                expect(peer.locator('.theme-option').first).to_be_visible()
                assert peer.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth+2')
                peer.screenshot(path=str(evidence/f'settings-zoom-{zoom}.png'),full_page=True)
            checks.append('reading/sound preference keys unchanged; reduced motion honored; narrow view and 150/200 percent CSS zoom have reachable controls')
            # Corrupt and unwritable preferences use the real runtime fallback, not a mock app.
            bad_context=browser.new_context(viewport={'width':1200,'height':900})
            bad_context.add_init_script(f"localStorage.setItem('{KEY}','{{')")
            bad_page=bad_context.new_page();bad_page.goto(f.url+'/#/settings');bad_page.wait_for_load_state('networkidle')
            expect(bad_page.locator('html')).to_have_attribute('data-theme-id','white-violet')
            expect(bad_page.locator('.theme-storage-notice')).to_be_visible();bad_context.close()
            ro_context=browser.new_context(viewport={'width':1200,'height':900})
            ro_context.add_init_script(f"const old=Storage.prototype.setItem;Storage.prototype.setItem=function(key,value){{if(key==='{KEY}')throw new DOMException('readonly','QuotaExceededError');return old.call(this,key,value)}}")
            ro_page=ro_context.new_page();ro_page.goto(f.url+'/#/settings');ro_page.wait_for_load_state('networkidle')
            ro_page.locator('.theme-option').filter(has_text='序光').click()
            expect(ro_page.locator('html')).to_have_attribute('data-theme-id','sequence-light')
            expect(ro_page.locator('.theme-storage-notice')).to_contain_text('本次会话')
            ro_peer=ro_context.new_page();ro_peer.goto(f.url+'/#/settings');ro_peer.wait_for_load_state('networkidle')
            expect(ro_peer.locator('html')).to_have_attribute('data-theme-id','sequence-light');ro_context.close()
            checks.append('corrupt storage falls back safely; blocked theme writes remain session-only and synchronize to new window')
            assert not errors,errors
            report={'ok':True,'workspace':str(f.WORKSPACE),'checks':checks,'console_errors':errors,'native_window_tested':False,'system_zoom_tested':False}
            (evidence/'browser-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False))
        finally:context.close();browser.close()

if __name__=='__main__':
    try:main()
    finally:f.server.shutdown();f.server.server_close();f.database.dispose()

