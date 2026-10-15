from studyflow.infrastructure.runtime import Service
from studyflow.modules.audio.dictionary.provider import DictionaryProvider
from studyflow.modules.learning.english.service import context, latest
from studyflow.modules.learning.english.checker import tokenize, check_answer
from studyflow.shared.domain import DomainError

class AudioService(Service):
    def __init__(self,runtime,provider=None):
        super().__init__(runtime);self.provider=provider or DictionaryProvider()
    def lookup(self,study_session_id,exercise_id,word_index=None,accent="en-US"):
        if accent not in {"en-US","en-GB"}:raise DomainError("INVALID_ARGUMENT","未支持的请求口音。")
        with self.session(read_only=True) as db:
            _,_,item=context(db,study_session_id,exercise_id)
            reference=item["english"]
            answer=latest(db,study_session_id,exercise_id)
            accepted=check_answer(reference,answer.answer_text).get("matched_variant") if answer else None
        target=accepted or reference["target"];tokens=tokenize(target)
        if word_index is not None:
            if isinstance(word_index,bool) or not isinstance(word_index,int) or not 0<=word_index<len(tokens):raise DomainError("INVALID_ARGUMENT","词位越界。")
            target=tokens[word_index]
        # Provider network I/O occurs only after the database read transaction is closed.
        result=self.provider.lookup(target,accent,target if len(tokenize(target))==1 else None)
        note={}
        if word_index is not None:
            for part in reference.get("sentence_parts",[]) if not accepted or accepted==reference["target"] else []:
                if part["start"]<=word_index<part["end"]:note=part["words"][word_index-part["start"]];break
        if not result["phonetic"]:result["phonetic"]=note.get("phonetic","") if word_index is not None and len(tokens)>1 else reference.get("phonetic","")
        result["course_gloss"]=note.get("gloss","") if word_index is not None else reference.get("gloss","")
        result["whole_sentence"]=word_index is None and len(tokens)>1
        return result

    def metadata(self,study_session_id,exercise_id,accent="en-US"):
        """Current frozen item only; enqueue metadata without playing or waiting on HTTP."""
        if accent not in {"en-US","en-GB"}:raise DomainError("INVALID_ARGUMENT","未支持的请求口音。")
        with self.session(read_only=True) as db:
            _,_,item=context(db,study_session_id,exercise_id)
            reference=item["english"]
            answer=latest(db,study_session_id,exercise_id)
            accepted=check_answer(reference,answer.answer_text).get("matched_variant") if answer else None
        target=accepted or reference["target"]
        words=[]
        for index,word in enumerate(tokenize(target)):
            result=self.provider.lookup(word,accent,word)
            words.append({"word_index":index,"word":word,**{key:result.get(key) for key in ["phonetic","definitions","metadata_status","definition_provider","accent_verified"]}})
        return {"target":target,"words":words,"requested_accent":accent,"sentence_transcription":False}
