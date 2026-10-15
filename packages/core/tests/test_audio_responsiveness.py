"""Dictionary network work cannot delay the serialized desktop Engine."""
from threading import Event
from time import monotonic
from studyflow.modules.audio.dictionary.provider import DictionaryProvider


def test_slow_dictionary_returns_voice_without_waiting_for_network():
    release = Event()
    entered = Event()

    def slow_fetch(url):
        entered.set()
        release.wait(1)
        return [{"phonetic": "/fɪltə/", "meanings": []}]

    provider = DictionaryProvider(fetch=slow_fetch)
    try:
        started = monotonic()
        result = provider.lookup("filter", "en-US", "filter")
        elapsed = monotonic() - started
        assert elapsed < 0.15, f"dictionary blocked the Engine for {elapsed:.3f}s"
        assert result["pronunciation_url"].startswith("https://dict.youdao.com/")
        assert entered.wait(0.3)
    finally:
        release.set()
        if hasattr(provider, "close"):
            provider.close()


def test_pending_metadata_is_deduplicated_and_queue_is_bounded():
    release = Event()
    calls = []

    def slow_fetch(url):
        calls.append(url)
        release.wait(1)
        raise OSError("offline")

    provider = DictionaryProvider(fetch=slow_fetch)
    try:
        for _ in range(10):
            assert provider.lookup("filter", "en-US", "filter")["metadata_status"] == "loading"
        for index in range(40):
            provider.lookup(f"word{index}", "en-GB", f"word{index}")
        assert len(provider._pending) <= provider.MAX_PENDING
        assert sum("/filter" in call for call in calls) <= 1
        assert len(calls) <= 2
    finally:
        provider.close()
        release.set()


def test_offline_metadata_is_negatively_cached_without_retrying_each_keystroke():
    finished = Event()
    calls = []

    def offline(url):
        calls.append(url)
        finished.set()
        raise OSError("offline")

    provider = DictionaryProvider(fetch=offline)
    try:
        provider.lookup("filter", "en-US", "filter")
        assert finished.wait(.3)
        deadline = monotonic() + .5
        while provider.lookup("filter", "en-US", "filter")["metadata_status"] == "loading" and monotonic() < deadline:
            Event().wait(.005)
        for _ in range(20):
            info = provider.lookup("filter", "en-US", "filter")
            assert info["metadata_status"] == "unavailable"
            assert info["from_cache"]
        assert len(calls) == 1
    finally:
        provider.close()


def test_worker_lifecycle_cannot_hold_one_shot_cli_exit():
    release = Event()
    entered = Event()
    def slow_fetch(url):
        entered.set()
        release.wait(1)
        return []
    provider = DictionaryProvider(fetch=slow_fetch)
    try:
        provider.lookup("filter", "en-US", "filter")
        assert entered.wait(.3)
        assert provider._workers and all(worker.daemon for worker in provider._workers)
        started = monotonic()
        provider.close()
        assert monotonic() - started < .1
        assert provider.lookup("other", "en-US", "other")["metadata_status"] == "unavailable"
    finally:
        release.set()


def test_one_shot_process_exits_while_dictionary_network_is_still_waiting():
    import subprocess
    import sys
    child = """
from threading import Event
from studyflow.modules.audio.dictionary.provider import DictionaryProvider
entered=Event()
def slow(url):
    entered.set()
    Event().wait(60)
    return []
p=DictionaryProvider(fetch=slow)
result=p.lookup('filter','en-US','filter')
assert entered.wait(.5)
p.close()
print(result['metadata_status'],flush=True)
"""
    result = subprocess.run([sys.executable, '-B', '-c', child], capture_output=True, text=True, timeout=2)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'loading'


def test_word_metadata_batch_is_bounded_nonblocking_and_keeps_course_phonetics(app_service,tmp_path):
    from test_english_specialty import install
    _,opened=install(app_service,tmp_path)
    sid=opened["study"]["id"];item=app_service.english.get(sid)["items"][0]
    provider=DictionaryProvider(fetch=lambda url:[{"phonetic":"/test/","meanings":[]}])
    app_service.audio.provider=provider
    try:
        start=monotonic()
        result=app_service.audio.metadata(sid,item["exercise_id"])
        assert monotonic()-start<.2
        assert result["target"]=="I like tea."
        assert [w["word_index"] for w in result["words"]]==[0,1,2]
        assert result["words"][0]["accent_verified"] is False
        assert result["sentence_transcription"] is False
    finally:provider.close()
