"""Existing installation read discovery plus fresh bundled resource parity; isolated data."""
from pathlib import Path
import json,os,subprocess,re,hashlib,tempfile
ROOT=Path(__file__).resolve().parents[3]
results=ROOT/'apps/desktop/test-results';work=Path(tempfile.mkdtemp(prefix='agent-discovery-',dir=results));request=work/'request.json';request.write_text('{}',encoding='utf-8')
runtime_temp=work/'runtime-temp';runtime_temp.mkdir()
rows=[]
for cli in [Path(os.environ.get('STUDYFLOW_TEST_INSTALLED_CLI','D:/ruanjian/StudyFlow/binaries/studyflow.exe')),ROOT/'apps/desktop/src-tauri/binaries/studyflow.exe']:
 env={k:v for k,v in os.environ.items() if k not in {'PYTHONPATH','VIRTUAL_ENV','STUDYFLOW_DATABASE_PATH','STUDYFLOW_DATABASE_URL','STUDYFLOW_WORKSPACE'}};env.update(STUDYFLOW_WORKSPACE=str(work),TEMP=str(runtime_temp),TMP=str(runtime_temp))
 process=subprocess.run([str(cli),'call','--method','system.installation','--file',str(request),'--format','json'],env=env,cwd=work,capture_output=True,text=True,encoding='utf-8',timeout=30);assert process.returncode==0,(process.stdout,process.stderr)
 data=json.loads(process.stdout);assert data['ok'];info=data.get('data',data)
 assert Path(info['cli_path']).is_file(),info
 legacy_discovery='skill_path' not in info
 if legacy_discovery:
  # An older installation does not advertise Skill readiness; inspect its known bundled sibling, not a guessed workspace.
  info['skill_path']=str(cli.parent/'studyflow-agent/SKILL.md')
 assert Path(info['skill_path']).is_file(),info
 assert Path(info['workspace']).resolve()==work.resolve()
 skill=Path(info['skill_path']);version=re.search(r'version:\s*"([^"]+)"',skill.read_text(encoding='utf-8-sig')).group(1)
 rows.append({'cli':str(cli),'exit':0,'paths_verified':True,'workspace':str(work),'skill_version':version,'legacy_discovery_without_ready_flags':legacy_discovery,'info':info})
source=ROOT/'skills/studyflow-agent';bundled=ROOT/'apps/desktop/src-tauri/binaries/studyflow-agent';mismatch=[]
for file in source.rglob('*'):
 if not file.is_file():continue
 target=bundled/file.relative_to(source)
 if not target.is_file() or hashlib.sha256(file.read_bytes()).digest()!=hashlib.sha256(target.read_bytes()).digest():mismatch.append(str(file.relative_to(source)))
assert not mismatch,mismatch
# Public is read only; do not overwrite it during acceptance.
public=Path.home()/'.agents/skills/studyflow-agent/SKILL.md'
result={'discovery':rows,'bundled_skill_hash_match':True,'public_skill_version':re.search(r'version:\s*"([^"]+)"',public.read_text(encoding='utf-8-sig')).group(1)}
(results/'acceptance-agent-discovery.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'installed_cli_paths':'verified','candidate_cli_paths':'verified','candidate_skill_matches_source':True,'skill_versions':[r['skill_version'] for r in rows],'public_version':result['public_skill_version']},ensure_ascii=False))
