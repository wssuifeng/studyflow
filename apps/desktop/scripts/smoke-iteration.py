"""SF-12 real Vue/Engine closed loop in an isolated synthetic workspace."""
import json,time
from pathlib import Path
from smoke_workbench_support import ROOT,WORKSPACE,service,engine,server,database,plan,courses,url
from playwright.sync_api import sync_playwright,expect
from studyflow.modules.reviews.retests import publish
from sqlalchemy import select
from studyflow.modules.learning.models import Submission

RESULT=ROOT/"test-results/implementation-20261003"
RESULT.mkdir(parents=True,exist_ok=True)

def main():
    errors=[]
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            page=browser.new_page(viewport={"width":1440,"height":950})
            page.set_default_timeout(12000)
            page.on("pageerror",lambda error:errors.append(str(error)))
            page.goto(url+"/#/course/"+courses[0]);page.wait_for_load_state("networkidle")
            expect(page.get_by_role("heading",name="合成课程1",exact=True)).to_be_visible()
            page.get_by_role("button",name="打开答题与笔记",exact=True).click()
            study=service.open_course_study(courses[0],"browser-existing")
            ids=[lesson["exercises"][0]["id"] for lesson in study["lessons"]]
            # Three knowledge points, one course, automatically saved then one submit.
            for i,identifier in enumerate(ids):
                if i:page.get_by_role("button",name="下一知识点",exact=False).last.click()
                page.locator("#answer-"+identifier).fill(f"合成原答案{i+1}，需要保留。")
                page.wait_for_timeout(1400)
            page.get_by_role("button",name="提交",exact=False).last.click()
            page.wait_for_timeout(1200)
            sheet=service.course_answer_sheet(courses[0],study["study"]["id"])
            parents=[item["submission"]["id"] for item in sheet["answers"]]
            issue={"quote":"合成原答案1","location":"第1句","reason":"概念缺少条件","guidance":"补充发生条件","next_action":"在课程中修正"}
            service.write_review(parents[0],"需要补充条件",decision="REVISION_REQUIRED",issues=[issue],idempotency_key="browser-review-1")
            service.write_review(parents[1],"独立新题复测",decision="RETEST_REQUIRED",idempotency_key="browser-review-2")
            service.write_review(parents[2],"通过",decision="PASSED",idempotency_key="browser-review-3")
            task=publish(service.reviews,parents[1],"合成独立复测题","请分析新的失败条件。","验证独立分析","browser-retest",agent_reference="PRIVATE-NOT-FOR-UI")
            page.goto(url+"/#/submission/"+parents[0]);page.wait_for_load_state("networkidle")
            expect(page.get_by_text("合成原答案1",exact=True)).to_be_visible()
            assert page.locator("textarea").count()==0
            page.get_by_role("button",name="定位到修正题",exact=False).click()
            expect(page.locator("#answer-"+ids[0])).to_be_visible()
            page.locator("#answer-"+ids[0]).fill("补充条件的合成修正答案。")
            # Simulated storage quota failures must not prevent a successful Core save.
            page.evaluate("() => {window.__originalSetItem=Storage.prototype.setItem;Storage.prototype.setItem=function(){throw new DOMException('synthetic quota full','QuotaExceededError')};}")
            page.wait_for_timeout(1500)
            page.get_by_role("button",name="下一知识点",exact=False).last.click()
            expect(page.get_by_text("请分析新的失败条件。",exact=True)).to_be_visible()
            assert "PRIVATE-NOT-FOR-UI" not in page.content()
            page.locator("#answer-"+ids[1]).fill("新的失败条件是合成条件。")
            page.wait_for_timeout(1500)
            page.evaluate("() => {Storage.prototype.setItem=window.__originalSetItem;}")
            page.get_by_role("button",name="下一知识点",exact=False).last.click()
            page.get_by_role("button",name="提交",exact=False).last.click();page.wait_for_timeout(1600)
            sheet=service.course_answer_sheet(courses[0],study["study"]["id"])
            for item in sheet["answers"][:2]:
                assert item["submission"]["status"]=="WAITING_REVIEW"
                service.write_review(item["submission"]["id"],"通过",decision="PASSED",idempotency_key="pass-"+item["submission"]["id"])
            assert service.course_study_detail(study["study"]["id"])["course"]["study_status"]=="PASSED"
            page.goto(url+"/#/plan/"+plan.id);page.wait_for_load_state("networkidle")
            expect(page.get_by_role("button",name="计划学习笔记",exact=True)).to_be_visible()
            page.get_by_role("button",name="计划学习笔记",exact=True).click()
            page.get_by_role("button",name="＋ 写笔记",exact=True).click()
            page.get_by_role("textbox",name="笔记：计划",exact=True).fill("中文检索与连续计划笔记。")
            page.wait_for_timeout(1600)
            page.get_by_role("textbox",name="搜索计划笔记").fill("中文检索")
            page.get_by_role("button",name="阅读模式",exact=True).click()
            expect(page.locator(".notebook-reading")).to_contain_text("中文检索")
            with page.expect_download() as download:page.get_by_role("button",name="导出 Markdown",exact=True).click()
            download.value.save_as(str(RESULT/"synthetic-notes.md"))
            screenshots=[]
            for route,name in [("/today","console-v17"),("/queue","queue-v17"),("/plan/"+plan.id,"plan-v17"),("/settings","workspace-v17")]:
                page.goto(url+"/#"+route);page.wait_for_load_state("networkidle");page.wait_for_timeout(300)
                page.screenshot(path=str(RESULT/(name+".png")),full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+2")
                screenshots.append(name)
            page.set_viewport_size({"width":720,"height":800})
            page.goto(url+"/#/course/"+courses[1]);page.wait_for_load_state("networkidle");page.wait_for_timeout(300)
            page.screenshot(path=str(RESULT/"reader-720.png"),full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+2")
            # A forged/mistyped deep link must not mount another course's editor.
            page.goto(url+"/#/course/"+courses[1]+"?study="+study["study"]["id"])
            page.wait_for_load_state("networkidle")
            expect(page.locator(".study-workspace")).to_have_count(0)
            expect(page.get_by_text("课程暂时无法打开，没有覆盖学习记录。",exact=True)).to_be_visible()
            # Old rounds are read-only and opening their link does not create a third round.
            latest=service.open_course_study(courses[0],"browser-explicit-review-round",review_round=True)
            page.goto(url+"/#/course/"+courses[0]+"?study="+study["study"]["id"])
            expect(page.get_by_text("冻结来源 · 只读，不开启学习轮次",exact=True)).to_be_visible()
            assert "/#/source/"+study["study"]["id"] in page.url
            assert service.open_course_study(courses[0],"browser-round-check")["study"]["id"]==latest["study"]["id"]
            browser.close()
            if errors:raise AssertionError(errors)
            result={"ok":True,"scope":"synthetic-only","workflow":"read/save/whole-submit/structured-review/correction/new-retest/passed/notebook/search/export","page_errors":errors,"screenshots":screenshots,"narrow_width":720,"deep_link_guard":True,"readonly_history":True}
            (RESULT/"browser-result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
            print(json.dumps(result,ensure_ascii=False))
    finally:
        server.shutdown();engine.close();database.dispose()

if __name__=="__main__":main()
