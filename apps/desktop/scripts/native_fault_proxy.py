"""Private protocol fault proxy around the real frozen Engine; not product code."""
from pathlib import Path
import os,subprocess

def build_proxy(workspace,engine):
    source=workspace/'engine-fault-proxy.cs';binary=workspace/'engine-fault-proxy.exe'
    source.write_text(r'''
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Web.Script.Serialization;
class Proxy {
 static int Main() {
  Console.InputEncoding=new System.Text.UTF8Encoding(false);Console.OutputEncoding=new System.Text.UTF8Encoding(false);
  var json=new JavaScriptSerializer();json.MaxJsonLength=16000000;
  var real=new Process();real.StartInfo=new ProcessStartInfo(Environment.GetEnvironmentVariable("STUDYFLOW_REAL_ENGINE"));
  real.StartInfo.UseShellExecute=false;real.StartInfo.CreateNoWindow=true;
  real.StartInfo.RedirectStandardInput=true;real.StartInfo.RedirectStandardOutput=true;
  real.StartInfo.RedirectStandardError=true;real.StartInfo.StandardOutputEncoding=System.Text.Encoding.UTF8;
  real.StartInfo.StandardErrorEncoding=System.Text.Encoding.UTF8;
  real.ErrorDataReceived+=(s,e)=>{if(e.Data!=null)Console.Error.WriteLine(e.Data);};
  real.Start();real.BeginErrorReadLine();
  var writer=new StreamWriter(real.StandardInput.BaseStream,new System.Text.UTF8Encoding(false));
  try {string line;while((line=Console.ReadLine())!=null) {
   var request=json.Deserialize<Dictionary<string,object>>(line);
   if(File.Exists(Environment.GetEnvironmentVariable("STUDYFLOW_FAULT_FILE")) && (string)request["method"]=="plan.notebook.apply") {
    Console.WriteLine(json.Serialize(new {id=request["id"],ok=false,error=new {code="DATABASE_READ_ONLY",message="隔离原生验收：模拟保存失败",next_action="重试原请求或不保存离开"}}));
   } else {writer.WriteLine(line);writer.Flush();Console.WriteLine(real.StandardOutput.ReadLine());}
   Console.Out.Flush();
  }} finally {writer.Close();if(!real.WaitForExit(3000))real.Kill();}
  return 0;
 }
}
''',encoding='utf-8-sig')
    compiler=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    result=subprocess.run([str(compiler),'/nologo','/target:exe','/reference:System.Web.Extensions.dll','/out:'+str(binary),str(source)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=30)
    if result.returncode or not binary.is_file():raise RuntimeError('Native test proxy build failed: '+result.stdout+result.stderr)
    return binary
