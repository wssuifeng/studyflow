"""Course cleanup extension, used only by the explicitly confirmed purge use case."""
from sqlalchemy import select,delete,func
from studyflow.modules.courses.models import Exercise,Lesson
from studyflow.modules.courses.english.models import EnglishItem
from studyflow.modules.learning.models import Submission,CourseStudySession,CourseReferenceView
from studyflow.modules.learning.english.models import EnglishCheckAttempt,EnglishSubmissionDetail,EnglishStudyState
from studyflow.modules.mistakes.english.models import EnglishErrorAggregate,EnglishErrorEvidence,EnglishReviewItem
from studyflow.modules.mistakes.general.models import GeneralMistakeEntry,GeneralMistakeOccurrence


def owned_queries(course_ids):
    from studyflow.modules.mistakes.remediation.models import EnglishRemediationSource,EnglishRemediationCourse
    exercises=select(Exercise.id).join(Lesson).where(Lesson.course_id.in_(course_ids))
    sessions=select(CourseStudySession.id).where(CourseStudySession.course_id.in_(course_ids))
    submissions=select(Submission.id).where(Submission.exercise_id.in_(exercises))
    aggregates=select(EnglishErrorAggregate.id).where(EnglishErrorAggregate.course_id.in_(course_ids))
    general=select(GeneralMistakeEntry.id).where(GeneralMistakeEntry.course_id.in_(course_ids))
    return [(CourseReferenceView,CourseReferenceView.study_session_id.in_(sessions)),(EnglishRemediationSource,EnglishRemediationSource.course_id.in_(course_ids)),(EnglishRemediationCourse,EnglishRemediationCourse.course_id.in_(course_ids)),(EnglishReviewItem,EnglishReviewItem.aggregate_id.in_(aggregates)),(EnglishErrorEvidence,EnglishErrorEvidence.aggregate_id.in_(aggregates)),(EnglishErrorAggregate,EnglishErrorAggregate.course_id.in_(course_ids)),(GeneralMistakeOccurrence,GeneralMistakeOccurrence.entry_id.in_(general)),(GeneralMistakeEntry,GeneralMistakeEntry.course_id.in_(course_ids)),(EnglishSubmissionDetail,EnglishSubmissionDetail.submission_id.in_(submissions)),(EnglishCheckAttempt,EnglishCheckAttempt.study_session_id.in_(sessions)),(EnglishStudyState,EnglishStudyState.study_session_id.in_(sessions)),(EnglishItem,EnglishItem.exercise_id.in_(exercises))]


def inventory(db,course_ids):
    return {model.__tablename__:db.scalar(select(func.count()).select_from(model).where(predicate)) for model,predicate in owned_queries(course_ids)}


def purge(db,course_ids):
    from studyflow.modules.mistakes.remediation.models import EnglishRemediationSource
    from studyflow.shared.domain import DomainError
    dependent=db.scalar(select(EnglishRemediationSource.course_id).join(EnglishErrorAggregate,EnglishErrorAggregate.id==EnglishRemediationSource.aggregate_id).where(EnglishErrorAggregate.course_id.in_(course_ids),EnglishRemediationSource.course_id.notin_(course_ids)).limit(1))
    if dependent:raise DomainError("COURSE_HAS_REMEDIATION_DEPENDENCIES","还有补充课程引用这些错误来源；请保留来源或明确一起清理关联课程。")
    for model,predicate in owned_queries(course_ids):db.execute(delete(model).where(predicate).execution_options(synchronize_session=False))
