"""Disposable current-release acceptance cases; no installed workspace writes."""
from __future__ import annotations
import asyncio,json,time,ctypes,hashlib,copy
from pathlib import Path
from playwright.async_api import expect
from studyflow.modules.learning.notebook.document import plain


def seed(service,plan,workspace):
    english={'schema':'studyflow.course-package/6','package_id':'native-en-acceptance','plan_line':plan.name,'course':{'title':'原生英语验收 · 喜好表达','learning_mode':'english'},'lessons':[{'id':'likes','title':'表达喜好','blocks':[{'id':'concept','type':'concept','title':'I like','body':'I like 表达喜好。'}],'exercises':[{'id':'tea','title':'我喜欢茶','prompt':'我喜欢茶。','english':{'target':'I like tea.','objective_ids':['likes']}},{'id':'coffee','title':'我喜欢咖啡','prompt':'我喜欢咖啡。','english':{'target':'I like coffee.','objective_ids':['likes']}}]}]}
    english['lessons'][0]['exercises'][1]['english'].update(gloss='我喜欢咖啡。',explanation='I 是说话者，like 表示喜欢，coffee 是所喜欢的对象。')
    english['lessons'][0]['exercises'][0]['english']['sentence_parts']=[
        {'role':'subject','start':0,'end':1,'words':[{'gloss':'我','pos':'代词'}]},
        {'role':'predicate','start':1,'end':2,'words':[{'gloss':'喜欢','pos':'动词'}]},
        {'role':'object','start':2,'end':3,'words':[{'gloss':'茶','pos':'名词'}]}]
    teaching={'schema':'studyflow.course-package/5','package_id':'native-content-acceptance','plan_line':plan.name,'course':{'title':'原生教学验收 · 位权','learning_mode':'general'},'lessons':[{'id':'binary','title':'位权与进位','blocks':[{'id':'first','type':'concept','title':'先理解位权','body':'位权是该位一个单位代表的数值。'},{'id':'second','type':'concept','title':'再理解进位','body':'先定义，再计算。'},{'id':'detail','type':'details','title':'为什么相差两倍','summary':'低位的两个单位合成高位的一个单位。','body':'### 深入推导\n每位只有 0 和 1；单位变化来自基数。'},{'id':'compare','type':'comparison','title':'数制对照','columns':['数制','基数'],'rows':[['二进制','2'],['十进制','10']]}],'exercises':[{'id':'ex','title':'解释位权','prompt':'解释位权。'}]}]}
    teaching['lessons'][0]['blocks'].insert(2,{'id':'sections','type':'concept','title':'理解地址','sections':[{'id':'main','title':'地址定义','role':'main','body':'地址表示位置。'},{'id':'more','title':'地址补充','role':'supplement','summary':'位置与内容不相同。','body':'地址用于定位内容。','children':[{'id':'nested','title':'定位边界','role':'main','body':'先确定位置，再读取内容。'}]}]})
    teaching['lessons'][0]['exercises'][0]['review_reference']={'answer':'位权由位置与基数决定。','explanation':'相邻位代表的单位按基数变化。','criteria':['解释位置和单位的关系'],'source':'合成原生验收'}
    empty=copy.deepcopy(english);empty["package_id"]="native-empty-english";empty["course"]["title"]="空轮次重开验收"
    empty["lessons"][0]["exercises"][0]["english"]["sentence_parts"][2]["words"][0]["phonetic"]="/tiː/"
    result={}
    for name,package in [('english',english),('teaching',teaching),('empty',empty),('empty-white',{**copy.deepcopy(empty),'package_id':'native-empty-white','course':{**empty['course'],'title':'白紫空轮次重开验收'}})]:
        file=workspace/f'native-{name}.json';file.write_text(json.dumps(package,ensure_ascii=False),encoding='utf-8');result[name]=service.import_course_package(file)
    return result

async def stable(call,predicate=lambda value:bool(value),seconds=12):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=await call()
        if predicate(value):return value
        await asyncio.sleep(.1)
    raise AssertionError('Native state did not settle')

