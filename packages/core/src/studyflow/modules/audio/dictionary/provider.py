"""Immediate voice resolution with bounded, background dictionary metadata."""
import json
import threading
from queue import Empty, Queue
from time import monotonic
from urllib.request import Request, urlopen
from urllib.parse import quote, urlencode


class DictionaryProvider:
    MAX_PENDING = 16
    MAX_CACHE = 256

    def __init__(self, fetch=None):
        self.fetch = fetch or self._fetch
        self.cache = {}
        self.lock = threading.Lock()
        self._pending = set()
        self._queue = Queue(maxsize=self.MAX_PENDING)
        self._workers = []
        self._closed = False

    def _fetch(self, url):
        with urlopen(Request(url, headers={"User-Agent": "StudyFlow-local/1.8"}), timeout=4) as response:
            data = response.read(256 * 1024 + 1)
            if len(data) > 256 * 1024:
                raise ValueError("dictionary response too large")
            return json.loads(data)

    def _resolve(self, word):
        try:
            payload = self.fetch("https://api.dictionaryapi.dev/api/v2/entries/en/" + quote(word, safe=""))
            entry = payload[0] if isinstance(payload, list) and payload and isinstance(payload[0], dict) else {}
            phonetic = entry.get("phonetic", "")
            if not phonetic:
                phonetic = next((p.get("text", "") for p in entry.get("phonetics", []) if isinstance(p, dict) and p.get("text")), "")
            definitions = [{"part_of_speech": str(m.get("partOfSpeech", ""))[:80], "definition": str(d.get("definition", ""))[:2000]}
                           for m in entry.get("meanings", []) if isinstance(m, dict)
                           for d in m.get("definitions", []) if isinstance(d, dict)][:8]
            available = bool(definitions or phonetic)
            info = {"phonetic": str(phonetic)[:200], "definitions": definitions,
                    "definition_available": available, "metadata_status": "ready" if available else "unavailable"}
            ttl = 3600 if available else 30
            if not available:
                info["notice"] = "词典辅助信息暂不可用；发音和文字训练可继续。"
        except (OSError, ValueError, TypeError, KeyError):
            info = {"phonetic": "", "definitions": [], "definition_available": False,
                    "metadata_status": "unavailable", "notice": "释义/音标暂不可用；发音可独立尝试，失败不阻塞学习。"}
            ttl = 30
        with self.lock:
            if self._closed:
                return
            old = self.cache.get(word)
            if not info["definition_available"] and old and old[1].get("definition_available"):
                info = {**old[1], "metadata_status": "unavailable",
                        "notice": "网络词典不可用，使用本次运行已缓存的辅助信息。"}
            if len(self.cache) >= self.MAX_CACHE and word not in self.cache:
                self.cache.pop(next(iter(self.cache)))
            self.cache[word] = (monotonic() + ttl, info)

    def _work(self):
        while True:
            word = self._queue.get()
            try:
                if word is None:
                    return
                with self.lock:
                    active = not self._closed
                if active:
                    self._resolve(word)
            finally:
                if word is not None:
                    with self.lock:
                        self._pending.discard(word)
                self._queue.task_done()

    def lookup(self, target, accent, word=None):
        voice = "https://dict.youdao.com/dictvoice?" + urlencode({"type": 2 if accent == "en-US" else 1, "audio": target})
        result = {"target": target, "pronunciation_url": voice, "pronunciation_provider": "youdao-dictionary",
                  "requested_accent": accent, "accent_verified": False, "phonetic": "", "definitions": [],
                  "definition_provider": "dictionaryapi.dev", "definition_available": False,
                  "from_cache": False, "metadata_status": "not_requested"}
        if not word:
            return result
        normalized = word.casefold()
        with self.lock:
            cached = self.cache.get(normalized)
            if cached and monotonic() < cached[0]:
                return {**result, **cached[1], "from_cache": True}
            if self._closed:
                return {**result, "metadata_status": "unavailable", "notice": "辅助查询已停止；文字训练仍可继续。"}
            if normalized not in self._pending and len(self._pending) < self.MAX_PENDING:
                if not self._workers:
                    for index in range(2):
                        worker = threading.Thread(target=self._work, name=f"studyflow-dictionary-{index}", daemon=True)
                        self._workers.append(worker)
                        worker.start()
                self._pending.add(normalized)
                self._queue.put_nowait(normalized)
            queued = normalized in self._pending
        # Never wait for DNS, TLS or an HTTP timeout on the serialized Engine lane.
        return {**result, **(cached[1] if cached else {}), "from_cache": bool(cached),
                "metadata_status": "loading" if queued else "deferred",
                "notice": "释义/音标后台读取中，发音与答题可继续。" if queued else "辅助查询已排满，本项仍可发音和作答。"}

    def close(self):
        with self.lock:
            self._closed = True
            workers = len(self._workers)
        while True:
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except Empty:
                break
        for _ in range(workers):
            self._queue.put_nowait(None)
        # Daemon workers never turn an immediate CLI reply into a DNS/HTTP exit wait.
        # A late network response cannot update the closed provider or the database.
