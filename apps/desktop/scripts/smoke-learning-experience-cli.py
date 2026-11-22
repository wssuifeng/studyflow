"""Agent-neutral public CLI receipts against a synthetic /3 course only."""
import argparse
import json
from pathlib import Path

from rust_smoke_support import NativeCli

ROOT = Path(__file__).resolve().parents[3]


def main(desktop, workspace, evidence):
    cli = NativeCli(desktop, workspace, evidence, record_receipts=True)
    call = cli.command
    method = cli.call
    RESULTS = evidence
    call('version');cap=call('capabilities');assert 'studyflow.course-package/3' in cap['content']['course_package_schemas'];assert 'details' not in cap['content']['schema_block_types']['studyflow.course-package/1']
    call('doctor');call('db-upgrade');installation=method('system.installation');assert installation['agent_workspace_entry_status'] in {'found','missing','invalid'}
    if installation['agent_workspace_entry_status']=='found':assert Path(installation['agent_workspace_entry_path']).is_file()
    else:assert installation['agent_workspace_entry_path'] is None
    method('system.schema',{'method':'course.study.restart'})
    call('plan','create','--name','合成计划')
    source=ROOT/'skills/studyflow-agent/examples/course-package-details.json'
    call('course','validate-package','--file',str(source));course=call('course','import-package','--file',str(source));cid=course['course_id']
    old=method('course.study.open',{'course_id':cid,'idempotency_key':'cli-old'});sid=old['study']['id'];lid=old['lessons'][0]['id']
    method('course.notes.save',{'study_session_id':sid,'lesson_id':lid,'text':'保留历史笔记','expected_version':0,'idempotency_key':'cli-note'})
    updated=json.loads(source.read_text(encoding='utf-8'));updated['package_id']='synthetic-details-revision';updated['lessons'][0]['blocks'][1]['body']+='\n\nCLI 新版补充解释。'
    revision=workspace/'revision.json';revision.write_text(json.dumps(updated,ensure_ascii=False),encoding='utf-8')
    preview=method('course.update.preview',{'course_id':cid,'path':str(revision),'expected_revision':1})
    receipt=method('course.update.apply',{'course_id':cid,'path':str(revision),'expected_revision':1,'preview_hash':preview['preview_hash'],'idempotency_key':'cli-revision'})
    assert receipt['learning_state_reset'] and sid in receipt['reset_study_sessions']
    sealed=method('course.study.get',{'study_session_id':sid});assert sealed['study']['source_changed'] and not sealed['study']['is_current']
    assert sealed['course']['study_status']=='ABANDONED' and 'CLI 新版' not in sealed['lessons'][0]['content_blocks'][1]['body']
    fresh=method('course.study.open',{'course_id':cid,'idempotency_key':'cli-after-revision'});assert fresh['study']['id']!=sid
    assert 'CLI 新版' in fresh['lessons'][0]['content_blocks'][1]['body']
    assert method('course.study.open',{'course_id':cid,'idempotency_key':'cli-after-revision'})['study']['id']==fresh['study']['id']
    assert method('course.notes.get',{'study_session_id':sid})['notes'][0]['text']=='保留历史笔记'
    (RESULTS/'result.json').write_text(json.dumps({'checks':len(cli.receipts),'receipts':cli.receipts,'business_acceptance':'not_evaluated'},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'ok':True,'checks':len(cli.receipts),'workspace':str(workspace)},ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    args.workspace.mkdir(parents=True, exist_ok=False)
    args.evidence.mkdir(parents=True, exist_ok=True)
    main(args.desktop.resolve(strict=True), args.workspace.resolve(), args.evidence.resolve())