async def cases(main,window,service,plan,workspace,fixture,checks,process_id):
    async def invoke(page,method,params=None):
        data=await page.evaluate('''async({method,params})=>{const result=await window.__TAURI_INTERNALS__.invoke('engine_call',{request:{id:'native-acceptance-'+crypto.randomUUID(),method,params:params||{}}});if(!result.ok)throw Error(JSON.stringify(result.error));return result.data}''',{'method':method,'params':params})
        return data
    async def theme(name):
        await main.get_by_role('button',name='工作区',exact=True).first.click()
        # Previous case may still hold a pending course draft after window handoff.
        # Honor the real leave guard rather than changing location.hash around it.
        leave = main.get_by_role('button', name='重试保存后离开', exact=True)
        if await leave.count():
            await leave.click()
        await main.locator('.theme-option').filter(has_text=name).click()
    async def go_course(cid):
        await main.evaluate('(id)=>location.hash="/course/"+id',cid)
        await expect(main.locator('.study-workspace,.english-overview').first).to_be_visible()
    async def notes_panel():
        opener=main.get_by_role('button',name='打开答题与笔记',exact=True)
        if await opener.count():await opener.click()
        await main.get_by_role('tab',name='笔记',exact=True).click()
        await expect(main.get_by_role('textbox',name='连续笔记编辑器',exact=True)).to_be_visible()

    # A4: current native teaching template, keyboard disclosure and frozen-source restart.
    await theme('序光')
    teaching=fixture['teaching'];await go_course(teaching['course_id'])
    await expect(main.get_by_text('低位的两个单位合成高位的一个单位。',exact=True)).to_be_visible()
    assert await main.locator('.is-concept-pair').count()==0
    await expect(main.locator('.teaching-disclosure')).not_to_have_attribute('open','')
    await main.locator('.teaching-disclosure summary').focus();await main.keyboard.press('Enter')
    await expect(main.get_by_role('heading',name='深入推导',exact=True)).to_be_visible()
    await main.screenshot(path=str(workspace/'native-teaching-sequence-expanded.png'))
    checks.append('A4 sequence: summary visible, details keyboard expandable, concepts single column')
    opened=await invoke(main,'course.study.open',{'course_id':teaching['course_id'],'idempotency_key':'native-read-active'})
    old_sid=opened['study']['id'];old_source=await invoke(main,'course.study.get',{'study_session_id':old_sid})
    await main.get_by_role('button',name='用最新版重新开始',exact=True).click()
    await expect(main.get_by_role('dialog')).to_be_visible();await main.get_by_role('button',name='取消',exact=True).click()
    still=await invoke(main,'course.study.get',{'study_session_id':old_sid});assert still['study']['is_current']
    path=workspace/teaching['paths'][0];path.write_text(path.read_text(encoding='utf-8').replace('先定义，再计算。','新版正文：先定义，再计算。'),encoding='utf-8')
    await main.get_by_role('button',name='用最新版重新开始',exact=True).click()
    await main.get_by_role('button',name='保留历史并重新开始',exact=True).click()
    await expect(main.get_by_text('新版正文：先定义，再计算。',exact=True)).to_be_visible()
    historical=await invoke(main,'course.study.get',{'study_session_id':old_sid})
    assert historical['study']['abandoned_at'] is not None
    assert '新版正文' not in json.dumps(historical,ensure_ascii=False)
    checks.append('A4 native restart cancel is read-only; explicit restart preserves frozen previous round')
    active=await invoke(main,'course.study.open',{'course_id':teaching['course_id'],'idempotency_key':'native-new-round-read'})
    await invoke(main,'course.answers.draft.save',{'course_id':teaching['course_id'],'study_session_id':active['study']['id'],'answers':[{'exercise_id':active['lessons'][0]['exercises'][0]['id'],'answer_text':'隔离作答必须受到保护'}],'idempotency_key':'native-restart-blocker'})
    blocked_restart=await invoke(main,'course.study.restart.preview',{'study_session_id':active['study']['id']})
    assert not blocked_restart['can_restart'] and any(r['code']=='ANSWER_HISTORY_PRESENT' for r in blocked_restart['blocked_reasons'])
    checks.append('A4 native Engine restart preview protects rounds with already-saved answers')
    maintenance=await invoke(main,'course.study.restart.preview',{'study_session_id':active['study']['id'],'reset_current_state':True})
    assert maintenance['can_restart'] and maintenance['expected_state_hash']
    checks.append('1.8.7 native maintenance preview allows existing answers with state fingerprint')

    await theme('白紫');await go_course(teaching['course_id'])
    await expect(main.locator('.teaching-disclosure summary')).to_be_visible()
    await main.locator('.teaching-disclosure summary').click();await expect(main.get_by_role('heading',name='深入推导',exact=True)).to_be_visible()
    assert await main.locator('.is-concept-pair').count()==0
    await main.screenshot(path=str(workspace/'native-teaching-white-expanded.png'))
    checks.append('A4 white-violet has same disclosure, template and main scroll contract')

    # A1: real WebView2 input composition events are not claimed as a physical IME test.
    await notes_panel()
    prose=main.locator('.plan-notebook-v2 .card-prose').first
    await prose.click();await main.keyboard.insert_text('原生计划笔记：')
    await main.keyboard.press('Control+s');await asyncio.sleep(.05)
    # Capture actual entry and its stable content before exercising edit handoff.
    await asyncio.sleep(.3)
    before=await invoke(main,'plan.notebook.read',{'plan_line_id':plan.id,'limit':100})
    await main.get_by_role('button',name='其他工具操作',exact=True).click();await main.get_by_role('menuitem',name='拆为独立窗口 ↗',exact=True).click()
    notes=await window('tool-notes');await expect(notes.get_by_role('textbox',name='连续笔记编辑器',exact=True)).to_have_attribute('contenteditable','true')
    # Inspect real host state; not a test-only mock of the dock.
    await expect(main.locator('[data-tool="notes"] [contenteditable="true"]')).to_have_count(0)
    await notes.locator('.card-prose').first.click();await notes.keyboard.press('Control+End');await notes.keyboard.insert_text('独立窗继续编辑。');await notes.keyboard.press('Control+s')
    await stable(lambda:invoke(notes,'plan.notebook.read',{'plan_line_id':plan.id,'limit':100}),lambda r:any('独立窗继续编辑' in plain(e['content']) for e in r['entries']))
    await notes.get_by_role('button',name='放回侧栏 ↙',exact=True).click()
    await expect(main.get_by_role('textbox',name='连续笔记编辑器',exact=True)).to_contain_text('独立窗继续编辑。')
    checks.append('A1 native v2 edit ownership and same-plan content survive detach/put-back')

    # Q2/Q3/Q4: new contract through the actual frozen Engine/WebView, both shared themes.
    for selected_theme in ('序光','白紫'):
        await theme(selected_theme);await go_course(teaching['course_id'])
        if selected_theme=='序光':
            await expect(main.locator('.section-supplement')).not_to_have_attribute('open','')
        else:
            await expect(main.locator('.section-supplement')).to_have_attribute('open','')
            await main.locator('.section-supplement>summary').click()
        await expect(main.get_by_text('位置与内容不相同。',exact=True)).to_be_visible()
        await main.get_by_role('tab',name='本节大纲',exact=True).click()
        await main.get_by_role('button',name='定位边界',exact=True).click()
        await expect(main.get_by_text('先确定位置，再读取内容。',exact=True)).to_be_visible()
        await main.get_by_role('button',name='打开答题与笔记',exact=True).click()
        await main.get_by_role('tab',name='学习工具',exact=False).click()
        answer=main.locator('.knowledge-question textarea').first
        await answer.fill('原生合成答案，用于检查选中与后台保存。')
        await answer.focus();await main.keyboard.press('Control+a');await main.keyboard.press('ArrowLeft');await main.keyboard.press('Control+Shift+ArrowRight')
        box=await answer.bounding_box()
        await main.mouse.move(box['x']+18,box['y']+18);await main.mouse.down();await main.mouse.move(box['x']+145,box['y']+18,steps=8);await main.mouse.up()
        await main.keyboard.insert_text('原生替换')
        await asyncio.sleep(1.3)
        await main.keyboard.press('Control+a')
        selection=await answer.evaluate('(el)=>({start:el.selectionStart,end:el.selectionEnd,value:el.value})')
        persisted=await invoke(main,'course.answers.get',{'course_id':teaching['course_id']})
        assert any(row['draft'] and row['draft']['answer_text']==selection['value'] for row in persisted['answers'])

        await main.evaluate('window.dispatchEvent(new Event("focus"))');await asyncio.sleep(.6)
        await expect(main.locator('.study-material')).to_be_visible();await expect(answer).to_be_focused()
        assert selection==await answer.evaluate('(el)=>({start:el.selectionStart,end:el.selectionEnd,value:el.value})')
        assert await main.get_by_text('工作区有新反馈或状态更新',exact=False).count()==0
        checks.append('BUG-ANSWER-SELECT-01 '+selected_theme+': native drag/keyboard selection, replacement and silent autosave retain reader and focus')
        await main.locator('.answer-reference>summary').click()
        await expect(main.get_by_text('位权由位置与基数决定。',exact=True)).to_be_visible()
        await main.screenshot(path=str(workspace/('native-q234-'+('sequence' if selected_theme=='序光' else 'white')+'.png')))
        await main.evaluate('(pid)=>location.hash="/plan/"+pid',plan.id)
        card=main.locator('[data-course-group="PENDING"] .path-list li').filter(has=main.get_by_role('heading',name='原生教学验收 · 位权',exact=True))
        await card.get_by_role('button',name='暂放其他',exact=True).click()
        await main.get_by_role('button',name='确认移入',exact=True).click()
        held=main.locator('[data-course-group="OTHER"] .path-list li').filter(has=main.get_by_role('heading',name='原生教学验收 · 位权',exact=True))
        await expect(held).to_be_visible();await held.get_by_role('button',name='恢复到计划',exact=True).click()
        await expect(main.locator('[data-course-group="PENDING"]')).to_contain_text('原生教学验收 · 位权')
        checks.append('Q234 '+selected_theme+': nested section outline, frozen answer reference, membership hold/restore in actual WebView2')
    await theme('序光');await go_course(teaching['course_id']);await notes_panel()

    # Actual OS copy/paste (not synthetic ClipboardEvent); all existing formats kept in memory/restored.
    from native_clipboard_guard import ClipboardGuard
    async with ClipboardGuard(workspace):
        def focus_test_window():
            from ctypes import wintypes
            user=ctypes.windll.user32
            user.SetForegroundWindow.argtypes=[wintypes.HWND]
            callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
            handles=[]
            @callback
            def collect(hwnd,_):
                pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                if pid.value==process_id:
                    title=ctypes.create_unicode_buffer(512);user.GetWindowTextW(hwnd,title,512)
                    if title.value.startswith('StudyFlow') and not ('笔记' in title.value or '练习' in title.value):handles.append(hwnd)
                return True
            user.EnumWindows(collect,0)
            if len(handles)!=1:raise RuntimeError('Expected one isolated main native window; found '+str(len(handles)))
            if not user.IsWindowVisible(handles[0]):user.ShowWindow(handles[0],5)
            if user.SetForegroundWindow(handles[0]):return True
            user.keybd_event(0x12,0,0,0);user.keybd_event(0x12,0,2,0)
            return bool(user.SetForegroundWindow(handles[0]))
        focused=focus_test_window()
        if not focused:
            checks.append("UNVERIFIED A1 physical system clipboard: foreground activation denied by Windows")
        if focused:
            clipboard_before=await invoke(main,'plan.notebook.read',{'plan_line_id':plan.id,'limit':100})
            marker_before=sum(plain(e['content']).count('原生计划笔记') for e in clipboard_before['entries'])
            await main.locator('.card-prose').filter(has_text='原生计划笔记').first.click()
            await main.evaluate("""()=>{const marker='原生计划笔记';const root=[...document.querySelectorAll('.card-prose')].find(el=>el.textContent.includes(marker));if(!root)throw Error('controlled clipboard marker is missing');const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let text;while(text=walker.nextNode()){const start=text.textContent.indexOf(marker);if(start<0)continue;const range=document.createRange();range.setStart(text,start);range.setEnd(text,start+marker.length);const selected=getSelection();selected.removeAllRanges();selected.addRange(range);if(selected.toString()!==marker)throw Error('controlled clipboard selection is wrong');return}throw Error('marker text node is missing')}""")
            def system_key(letter):
                user=ctypes.windll.user32
                user.keybd_event(0x11,0,0,0);user.keybd_event(ord(letter),0,0,0);user.keybd_event(ord(letter),0,2,0);user.keybd_event(0x11,0,2,0)
            # Prove that physical Ctrl+C reached this WebView before physical paste.
            # Never paste unverified user clipboard content into the synthetic notebook.
            def has_controlled_clipboard():
                from ctypes import wintypes
                user=ctypes.windll.user32;kernel=ctypes.windll.kernel32
                user.GetClipboardData.argtypes=[wintypes.UINT];user.GetClipboardData.restype=wintypes.HANDLE
                kernel.GlobalLock.argtypes=[wintypes.HANDLE];kernel.GlobalLock.restype=ctypes.c_void_p
                kernel.GlobalUnlock.argtypes=[wintypes.HANDLE]
                if not user.OpenClipboard(None):return False
                try:
                    handle=user.GetClipboardData(13)
                    if not handle:return False
                    pointer=kernel.GlobalLock(handle)
                    if not pointer:return False
                    try:return ctypes.wstring_at(pointer)=='原生计划笔记'
                    finally:kernel.GlobalUnlock(handle)
                finally:user.CloseClipboard()
            system_key('C');await asyncio.sleep(.2)
            copied=has_controlled_clipboard()
            clipboard_evidence={'controlled_copy_received':copied,'webview_focus':await main.evaluate('document.hasFocus()')}
            if not copied:
                checks.append('UNVERIFIED A1 physical clipboard: controlled OS copy did not arrive; paste not attempted')
            else:
                await main.evaluate("()=>{window.__nativePasteCount=0;document.addEventListener('paste',()=>window.__nativePasteCount++,{capture:true})}")
                await main.keyboard.press('Control+End');await main.keyboard.press('Enter');system_key('V');await asyncio.sleep(.2)
                clipboard_evidence['paste_events']=await main.evaluate('window.__nativePasteCount')
                if not clipboard_evidence['paste_events']:
                    checks.append('UNVERIFIED A1 physical clipboard: OS paste event did not arrive in WebView')
                else:
                    await main.keyboard.press('Control+s')
                    pasted=await stable(lambda:invoke(main,'plan.notebook.read',{'plan_line_id':plan.id,'limit':100}),lambda r:sum(plain(e['content']).count('原生计划笔记') for e in r['entries'])>=marker_before+1)
                    assert pasted['version']>clipboard_before['version']
                    checks.append('A1 actual system copy/paste roundtrip; original clipboard formats restored after test')
            (workspace/'native-clipboard-evidence.json').write_text(json.dumps(clipboard_evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    # Native failure UI: injected bridge rejection, never make the user database read-only.
    fault_file=workspace/'fault-notebook-save';fault_file.write_text('inject',encoding='ascii')
    await main.locator('.card-prose').first.click();await main.keyboard.press('Control+End');await main.keyboard.insert_text('尚未写入的失败内容。');await main.keyboard.press('Control+s')
    await expect(main.locator('footer.notebook-alert')).to_be_visible()
    await main.evaluate('location.hash="/today"');await expect(main.get_by_role('alertdialog')).to_be_visible()
    await main.screenshot(path=str(workspace/'native-notebook-save-failure-discard.png'))
    await main.get_by_role('button',name='不保存并离开',exact=True).click()
    await expect(main.get_by_role('heading',name='学习控制台',exact=True)).to_be_visible()
    fault_file.unlink()
    check_state=await invoke(main,'plan.notebook.read',{'plan_line_id':plan.id,'limit':100})
    assert all('尚未写入的失败内容' not in plain(e['content']) for e in check_state['entries'])
    checks.append('A1 actual native failure dialog allows explicit discard and navigation without forced save')

    # A3: complete native English training, real keyboard and focus correction.
    await theme('序光');await go_course(fixture['english']['course_id'])
    await main.get_by_role('button',name='开始 / 继续训练 →',exact=True).click()
    await expect(main.get_by_role('heading',name='我喜欢茶。',exact=True)).to_be_visible()
    # Native voice requests are examined separately below; avoid autoplay while checking input.
    await main.evaluate("localStorage.setItem('studyflow:english-speech:v1',JSON.stringify({volume:20,muted:false,auto:false,accent:'en-US'}))")
    await main.reload();await expect(main.get_by_role('heading',name='我喜欢茶。',exact=True)).to_be_visible()
    w1=main.get_by_role('textbox',name='第 1 个单词');w2=main.get_by_role('textbox',name='第 2 个单词');w3=main.get_by_role('textbox',name='第 3 个单词')
    await w2.focus();await w2.press('Control+Semicolon')
    await expect(main.locator('.english-breakdown')).to_be_visible();await expect(main.locator('.part-role')).to_have_text(['主语','谓语','宾语'])
    await expect(w2).to_be_focused();await expect(w2).to_be_enabled()
    assert await main.locator('.english-answer').count()==0
    await main.screenshot(path=str(workspace/'native-english-analysis.png'))
    study_id=(await main.evaluate('location.hash')).split('/english/')[1].split('?')[0]
    view=await invoke(main,'course.english.get',{'study_session_id':study_id})
    assert view['items'][0]['assisted']
    lookup_started=time.monotonic()
    metadata=await invoke(main,'audio.dictionary.lookup',{'study_session_id':study_id,'exercise_id':view['items'][0]['exercise_id'],'word_index':1,'accent':'en-US'})
    metadata_ms=(time.monotonic()-lookup_started)*1000
    assert metadata_ms<600,metadata_ms
    (workspace/'native-dictionary-latency.json').write_text(json.dumps({'ms':metadata_ms,'status':metadata['metadata_status'],'scope':'synthetic-only'}),encoding='utf-8')
    await w2.press('Control+Semicolon');await expect(main.locator('.english-breakdown')).to_have_count(0)
    checks.append('A3 native explicit analysis retains input/focus and tracks text assistance')
    checks.append('A3 frozen dictionary lookup returns without holding native Engine')
    await w1.fill('I');await w1.press('Space');await expect(w2).to_be_focused();await w2.fill('lik');await w2.press('Space');await expect(w3).to_be_focused();await w3.fill('tea');await w3.press('Enter')
    await expect(main.get_by_text('原输入：lik',exact=True)).to_be_visible();await expect(w2).to_be_focused()
    await main.screenshot(path=str(workspace/'native-english-correction.png'))
    await w2.press('l');await w2.type('ike');await w2.press('Enter');await expect(main.locator('.english-target')).to_have_text('I like tea');assert await main.locator('.english-breakdown').count()==0
    checks.append('A3 native space/enter navigation, exact wrong-word focus, retained original and first-key replacement')
    await main.evaluate("()=>{const NativeAudio=window.Audio;window.__nativeAudio=[];window.Audio=class extends NativeAudio{constructor(url){super(url);this.__requestedUrl=url;window.__nativeAudio.push(this)}};window.__nativeSpeechEvents=[];if(window.speechSynthesis){const speak=window.speechSynthesis.speak.bind(window.speechSynthesis);window.speechSynthesis.speak=utterance=>{for(const type of [\"start\",\"end\",\"error\"])utterance.addEventListener(type,event=>window.__nativeSpeechEvents.push({type,error:event.error||null}));speak(utterance)}}}")
    audio_evidence=[]
    await main.get_by_role('button',name='训练设置',exact=True).click()
    for accent,voice_type in [('en-US','2'),('en-GB','1')]:
        await main.get_by_label('口音请求').select_option(accent)
        previous_audio_count=await main.evaluate('window.__nativeAudio.length')
        await main.get_by_role('button',name="Ctrl ' 整句朗读",exact=True).click()
        await main.wait_for_function('(count)=>window.__nativeAudio.length>count',arg=previous_audio_count)
        played=False
        try:
            await main.wait_for_function("()=>window.__nativeAudio.at(-1)?.currentTime>0",timeout=8000)
            await main.wait_for_function("()=>window.__nativeAudio.at(-1)?.ended===true",timeout=12000)
            played=True
        except Exception:pass
        actual=await main.evaluate("()=>{const a=window.__nativeAudio.at(-1);return a?{src:a.__requestedUrl,activeSrc:a.src,readyState:a.readyState,currentTime:a.currentTime,duration:Number.isFinite(a.duration)?a.duration:null,paused:a.paused,ended:a.ended,error:a.error?.code||null}:null}")
        attempts=await main.evaluate('(start)=>window.__nativeAudio.slice(start).map(a=>({src:a.__requestedUrl,currentTime:a.currentTime,error:a.error?.code||null}))',previous_audio_count)
        if attempts:assert 'type='+voice_type in attempts[0]['src']
        notice=await main.locator('.english-assistance').inner_text() if await main.locator('.english-assistance').count() else ''
        audio_evidence.append({'requested_accent':accent,'played':played,'actual':actual,'attempts':attempts,'notice':notice})
    (workspace/'native-audio-playback.json').write_text(json.dumps(audio_evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    voices=await main.evaluate("()=>({available:!!window.speechSynthesis,voices:window.speechSynthesis?.getVoices().map(v=>({lang:v.lang,name:v.name}))||[],speaking:window.speechSynthesis?.speaking,events:window.__nativeSpeechEvents||[],notice:document.querySelector('.english-assistance')?.textContent||''})")
    (workspace/'native-system-voice.json').write_text(json.dumps(voices,ensure_ascii=False,indent=2),encoding='utf-8')
    checks.append('A3 actual sentence playback for both accent requests (announced alternate voice when unavailable)' if all(e['played'] for e in audio_evidence) else 'UNVERIFIED A3 online dictionary voice; local fallback evidence retained')
    await main.get_by_role('button',name='笔记',exact=True).click()
    assert await main.get_by_role('tab',name='练习',exact=True).count()==0
    pending_retry=main.get_by_role('button',name='原键重试／读取冲突',exact=True)
    if await pending_retry.count():
        await pending_retry.click();await expect(main.locator('footer.notebook-alert')).to_have_count(0)
        checks.append('A1 reopened failed recovery is replayed only after explicit original-key retry')
    recovery_choice=main.get_by_role('button',name='保留工作区版本',exact=True)
    if await recovery_choice.count():await recovery_choice.click()
    await main.get_by_role('button',name='弹出笔记窗口',exact=True).click()
    en_notes=await window('tool-notes');await expect(en_notes.get_by_role('textbox',name='连续笔记编辑器',exact=True)).to_be_visible()
    await en_notes.get_by_role('button',name='放回侧栏 ↙',exact=True).click()
    await main.get_by_role('button',name='关闭侧栏',exact=True).click()
    await main.get_by_role('button',name='下一项 →',exact=True).click();await expect(main.get_by_role('heading',name='我喜欢咖啡。',exact=True)).to_be_visible()
    await main.reload();await expect(main.get_by_role('heading',name='我喜欢咖啡。',exact=True)).to_be_visible()
    await main.screenshot(path=str(workspace/'native-english-resume.png'))
    checks.append('A3 English only-notes real detach/put-back and last position resumes after reload')
    await main.get_by_role('textbox',name='第 1 个单词').press('Control+Semicolon')
    await expect(main.locator('.fallback-meaning')).to_have_text('我喜欢咖啡。')
    await expect(main.get_by_role('button',name='朗读单词 coffee',exact=True)).to_be_visible()
    assert await main.locator('.part-role').count()==0
    await main.screenshot(path=str(workspace/'native-fallback-sequence.png'))
    await main.get_by_role('textbox',name='第 1 个单词').press('Control+Semicolon')
    checks.append('A3 sequence native missing annotation uses real meaning without inferred grammar')
    await main.get_by_role('button',name='← 返回课程',exact=True).click()
    await theme('白紫');await go_course(fixture['english']['course_id']);await main.get_by_role('button',name='开始 / 继续训练 →',exact=True).click();await expect(main.get_by_role('heading',name='我喜欢咖啡。',exact=True)).to_be_visible()
    await main.get_by_role('textbox',name='第 1 个单词').press('Control+Semicolon')
    await expect(main.locator('.fallback-meaning')).to_have_text('我喜欢咖啡。')
    assert await main.locator('.part-role').count()==0
    checks.append('A3 white-violet native missing annotation keeps the same semantic fallback')
    # Resize only our isolated OS window; do not expand the application's capability ACL for tests.
    from ctypes import wintypes
    user=ctypes.windll.user32;handles=[]
    callback=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    @callback
    def collect_main(hwnd,_):
        pid=wintypes.DWORD();user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid));title=ctypes.create_unicode_buffer(512);user.GetWindowTextW(hwnd,title,512)
        if pid.value==process_id and title.value.startswith('StudyFlow') and not ('笔记' in title.value or '练习' in title.value):handles.append(hwnd)
        return True
    user.EnumWindows(collect_main,0);assert len(handles)==1
    if await main.evaluate('window.__TAURI_INTERNALS__.invoke("plugin:window|is_maximized",{label:"main"})'):
        await main.evaluate('window.__TAURI_INTERNALS__.invoke("plugin:window|toggle_maximize",{label:"main"})')
    # GetWindowRect/SetWindowPos must share the application's per-monitor coordinate space.
    # This changes only the harness thread's context, never Windows display settings.
    user.SetThreadDpiAwarenessContext.argtypes=[ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype=ctypes.c_void_p
    previous_dpi=user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    if user.IsIconic(handles[0]):
        user.ShowWindow(handles[0],9)
        await stable(lambda:asyncio.to_thread(lambda:not user.IsIconic(handles[0])))
    original_rect=wintypes.RECT();user.GetWindowRect(handles[0],ctypes.byref(original_rect))
    current_size=await main.evaluate('({width:innerWidth,height:innerHeight})')
    user.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint]
    assert user.SetWindowPos(handles[0],None,0,0,round((original_rect.right-original_rect.left)*960/current_size['width']),round((original_rect.bottom-original_rect.top)*720/current_size['height']),0x16)
    resized=await main.evaluate('({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})')
    (workspace/'native-resize-evidence.json').write_text(json.dumps({'before':current_size,'after_request':resized,'rect':[original_rect.left,original_rect.top,original_rect.right,original_rect.bottom]},indent=2),encoding='utf-8')
    await main.wait_for_function('()=>innerWidth<=970')
    assert await main.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    frame=await main.evaluate('''()=>{const footer=document.querySelector('.english-training-footer');return {footerBottom:footer.getBoundingClientRect().bottom,viewport:innerHeight,documentHeight:document.documentElement.scrollHeight}}''')
    assert frame['footerBottom']<=frame['viewport']+2 and frame['documentHeight']<=frame['viewport']+2,frame
    await expect(main.get_by_role('textbox',name='第 1 个单词')).to_be_visible()
    await main.screenshot(path=str(workspace/'native-english-white.png'))
    assert user.SetWindowPos(handles[0],None,0,0,original_rect.right-original_rect.left,original_rect.bottom-original_rect.top,0x16)
    if previous_dpi:user.SetThreadDpiAwarenessContext(previous_dpi)
    checks.append('A3 white-violet shares complete English training flow')

    # A5: generated connection text is captured at the real Copy action. System clipboard separately guarded.
    await main.get_by_role('button',name='← 返回课程',exact=True).click()
    await main.get_by_role('button',name='工作区',exact=True).first.click()
    await expect(main.get_by_role('button',name='复制Agent接入说明',exact=True)).to_be_enabled()
    installation=await invoke(main,'system.installation')
    assert installation['cli_available'] and installation['skill_available'] and installation['agent_ready']
    assert Path(installation['cli_path']).is_file() and Path(installation['skill_path']).is_file()
    assert Path(installation['workspace']).resolve()==workspace.resolve()
    await main.evaluate("()=>{window.__capturedConnection='';Object.defineProperty(navigator.clipboard,'writeText',{configurable:true,value:async(text)=>{window.__capturedConnection=text}})}")
    await main.get_by_role('button',name='复制Agent接入说明',exact=True).click()
    prompt=await main.evaluate('window.__capturedConnection')
    assert installation['cli_path'] in prompt and installation['skill_path'] in prompt and installation['workspace'] in prompt
    assert 'studyflow\\.exe' not in prompt and 'local.studyflow\\.desktop' not in prompt
    (workspace/'native-agent-connection.json').write_text(json.dumps({'installation':installation,'prompt':prompt,'clipboard_mode':'actual settings copy handler with capture; no user clipboard overwrite'},ensure_ascii=False,indent=2),encoding='utf-8')
    await main.screenshot(path=str(workspace/'native-agent-settings-paths.png'))
    checks.append('A5 actual release settings generate confirmed CLI/Skill/workspace paths from installed resources')

    # 1.8.6: native restart guards, aligned authored rows and no metadata UI.
    for theme_name in ['序光','白紫轻学']:
        await theme(theme_name)
        cid=fixture['empty' if theme_name=='序光' else 'empty-white']['course_id']
        old=await invoke(main,'course.study.open',{'course_id':cid,'idempotency_key':'empty-open-'+theme_name})
        old_id=old['study']['id']
        await go_course(cid)
        await main.get_by_role('button',name='用最新材料重新开始',exact=True).click()
        await expect(main.get_by_role('heading',name='用最新材料重新开始？',exact=True)).to_be_visible()
        await main.get_by_role('button',name='确认重新开始',exact=True).click()
        await expect(main.get_by_role('textbox',name='第 1 个单词',exact=True)).to_be_visible()
        sid=await main.evaluate('location.hash.split("/english/")[1]')
        assert sid and sid!=old_id
        previous=await invoke(main,'course.study.get',{'study_session_id':old_id})
        assert previous['course']['study_status']=='ABANDONED'
        await main.get_by_role('textbox',name='第 1 个单词',exact=True).press('Control+Semicolon')
        await expect(main.locator('.english-breakdown')).to_be_visible()
        await expect(main.locator('.part-word small').filter(has_text='/tiː/')).to_be_visible()
        await expect(main.locator('.english-metadata-status')).to_have_count(0)
        assert await main.get_by_role('button',name='重试辅助信息',exact=True).count()==0
        tops=await main.locator('.english-breakdown .part-word strong').evaluate_all('(els)=>els.map(el=>el.getBoundingClientRect().top)')
        assert max(tops)-min(tops)<=1,tops
        current=await invoke(main,'course.english.get',{'study_session_id':sid})
        start=time.monotonic()
        metadata=await invoke(main,'audio.dictionary.metadata',{'study_session_id':sid,'exercise_id':current['items'][0]['exercise_id'],'accent':'en-GB'})
        assert time.monotonic()-start<1.5
        assert metadata['sentence_transcription'] is False and len(metadata['words'])==3
        await main.screenshot(path=str(workspace/('native-186-'+theme_name+'.png')))
        # This marker affects only the disposable protocol proxy, never product default behavior.
        await main.get_by_role('textbox',name='第 1 个单词',exact=True).press('Control+Semicolon')
        for i,word in enumerate(('I','like','tea')):
            await main.get_by_role('textbox',name=f'第 {i+1} 个单词',exact=True).fill(word)
        (workspace/'fault-notebook-save.english-check').write_text('synthetic protocol fault',encoding='utf-8')
        await main.get_by_role('button',name='检查答案',exact=False).click()
        problem=main.get_by_role('alertdialog',name='保存尚未确认',exact=True)
        await expect(problem).to_be_visible()
        await expect(main.locator('.english-error')).to_have_count(0)
        await problem.get_by_text('技术信息',exact=True).click()
        await expect(problem.get_by_text('已写入本地诊断日志',exact=False)).to_be_visible()
        log=workspace/'diagnostics/ui-diagnostics.jsonl'
        assert log.exists() and all(set(json.loads(line))<={'event_id','context','code','operation','request_id','response_id','recorded_at_unix'} for line in log.read_text(encoding='utf-8').splitlines())
        await problem.get_by_role('button',name='暂时关闭',exact=True).click()
        await expect(problem).not_to_be_visible()
        await expect(main.get_by_role('textbox',name='第 2 个单词',exact=True)).to_have_value('like')
        await main.get_by_role('button',name='保存待确认',exact=True).click()
        await problem.get_by_role('button',name='重试原操作',exact=True).click()
        await expect(problem).not_to_be_visible()
        await expect(main.get_by_role('button',name='下一项 →',exact=True)).to_be_visible()
        checks.append('native '+theme_name+' wrong-id reply: metadata log persisted, no banner, dismiss retains input, original check replay succeeds')
        await main.get_by_role('button',name='← 返回课程',exact=True).click()
        await main.get_by_role('button',name='用最新材料重新开始',exact=True).click()
        await expect(main.locator('.study-restart-dialog')).to_be_visible()
        await expect(main.get_by_role('button',name='确认重新开始',exact=True)).to_be_visible()
        await main.get_by_role('button',name='保留当前轮次',exact=True).click()
        checks.append('1.8.7 '+theme_name+' confirmed reset available after hints; cancel preserves current state; authored phonetics aligned')
