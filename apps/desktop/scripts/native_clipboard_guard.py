"""Preserve clipboard formats in memory during synthetic native keyboard tests."""
import asyncio,base64,subprocess,json,time
from pathlib import Path

class ClipboardGuard:
    def __init__(self,workspace):self.workspace=workspace;self.process=None
    async def __aenter__(self):
        ps=r'''
Add-Type -AssemblyName System.Windows.Forms
$snapshot=New-Object System.Windows.Forms.DataObject
$existing=[System.Windows.Forms.Clipboard]::GetDataObject()
if($null -ne $existing){foreach($format in $existing.GetFormats($false)){$snapshot.SetData($format,$false,$existing.GetData($format,$false))}}
[IO.File]::WriteAllText($env:STUDYFLOW_CLIP_READY,'ready')
try{while(-not [IO.File]::Exists($env:STUDYFLOW_CLIP_DONE)){Start-Sleep -Milliseconds 100}}
finally{[System.Windows.Forms.Clipboard]::SetDataObject($snapshot,$true)}
'''
        import os
        ready=self.workspace/'clipboard-ready';self.done=self.workspace/'clipboard-done'
        env=dict(os.environ,STUDYFLOW_CLIP_READY=str(ready),STUDYFLOW_CLIP_DONE=str(self.done))
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        self.process=subprocess.Popen(['powershell.exe','-NoProfile','-STA','-EncodedCommand',base64.b64encode(ps.encode('utf-16-le')).decode()],env=env,startupinfo=startup,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        deadline=time.monotonic()+8
        while not ready.exists():
            if self.process.poll() is not None:raise RuntimeError('Clipboard guard could not snapshot all formats; no test clipboard change executed')
            if time.monotonic()>deadline:raise RuntimeError('Clipboard guard not ready')
            await asyncio.sleep(.05)
        return self
    async def __aexit__(self,*args):
        self.done.write_text('restore',encoding='ascii')
        stdout,stderr=await asyncio.to_thread(self.process.communicate,timeout=8)
        if self.process.returncode!=0:raise RuntimeError('System clipboard restoration failed')
