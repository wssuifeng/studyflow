"""Frozen CLI contract, arbitrary cwd, no source/Python dependency in the child."""
import argparse,json,os,subprocess,tempfile
from pathlib import Path
from hashlib import sha256
ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument("--cli",required=True);args=parser.parse_args()
    cli=Path(args.cli).resolve()
    results=ROOT/"test-results/implementation-20261003";results.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix="独立 CLI 合成工作区-",dir=results)).resolve()
    environment={k:v for k,v in os.environ.items() if k not in {"PYTHONPATH","VIRTUAL_ENV","STUDYFLOW_DATABASE_PATH","STUDYFLOW_DATABASE_URL","STUDYFLOW_WORKSPACE"}}
    environment["STUDYFLOW_WORKSPACE"]=str(root)
    environment["PATH"]=str(Path(os.environ.get("WINDIR","C:/Windows"))/"System32")
    commands=[]
    def run(*arguments,expect_ok=True):
        process=subprocess.run([str(cli),*arguments],cwd=str(root.parent),env=environment,capture_output=True,text=True,encoding="utf-8",timeout=60)
        data=json.loads(process.stdout)
        assert (process.returncode==0)==expect_ok,(process.returncode,process.stdout,process.stderr)
        assert data.get("ok")==expect_ok,data
        commands.append({"arguments":list(arguments[:3]),"ok":data.get("ok")})
        return data
    version=run("version","--format","json");assert version["app_version"]=="1.7.0"
    caps=run("capabilities","--format","json");assert any(i.get("method")=="course.update.apply" for i in caps["engine_capabilities"])
    run("doctor","--format","json")
    run("plan","create","--name","合成独立CLI计划","--format","json")
    package={"schema":"studyflow.course-package/1","package_id":"frozen-cli-synthetic","plan_line":"合成独立CLI计划","course":{"title":"合成独立CLI课程"},"lessons":[{"id":"unit","title":"知识点","blocks":[{"id":"concept","type":"concept","title":"理解概念","body":"合成资料，不是真实学习内容。"}],"exercises":[{"id":"question","title":"练习","prompt":"解释合成概念。"}]}]}
    file=root/"package.json";file.write_text(json.dumps(package,ensure_ascii=False),encoding="utf-8")
    run("course","validate-package","--file",str(file),"--format","json")
    imported=run("course","import-package","--file",str(file),"--format","json")
    def call(method,params=None,expect_ok=True):
        request=root/"request.json";request.write_text(json.dumps(params or {},ensure_ascii=False),encoding="utf-8")
        return run("call","--method",method,"--file",str(request),"--format","json",expect_ok=expect_ok)
    opened=call("course.study.open",{"course_id":imported["course_id"],"idempotency_key":"frozen-open"})
    exercise=opened["lessons"][0]["exercises"][0]["id"]
    submitted=call("course.answers.submit",{"course_id":imported["course_id"],"study_session_id":opened["study"]["id"],"answers":[{"exercise_id":exercise,"answer_text":"合成测试答案，非用户作答"}],"idempotency_key":"frozen-answer"})
    queue=call("assignment.summary",{"role":"agent","limit":20})
    assert len(queue["items"])==1 and "answer_text" not in queue["items"][0]
    sid=submitted["submissions"][0]["id"]
    context=call("assignment.context",{"submission_ids":[sid]});assert len(context["contexts"])==1
    call("review.write",{"submission_id":sid,"summary":"合成通过","decision":"PASSED","idempotency_key":"frozen-review"})
    assert call("assignment.summary",{"history":True})["items"][0]["status"]=="PASSED"
    run("workspace","export","--output",str(root.parent/(root.name+".zip")),"--format","json")
    call("assignment.summary",{"limit":1000},expect_ok=False)
    result={"ok":True,"source_env_removed":True,"system_path_only":True,"arbitrary_cwd":True,"unicode_workspace":True,"cli_sha256":sha256(cli.read_bytes()).hexdigest(),"commands":commands}
    (results/"installed-cli-result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False))
if __name__=="__main__":main()
