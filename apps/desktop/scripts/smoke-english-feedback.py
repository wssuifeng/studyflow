"""Real Vue/Core, synthetic data: lost reply, dismissible error, exact-key recovery. No learner data."""
import json, os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
import smoke_workbench_support as f

checks=[];errors=[]
def course(key):
    package={"schema":"studyflow.course-package/6","package_id":"feedback-"+key,"plan_line":f.plan.name,"course":{"title":"合成反馈验证 "+key,"learning_mode":"english"},"lessons":[{"id":"likes","title":"表达喜好","blocks":[{"id":"intro","type":"concept","title":"喜好","body":"I like 表达喜好。"}],"exercises":[{"id":"tea","title":"我喜欢茶","prompt":"我喜欢茶。","english":{"target":"I like tea.","objective_ids":["likes"]}}]}]}
    file=f.WORKSPACE/(key+'.json');file.write_text(json.dumps(package,ensure_ascii=False),encoding='utf-8')
    imported=f.service.import_course_package(file)
    opened=f.service.open_course_study(imported['course_id'],'open-'+key,plan_line_id=f.plan.id)
    return imported,opened

def retest(key,imported,opened):
    sid=opened['study']['id'];item=f.service.english.get(sid)['items'][0];eid=item['exercise_id']
    saved=f.service.english.save(sid,eid,'I lik tea',0,key+'-wrong-save')
    f.service.english.check(sid,eid,saved['answer_version'],key+'-wrong-check')
    current=f.service.english.get(sid)['items'][0]
    fixed=f.service.english.save(sid,eid,'I like tea',current['answer_version'],key+'-fix')
    f.service.english.check(sid,eid,fixed['answer_version'],key+'-correct')
    f.service.english.submit(sid,key+'-submit')
    scope={'plan_line_id':imported['plan_id'],'course_id':imported['course_id'],'domain':'english'}
    entry=f.service.mistakes.list(**scope)['items'][0]
    f.service.mistakes.select_review(entry['id'],entry['version'],key+'-select',**scope)
    entry=f.service.mistakes.list(**scope)['items'][0]
    return f.service.mistakes.retest_request(entry['id'],entry['version'],key+'-retest',**scope)['task_id']

try:
 with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,channel='msedge' if os.name=='nt' else None)
    try:
      for theme in ('sequence-light','white-violet'):
       for mode in ('training','retest'):
        key=theme+'-'+mode;imported,opened=course(key)
        route='/english/'+opened['study']['id'] if mode=='training' else '/english-retest/'+retest(key,imported,opened)
        context=browser.new_context(viewport={'width':1366,'height':768})
        context.add_init_script("localStorage.setItem('studyflow:theme-preference:v1',JSON.stringify(%s));localStorage.setItem('studyflow:english-speech:v1',JSON.stringify({auto:false,muted:true}))"%json.dumps({'schema_version':'studyflow.theme-preference/1','selected_theme_id':theme,'custom_themes':[],'revision':{'clock':1,'source':'feedback-test'}}))
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        requests=[];fault={'remaining':1};method='course.english.check' if mode=='training' else 'course.english.retest-check'
        def intercept(route):
            payload=route.request.post_data_json
            if payload.get('method')==method:
                requests.append(payload['params'])
                if fault['remaining']:
                    fault['remaining']-=1
                    response=route.fetch();data=response.json();assert data['ok'],data
                    data['id']='synthetic-lost-correlation'
                    route.fulfill(response=response,json=data);return
            route.continue_()
        page.route('**/api/engine',intercept);page.route('https://dict.youdao.com/**',lambda route:route.abort())
        page.goto(f.url+'/#'+route)
        expect(page.locator('html')).to_have_attribute('data-theme-id',theme)
        for i,word in enumerate(('I','like','tea')):page.get_by_role('textbox',name=f'第 {i+1} 个单词',exact=True).fill(word)
        page.get_by_role('button',name='检查答案' if mode=='training' else '确认本次复测',exact=mode!='training').click()
        problem=page.get_by_role('alertdialog',name='保存尚未确认',exact=True)
        expect(problem).to_be_visible();expect(page.locator('.english-error')).to_have_count(0)
        assert page.get_by_role('textbox',name='第 2 个单词',exact=True).input_value()=='like'
        assert '响应ID不匹配' not in problem.inner_text()
        problem.get_by_role('button',name='暂时关闭',exact=True).click();expect(problem).not_to_be_visible()
        page.wait_for_timeout(1000);expect(problem).not_to_be_visible()
        status=page.get_by_role('button',name='保存待确认',exact=True);expect(status).to_be_visible();status.click();expect(problem).to_be_visible()
        # Native dialog Escape dismisses the UI, not the unconfirmed write.
        page.keyboard.press('Escape');expect(problem).not_to_be_visible();expect(status).to_be_visible()
        status.click();problem.get_by_role('button',name='重试原操作',exact=True).click();expect(problem).not_to_be_visible()
        assert len(requests)==2 and requests[0]==requests[1],requests
        if mode=='training':expect(page.get_by_role('button',name='完成本课',exact=True)).to_be_visible()
        else:expect(page.get_by_role('heading',name='本次无提示复测通过',exact=True)).to_be_visible()
        expect(status).to_have_count(0);checks.append(theme+' '+mode+': lost confirmed reply, no banner, close/Escape, compact reopen, identical-key replay')
        context.close()
      assert not errors,errors
      result={'ok':True,'checks':checks,'page_errors':errors,'workspace':str(f.WORKSPACE)}
      (f.WORKSPACE/'english-feedback-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
    finally:browser.close()
finally:f.server.shutdown();f.database.dispose()
