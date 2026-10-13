"""Transaction boundary for English use cases and their error projections."""
import json
from sqlalchemy import select
from studyflow.infrastructure.runtime import Service
from studyflow.modules.learning.models import CourseWriteReceipt
from studyflow.modules.learning.english import service as operations
from studyflow.shared.domain import DomainError
from studyflow.shared.ids import new_id
from studyflow.modules.learning.write_contract import digest


class EnglishApplication(Service):
    def get(self,study_session_id):
        from studyflow.infrastructure.installation import workspace_key
        with self.session(read_only=True) as db:
            result=operations.get_view(db,study_session_id)
            result["workspace_key"]=workspace_key(self.settings.workspace_root)
            return result

    def _write(self,operation,study_id,key,payload,action):
        if not isinstance(key,str) or not 1<=len(key)<=160:raise DomainError("INVALID_ARGUMENT","幂等键必须为1—160字符。")
        request={"study_session_id":study_id,**payload};request_hash=digest(request)
        with self.session() as db:
            receipt=db.scalar(select(CourseWriteReceipt).where(CourseWriteReceipt.idempotency_key==key))
            if receipt:
                if receipt.operation!=operation or receipt.payload_hash!=request_hash:raise DomainError("IDEMPOTENCY_KEY_CONFLICT","幂等键已用于其他请求。")
                return json.loads(receipt.result_json)
            study,_,_=operations.context(db,study_id)
            result=action(db)
            db.add(CourseWriteReceipt(id=new_id(),course_id=study.course_id,study_session_id=study_id,idempotency_key=key,operation=operation,payload_hash=request_hash,result_json=json.dumps(result,ensure_ascii=False)))
            self._event(db,"USER_ENGINE","english_study",study_id,operation,"英语训练状态更新；无答卷正文。")
            return result

    def save(self,study_session_id,exercise_id,answer_text,expected_version,idempotency_key,skipped=False):
        return self._write("EN_SAVE",study_session_id,idempotency_key,{"exercise_id":exercise_id,"answer_text":answer_text,"expected_version":expected_version,"skipped":skipped},lambda db:operations.save(db,study_session_id,exercise_id,answer_text,expected_version,skipped))

    def check(self,study_session_id,exercise_id,expected_version,idempotency_key):
        def execute(db):
            result,context=operations.check(db,study_session_id,exercise_id,expected_version)
            from studyflow.modules.mistakes.english.projection import record_check
            record_check(db,*context)
            return result
        return self._write("EN_CHECK",study_session_id,idempotency_key,{"exercise_id":exercise_id,"expected_version":expected_version},execute)

    def reveal(self,study_session_id,exercise_id,idempotency_key):
        return self._write("EN_REVEAL",study_session_id,idempotency_key,{"exercise_id":exercise_id},lambda db:operations.reveal(db,study_session_id,exercise_id))

    def answer(self,study_session_id,exercise_id):
        with self.session(read_only=True) as db:return operations.answer_view(db,study_session_id,exercise_id)

    def submit(self,study_session_id,idempotency_key,expected_versions=None):
        return self._write("EN_SUBMIT",study_session_id,idempotency_key,{"expected_versions":expected_versions},lambda db:operations.submit(db,study_session_id,expected_versions))

    def request_review(self,study_session_id,exercise_id,expected_version,idempotency_key):
        return self._write("EN_REVIEW",study_session_id,idempotency_key,{"exercise_id":exercise_id,"expected_version":expected_version},lambda db:operations.request_review(db,study_session_id,exercise_id,expected_version))

    def navigate(self,study_session_id,position,expected_version,idempotency_key):
        return self._write("EN_MOVE",study_session_id,idempotency_key,{"position":position,"expected_version":expected_version},lambda db:operations.navigate(db,study_session_id,position,expected_version))

    def retest_get(self,task_id):
        with self.session(read_only=True) as db:return operations.retest_get(db,task_id)

    def retest_save(self,task_id,answer_text,expected_version,idempotency_key):
        with self.session(read_only=True) as db:
            view=operations.retest_get(db,task_id)
        return self._write("EN_RETEST_SAVE",view["study_session_id"],idempotency_key,{"task_id":task_id,"answer_text":answer_text,"expected_version":expected_version},lambda db:operations.retest_save(db,task_id,answer_text,expected_version))

    def retest_check(self,task_id,answer_text,idempotency_key,expected_version=None):
        with self.session(read_only=True) as db:
            view=operations.retest_get(db,task_id)
        return self._write("EN_RETEST",view["study_session_id"],idempotency_key,{"task_id":task_id,"answer_text":answer_text,"expected_version":expected_version},lambda db:operations.retest_check(db,task_id,answer_text,expected_version))
