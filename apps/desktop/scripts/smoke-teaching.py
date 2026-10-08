"""Structured teaching components: real Vue/Core, CLI import, synthetic data only."""
import copy,json,time
from pathlib import Path
from typer.testing import CliRunner
from playwright.sync_api import sync_playwright,expect
import smoke_workbench_support as f
from studyflow.cli import app
from studyflow.interfaces.cli import runtime


def main():
    data=json.loads((f.ROOT.parents[1]/'skills/studyflow-agent/examples/course-package.json').read_text(encoding='utf-8'))
    data['plan_line']=f.plan.name
    source=data['lessons'][0]
    for i in range(2,6):
        item=copy.deepcopy(source);item['id']=f'cpu-{i}';item['title']=f'知识点 {i}';data['lessons'].append(item)
    package=f.WORKSPACE/'teaching-demo.json';package.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    original=runtime.service;runtime.service=lambda:f.service
    try:
        result=CliRunner().invoke(app,['course','import-package','--file',str(package),'--format','json'])
        assert result.exit_code==0,result.output
        imported=json.loads(result.stdout)
    finally:runtime.service=original
    course=imported['course_id'];checks=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page(viewport={'width':1440,'height':900});page.set_default_timeout(10000)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        try:
            page.goto(f.url+'/#/course/'+course);page.wait_for_load_state('networkidle')
            expect(page.locator('.teaching-block')).to_have_count(7)
            expect(page.locator('#workspace-tool-panel')).not_to_be_visible()
            header=page.locator('.reader-toolbar').bounding_box();nav=page.locator('.reader-navigation').bounding_box()
            assert header['height']<=72 and nav['height']<=80,(header,nav)
            body=page.locator('.study-material-body');assert body.bounding_box()['height']>520
            expect(page.locator('.reader-heading .muted')).to_have_count(0)
            page.screenshot(path=str(f.WORKSPACE/'teaching-1440.png'),full_page=True)
            sid=f.service.course_detail(course)['course']['study_session_id'];checks.append('compact header, seven components, initial tools closed')
            # Follow the practice link to the same-round answer, not a new route/editor.
            page.locator('.teaching-practice-links button').click()
            expect(page.locator('#workspace-tool-panel')).to_be_visible()
            answer=page.get_by_role('textbox');answer.fill('合成测试答案，不是学习记录。')
            page.get_by_role('button',name='下一知识点',exact=True).click()
            expect(page.locator('.study-unit-heading h3')).to_have_text('知识点 2')
            page.get_by_role('button',name='上一知识点',exact=True).click()
            expect(page.get_by_role('textbox')).to_have_value('合成测试答案，不是学习记录。')
            assert f.service.course_detail(course)['course']['study_session_id']==sid
            page.screenshot(path=str(f.WORKSPACE/'teaching-with-tools.png'),full_page=True)
            checks.append('practice links reuse answer editor; navigation autosaves same round')
            # Scroll only material: heading leaves; a compact location remains.
            page.get_by_role('button',name='收起学习工具',exact=True).click()
            body.evaluate('(el)=>{el.scrollTop=180;el.dispatchEvent(new Event("scroll"))}')
            expect(page.locator('.reader-current-title')).to_have_class('reader-current-title visible')
            assert page.locator('.study-unit-heading').bounding_box()['y']<body.bounding_box()['y']
            checks.append('heading scrolls with document; short location remains')
            page.get_by_role('button',name='打开答题与笔记',exact=True).click()
            page.get_by_role('tab',name='大纲',exact=False).click()
            page.locator('.lesson-section-outline').get_by_role('button',name='Example',exact=True).click()
            expect(page.locator('[data-content-block="example"]')).to_be_in_viewport()
            checks.append('existing outline navigates structured content sections')
            page.get_by_role('button',name='收起学习工具',exact=True).click()
            # Selection writes a verified source_block_id to the existing plan notebook.
            body.evaluate('(el)=>{el.scrollTop=0;el.dispatchEvent(new Event("scroll"))}')
            target=page.locator('[data-content-block="idea"] .teaching-richtext p')
            target.evaluate('el=>{const r=document.createRange();r.selectNodeContents(el);const s=window.getSelection();s.removeAllRanges();s.addRange(r)}')
            target.dispatch_event('mouseup')
            page.get_by_role('button',name='≡ 记入计划笔记',exact=True).click()
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                notes=f.service.plan_notebook(f.plan.id)['blocks']
                if notes and notes[-1].get('source_block_id')=='idea':break
                page.wait_for_timeout(150)
            else:raise AssertionError(f'Excerpt not persisted: {notes}')
            checks.append('excerpt verified against frozen component and persisted plan notebook')
            page.get_by_role('button',name='收起学习工具',exact=True).click()
            for width,height in [(1100,800),(900,740),(640,720)]:
                page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(120)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                page.screenshot(path=str(f.WORKSPACE/f'teaching-{width}.png'),full_page=True)
            checks.append('1100/900/640 layouts without page horizontal overflow')
            page.set_viewport_size({'width':1440,'height':900})
            page.goto(f.url+'/#/course/'+f.courses[0]);page.wait_for_load_state('networkidle')
            expect(page.locator('.legacy-teaching-content')).to_be_visible();expect(page.locator('.teaching-block')).to_have_count(0)
            checks.append('legacy markdown readable without source migration')
            assert not errors,errors
            report={'ok':True,'checks':checks,'page_errors':errors,'workspace':str(f.WORKSPACE)}
            (f.WORKSPACE/'teaching-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(report,ensure_ascii=False,indent=2))
        except Exception:
            page.screenshot(path=str(f.WORKSPACE/'teaching-failure.png'),full_page=True)
            print('Failure screenshot:',f.WORKSPACE/'teaching-failure.png')
            print('Page errors:',errors)
            raise
        finally:browser.close();f.server.shutdown();f.database.dispose()

if __name__=='__main__':main()
