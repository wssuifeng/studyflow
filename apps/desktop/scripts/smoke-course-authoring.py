"""LC-05: synthetic authoring examples through actual CLI and production Vue.

Four general teaching shapes and an English progression; never imports private
source material or operates an installed learner workspace. Not an AI grader.
"""
from __future__ import annotations
import json
from pathlib import Path
from copy import deepcopy
from typer.testing import CliRunner
from playwright.sync_api import sync_playwright, expect
import smoke_workbench_support as f
from studyflow.cli import app
from studyflow.interfaces.cli import runtime

checks,errors=[],[]
def check(name,passed=True):
    checks.append({'name':name,'passed':bool(passed)})
    if not passed:raise AssertionError(name)
def concept(id,title,body):return {'id':id,'type':'concept','title':title,'body':body}
def question(id,prompt,requirements='说明依据；不只写结论。'):return {'id':id,'title':'独立检验','prompt':prompt,'requirements':requirements}

general={'schema':'studyflow.course-package/3','package_id':'lc05-synthetic-general','plan_line':f.plan.name,
 'course':{'title':'制课复盘 · 四类合成样本','learning_mode':'general'},'lessons':[
 {'id':'concept','title':'概念：成员与集合','blocks':[concept('definition','先分清对象与整体','集合是一些对象构成的整体；其中每个对象叫元素。\n\n## 用一条关系判断\n记号 x ∈ A 表示对象 x 是集合 A 的元素。先确定对象和集合，再判断成员关系。\n\n同一对象重复列出不会成为两个不同元素。')],
 'exercises':[question('membership','A={2,5}。判断2与A的关系，并说明“元素”和“集合”各指哪个对象。')]},
 {'id':'calculation','title':'计算：加权耗时','blocks':[concept('assumptions','条件先于计算','两条处理路线互斥，分别占全部请求的80%和20%。每条给定耗时已包含该路线全部工作。\n\n## 权重与单位\n平均耗时=各路线占比乘对应耗时再求和。占比相加为1，耗时使用同一单位。'),
 {'id':'worked','type':'example','title':'先看有理由的计算','given':'路线A耗时5ms，路线B耗时20ms。','steps':[{'title':'分别加权','body':'0.8×5=4ms；0.2×20=4ms。'},{'title':'求和并检查','body':'平均8ms，位于5ms和20ms之间。'}],'conclusion':'平均耗时8ms；这里不能再额外加某一路线耗时。'},
 {'id':'supplement','type':'details','title':'补充：哪些条件会改变算法','summary':'改变路线是否互斥或耗时是否已经含全部工作，需要先调整模型。','body':'### 模型边界\n若一条路线包含另一条工作的耗时，先查清包含关系，不能重复相加。'}],
 'exercises':[question('weighted','两条互斥路线占比仍为80%和20%，完整耗时改为2ms和8ms。计算平均耗时。','列出加权过程和单位，检查结果范围。')]},
 {'id':'code','title':'代码：边界与状态','blocks':[concept('code','跟踪实际执行顺序','下面的Python函数取非空列表的最大值；空列表返回None。\n\n```python\ndef largest(values):\n    if not values:\n        return None\n    best = values[0]\n    for value in values[1:]:\n        if value > best:\n            best = value\n    return best\n```\n\n## 看清边界\n空列表先返回；非空时best保存当前已扫描部分的最大值。它不是永远从0开始。'),
 {'id':'negative','type':'callout','title':'一个真实易错点','tone':'warning','body':'若把best直接初始化为0，全为负数的输入可能得到不属于列表的错误结果。'}],
 'exercises':[question('trace','追踪largest([-4,-1,-3])的best变化，并说明largest([])返回什么。','给出执行依据和边界结论；不必重写函数。')]},
 {'id':'case','title':'案例：业务约束与关系','blocks':[concept('business','先说明记录的粒度','某工具记录成员借出某一本实体书的事件。一个成员可以多次借书，一本实体书可以在不同时间被多次借出。\n\n## 区分对象和事件\n成员、实体书和借阅事件作用不同：借阅事件记录发生时间，并关联当次成员与实体书。选记录结构之前先确定业务事实，不能只凭页面名称猜。'),
 {'id':'dimensions','type':'comparison','title':'用共同维度整理问题','columns':['观察对象','要确认的事实'],'rows':[['成员','谁参与当次借阅'],['实体书','当次借出哪一本'],['借阅事件','何时发生、关联哪些对象']]}],
 'exercises':[question('model','若同一成员可在不同日期重复借同一本书，解释为什么不能只用“成员+书”区分每一次事件。提出一种可行的事件区分办法。','写明业务依据与方案；满足条件的等价设计均可。')]}
 ]}
