"""Regression: the real Vue confirmation resets a submitted stale course, both themes.

Uses only the disposable fixture workspace; successful checks do not take screenshots.
"""
import json
import time
from playwright.sync_api import sync_playwright, expect
from sqlalchemy import select
from studyflow.modules.learning.models import CourseStudySession
from studyflow.modules.reviews.queue_queries import summary
import smoke_workbench_support as f


def run():
    errors=[]
    checks=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        try:
            for theme,cid in zip(("white-violet","sequence-light"),f.courses):
                opened=f.service.open_course_study(cid,"stale-"+theme,plan_line_id=f.plan.id)
                sid=opened["study"]["id"]
                f.service.write_course_answers(cid,[{"exercise_id":e["id"],"answer_text":"Synthetic submitted answer"}
                    for lesson in opened["lessons"] for e in lesson["exercises"]],"SUBMIT","submitted-"+theme,study_session_id=sid)
                f.service.save_study_note(sid,opened["lessons"][0]["id"],"Keep my note",0,"note-"+theme)
                path=f.WORKSPACE/opened["lessons"][0]["markdown_path"]
                path.write_text(path.read_text(encoding="utf-8")+"\n\n合成新版内容已经发布。",encoding="utf-8")
                page=browser.new_page(viewport={"width":1440,"height":960})
                page.on("pageerror",lambda e:errors.append(str(e)))
                pref={"schema_version":"studyflow.theme-preference/1","selected_theme_id":theme,
                    "custom_themes":[],"revision":{"clock":0,"source":"reset-regression"}}
                page.add_init_script("localStorage.setItem('studyflow:theme-preference:v1',JSON.stringify(%s))"%json.dumps(pref))
                page.goto(f.url+"/#/course/"+cid+"?study="+sid+"&plan="+f.plan.id)
                expect(page.locator("html")).to_have_attribute("data-theme-id",theme)
                page.get_by_role("button",name="用最新版重新开始",exact=True).click()
                dialog=page.locator(".study-restart-dialog")
                expect(dialog).to_be_visible()
                expect(dialog).to_contain_text("待批改状态")
                dialog.get_by_role("button",name="取消",exact=True).click()
                assert f.service.course_study_detail(sid)["study"]["is_current"]
                page.get_by_role("button",name="用最新版重新开始",exact=True).click()
                page.get_by_role("button",name="保留历史并重新开始",exact=True).click()
                expect(dialog).not_to_be_visible()
                deadline=time.monotonic()+12
                while time.monotonic()<deadline:
                    with f.service.session(read_only=True) as db:
                        old=db.get(CourseStudySession,sid)
                        current=db.scalar(select(CourseStudySession).where(CourseStudySession.course_id==cid,CourseStudySession.abandoned_at.is_(None)))
                        if old.abandoned_at is not None and current and current.id!=sid:
                            new_id=current.id;break
                    page.wait_for_timeout(100)
                else:raise AssertionError("reset did not persist")
                expect(page.locator(".study-version-note")).to_have_count(0)
                assert "study="+new_id in page.url
                assert not summary(f.service.reviews,course_id=cid)["items"]
                assert any(n["text"]=="Keep my note" for n in f.service.study_notes(sid)["notes"])
                assert not f.service.course_study_detail(new_id)["study"]["source_changed"]
                page.reload()
                expect(page.locator(".study-workspace")).to_be_visible()
                assert "study="+new_id in page.url
                page.close();checks.append(theme+": submitted stale round -> confirmed reset -> latest -> reload")
            assert not errors,errors
            print(json.dumps({"ok":True,"checks":checks,"page_errors":errors,"workspace":str(f.WORKSPACE)},ensure_ascii=False))
        finally:browser.close()


if __name__=="__main__":
    try:run()
    finally:f.server.shutdown();f.database.dispose()
