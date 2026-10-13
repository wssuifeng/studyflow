"""Bounded public dictionary lookup; never accepts a user answer or arbitrary URL."""
import json
import threading
from time import monotonic
from urllib.request import Request,urlopen
from urllib.parse import quote,urlencode

class DictionaryProvider:
    def __init__(self,fetch=None):
        self.fetch=fetch or self._fetch
        self.cache={};self.lock=threading.Lock()
    def _fetch(self,url):
        with urlopen(Request(url,headers={"User-Agent":"StudyFlow-local/1.7"}),timeout=4) as response:
            data=response.read(256*1024+1)
            if len(data)>256*1024:raise ValueError("dictionary response too large")
            return json.loads(data)
    def lookup(self,target,accent,word=None):
        # The legacy dictionary voice convention is the same one used by the reference app.
        voice="https://dict.youdao.com/dictvoice?"+urlencode({"type":2 if accent=="en-US" else 1,"audio":target})
        result={"target":target,"pronunciation_url":voice,"pronunciation_provider":"youdao-dictionary","requested_accent":accent,"accent_verified":False,"phonetic":"","definitions":[],"definition_provider":"dictionaryapi.dev","definition_available":False,"from_cache":False}
        if not word:return result
        normalized=word.casefold()
        with self.lock:cached=self.cache.get(normalized)
        if cached and monotonic()-cached[0]<3600:
            return {**result,**cached[1],"from_cache":True}
        try:
            payload=self.fetch("https://api.dictionaryapi.dev/api/v2/entries/en/"+quote(normalized,safe=""))
            entry=payload[0] if isinstance(payload,list) and payload and isinstance(payload[0],dict) else {}
            phonetic=entry.get("phonetic","")
            if not phonetic:phonetic=next((p.get("text","") for p in entry.get("phonetics",[]) if isinstance(p,dict) and p.get("text")),"")
            definitions=[{"part_of_speech":str(m.get("partOfSpeech",""))[:80],"definition":str(d.get("definition",""))[:2000]} for m in entry.get("meanings",[]) if isinstance(m,dict) for d in m.get("definitions",[]) if isinstance(d,dict)][:8]
            info={"phonetic":str(phonetic)[:200],"definitions":definitions,"definition_available":bool(definitions or phonetic)}
            with self.lock:
                if len(self.cache)>=256:self.cache.pop(next(iter(self.cache)))
                self.cache[normalized]=(monotonic(),info)
            return {**result,**info}
        except (OSError,ValueError,TypeError,KeyError):
            if cached:return {**result,**cached[1],"from_cache":True,"notice":"网络词典不可用，使用本次运行已缓存的辅助信息。"}
            return {**result,"notice":"释义/音标暂不可用；发音可独立尝试，失败不阻塞学习。"}
