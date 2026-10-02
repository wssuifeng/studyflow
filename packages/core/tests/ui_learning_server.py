"""Disposable synthetic UI fixture server; never connects to an installed workspace.
Run with --workspace pointing to a NEW empty directory, and --frontend to a built Vue dist.
The test database and generated files are retained as local verification evidence.
"""
from __future__ import annotations
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from studyflow.config import Settings
from studyflow.db import build_engine, build_session_factory, init_db
from studyflow.engine import StudyFlowEngine
from studyflow.services import AppService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--frontend", required=True, type=Path)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    workspace=args.workspace.resolve()
    if workspace.exists() and any(workspace.iterdir()):
        raise SystemExit("Refusing non-empty workspace; use a new synthetic test directory.")
    if not (args.frontend / "index.html").is_file(): raise SystemExit("Build Vue first.")
    workspace.mkdir(parents=True,exist_ok=True)
    settings=Settings(workspace_root=workspace,database_url=f"sqlite:///{(workspace/'synthetic.db').as_posix()}")
    settings.ensure_layout()
    database=build_engine(settings); init_db(database)
    app=AppService(settings,build_session_factory(database))
    plan=app.create_plan_line("核心学习链验证（合成数据）")
    files=[]
    for number, title in ((1,"状态与事务"),(2,"事务之后的处理"),(3,"下一门课程")):
        course="课程一：连续学习与事务" if number<3 else "课程二：继续学习与反馈"
        path=workspace/f"content/lesson-{number}.md"
        body=f"# {title}\n\n课程的材料与练习应该连贯，保存草稿不等于正式提交，提交不等于已经掌握。\n\n"
        body+="## 从一次操作理解生命周期\n\n先保留输入，再确认保存结果。正式提交后，原答案只读；反馈返回后，产生新的修正版。\n\n"
        body+="```text\n学习 → 草稿 → 提交 → 批改 → 修正或复测\n```\n\n"
        body+="## 可以暂时跳过\n\n学习时允许留空，在最后提交时定位需要补齐的题目。材料被更新时，本次学习仍保留开始时版本。\n\n"
        questions=[{"title":f"练习{number}-1","prompt":"说明草稿保存与正式提交的区别。","requirements":"说明状态变化和原答案保护。"}]
        if number==1: questions.append({"title":"练习1-2","prompt":"为什么阅读完成不能直接表示已经掌握？","requirements":"结合批改和复测说明。"})
        import yaml
        path.write_text("---\n"+yaml.safe_dump({"plan_line":plan.name,"course":course,"lesson":title,"position":number if number<3 else 1,"exercises":questions},allow_unicode=True)+"---\n\n"+body,encoding="utf-8")
        imported=app.import_course_markdown(path);files.append(imported)
    course_id=files[0]["course_id"]
    info={"synthetic":True,"course_id":course_id,"next_course_id":files[2]["course_id"],"plan_id":plan.id,
          "workspace":str(workspace),"lesson_file":str(workspace/'content/lesson-1.md'),"course":app.course_detail(course_id)}
    engine=StudyFlowEngine(service=app)
    lock=threading.Lock()
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
        def send_json(self,payload):
            raw=json.dumps(payload,ensure_ascii=False,default=str).encode("utf-8")
            self.send_response(200);self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.path=="/test/info": return self.send_json(info)
            if self.path=="/test/stop":
                self.send_json({"stopping":True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
            super().do_GET()
        def do_POST(self):
            if self.path!="/api/engine" or self.headers.get("X-StudyFlow-Client")!="studyflow-ui":
                self.send_error(403);return
            length=int(self.headers.get("Content-Length","0"))
            if length>5_000_000: self.send_error(413);return
            request=json.loads(self.rfile.read(length))
            with lock: response=engine.handle(request)
            self.send_json(response)
    server=ThreadingHTTPServer(("127.0.0.1",args.port),partial(Handler,directory=str(args.frontend.resolve())))
    info["url"]=f"http://127.0.0.1:{server.server_port}"
    (workspace.parent/'server-info.json').write_text(json.dumps(info,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({"url":info["url"],"synthetic":True,"workspace":str(workspace)},ensure_ascii=False),flush=True)
    try: server.serve_forever()
    finally: server.server_close();engine.close();database.dispose()


if __name__=="__main__": main()