repo=Path(__file__).resolve().parents[3]
# Author-only reference is an isolated artifact, never an unknown package
# field or learner submission. IDs below align with the synthetic exercises.
author_reference={'concept/membership':'2是A的元素，A是集合。','calculation/weighted':'0.8×2+0.2×8=3.2ms，处于2ms与8ms之间。','code/trace':'best先为-4，再为-1，最后保持-1；空列表为None。','case/model':'成员和书相同不能区分重复事件，可用稳定事件ID，并记录日期等业务属性；满足给定约束的其他方案可接受。'}
(f.WORKSPACE/'author-reference.json').write_text(json.dumps(author_reference,ensure_ascii=False,indent=2),encoding='utf-8')
english=deepcopy(json.loads((repo/'skills/studyflow-agent/examples/english-course-package.json').read_text(encoding='utf-8')))
english['package_id']='lc05-synthetic-english';english['plan_line']=f.plan.name;english['course']['title']='制课复盘 · 英语渐进合成样本'
lesson=english['lessons'][0]
lesson['title']='先词义再组合'
lesson['blocks'][0]['body']='这是合成基础假设：已经解释I指说话者，like表达喜欢。新词tea是茶，coffee是咖啡。先回忆词义，再把已知结构I like和名词组合。后续否定/第三人称不在本课。'
lesson['exercises']=[{'id':'word-tea','title':'词义回忆','prompt':'茶','english':{'target':'tea','objective_ids':['express-likes']}},{'id':'word-coffee','title':'词义回忆','prompt':'咖啡','english':{'target':'coffee','objective_ids':['express-likes']}}]+lesson['exercises'][:2]
previous=runtime.service
try:
    runtime.service=lambda:f.service
    imported=[]
    for name,package in [('general',general),('english',english)]:
        file=f.WORKSPACE/(name+'-authoring.json');file.write_text(json.dumps(package,ensure_ascii=False,indent=2),encoding='utf-8')
        for command in [('validate-package',),('import-package',)]:
            result=CliRunner().invoke(app,['course',*command,'--file',str(file),'--format','json'])
            assert result.exit_code==0,result.output
            data=json.loads(result.output);check(name+'-'+command[0]+'-CLI',data['ok'])
        imported.append(data)
        readback=CliRunner().invoke(app,['course','detail','--id',data['course_id'],'--format','json']);assert readback.exit_code==0,readback.output
        detail=json.loads(readback.output);check(name+'-readback-counts',len(detail['lessons'])==len(package['lessons']) and sum(len(l['exercises']) for l in detail['lessons'])==sum(len(l['exercises']) for l in package['lessons']))
    check('general-not-fixed-six-part-template',len({tuple(b['type'] for b in l['blocks']) for l in general['lessons']})==4)
    check('author-reference-mapped-outside-visible-package',all(l['id']+'/'+e['id'] in author_reference for l in general['lessons'] for e in l['exercises']) and not any(text in json.dumps(general,ensure_ascii=False) for text in author_reference.values()))
    check('visible-requirements-no-reference-answer-label',not any(any(k in e.get('requirements','') for k in ['参考答案','正确答案','评分要点']) for l in general['lessons'] for e in l['exercises']))
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,channel='msedge');page=browser.new_page(viewport={'width':1600,'height':1000});page.set_default_timeout(12000);page.on('pageerror',lambda e:errors.append(str(e)))
        for theme,label in [('sequence-light','序光'),('white-violet','白紫')]:
            page.goto(f.url+'/#/settings');page.wait_for_load_state('networkidle');page.locator('.theme-option').filter(has_text=label).click()
            page.goto(f.url+'/#/course/'+imported[0]['course_id']);page.wait_for_load_state('networkidle')
            if theme=='white-violet':
                expect(page.get_by_role('heading',name=general['lessons'][-1]['title'],exact=True)).to_be_visible();check('theme-switch-keeps-reading-position')
                for _ in range(len(general['lessons'])-1):page.get_by_role('button',name='上一知识点',exact=True).click()
            for index,lesson in enumerate(general['lessons']):
                expect(page.get_by_role('heading',name=lesson['title'],exact=True)).to_be_visible();check(theme+'-'+lesson['id']+'-reading')
                check(theme+'-'+lesson['id']+'-no-automatic-pair',page.locator('.is-concept-pair').count()==0)
                if lesson['id']=='calculation':
                    expect(page.locator('.teaching-disclosure')).not_to_have_attribute('open','');expect(page.get_by_text('平均耗时=各路线占比乘对应耗时再求和。',exact=False)).to_be_visible();check(theme+'-required-formula-visible-while-details-closed')
                if lesson['id']=='code':expect(page.locator('.teaching-richtext pre')).to_contain_text('def largest')
                page.screenshot(path=str(f.WORKSPACE/(theme+'-'+lesson['id']+'.png')))
                if index<len(general['lessons'])-1:page.get_by_role('button',name='下一知识点 →',exact=True).click()
        page.goto(f.url+'/#/course/'+imported[1]['course_id']);page.wait_for_load_state('networkidle')
        expect(page.locator('.english-overview')).to_be_visible();page.screenshot(path=str(f.WORKSPACE/'english-overview.png'));check('english-overview-real-render')
        page.get_by_role('button',name='开始 / 继续训练 →',exact=True).click()
        expect(page.get_by_text('茶',exact=True)).to_be_visible();expect(page.get_by_role('textbox',name='第 1 个单词',exact=True)).to_be_visible()
        page.screenshot(path=str(f.WORKSPACE/'english-word-first.png'));check('english-sequence-starts-with-authored-first-item')
        check('no-page-errors',not errors);browser.close()
finally:
    runtime.service=previous
    result={'workspace':str(f.WORKSPACE),'checks':checks,'page_errors':errors,'real_learner_data_modified':False,'business_acceptance':'not_evaluated'}
    (f.WORKSPACE/'authoring-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
    f.server.shutdown();f.database.dispose()
