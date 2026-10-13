from studyflow.infrastructure.runtime import Service
from studyflow.modules.audio.dictionary.provider import DictionaryProvider
from studyflow.modules.learning.english.service import answer_view
from studyflow.modules.learning.english.checker import tokenize
from studyflow.shared.domain import DomainError

class AudioService(Service):
    def __init__(self,runtime,provider=None):
        super().__init__(runtime);self.provider=provider or DictionaryProvider()
    def lookup(self,study_session_id,exercise_id,word_index=None,accent="en-US"):
        if accent not in {"en-US","en-GB"}:raise DomainError("INVALID_ARGUMENT","未支持的请求口音。")
        with self.session(read_only=True) as db:reference=answer_view(db,study_session_id,exercise_id)
        target=reference["target"];tokens=tokenize(target)
        if word_index is not None:
            if isinstance(word_index,bool) or not isinstance(word_index,int) or not 0<=word_index<len(tokens):raise DomainError("INVALID_ARGUMENT","词位越界。")
            target=tokens[word_index]
        # Provider network I/O occurs only after the database read transaction is closed.
        result=self.provider.lookup(target,accent,target if len(tokenize(target))==1 else None)
        if not result["phonetic"]:result["phonetic"]=reference.get("phonetic","")
        result["course_gloss"]=reference.get("gloss","")
        result["whole_sentence"]=word_index is None and len(tokens)>1
        return result
