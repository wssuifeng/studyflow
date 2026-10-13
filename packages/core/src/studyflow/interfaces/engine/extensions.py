"""New transport routes: delegate to domain owners, never implement business here."""
from studyflow.shared.domain import DomainError

METHODS={"plan.notebook.read":"read","plan.notebook.apply":"write","course.study.restart.preview":"read","course.study.restart":"write","assignment.summary":"read","assignment.context":"read","review.retest.publish":"write","submission.resolve-branch":"write","system.changes":"read","system.schema":"read","course.update.preview":"read","course.update.apply":"write","workspace.export":"write","workspace.validate":"read","workspace.restore":"write","system.installation":"read","plan.edit":"write","plan.schedule.list":"read","plan.notebook.search":"read","plan.notebook.export":"read","course.source.read":"read"}

METHODS.update({"exercise.reference.read":"read","exercise.reference.view":"write","learning.evidence":"read"})

from .english import METHODS as ENGLISH_METHODS
METHODS.update(ENGLISH_METHODS)
from .remediation import METHODS as REMEDIATION_METHODS
METHODS.update(REMEDIATION_METHODS)

def dispatch(engine,method,params):
    if method in REMEDIATION_METHODS:
        from .remediation import dispatch as remediation_dispatch
        return remediation_dispatch(engine,method,params)
    if method in ENGLISH_METHODS:
        from .english import dispatch as english_dispatch
        return english_dispatch(engine,method,params)
    service=engine.service
    if method in {"exercise.reference.read","exercise.reference.view"}:
        from studyflow.modules.courses.references.service import read_reference,view_reference
        return (read_reference if method.endswith("read") else view_reference)(service.learning,**params)
    if method=="learning.evidence":
        from studyflow.modules.learning.evidence import read_evidence
        return read_evidence(service.learning,**params)
    if method=="plan.notebook.read": return service.read_plan_notebook(**params)
    if method=="plan.notebook.apply": return service.apply_plan_notebook(**params)
    if method=="plan.edit":
        from studyflow.modules.planning.management import edit_plan
        return edit_plan(service.planning,**params)
    if method=="plan.schedule.list":
        from studyflow.modules.planning.management import list_schedule
        return list_schedule(service.planning,**params)
    if method in {"plan.notebook.search","plan.notebook.export","course.source.read"}:
        from studyflow.modules.learning.notebook_queries import search, export, source
        return {"plan.notebook.search":search,"plan.notebook.export":export,"course.source.read":source}[method](service.learning,**params)
    if method in {"course.study.restart.preview","course.study.restart"}:
        from studyflow.modules.learning.restart import preview, restart
        from .protocol import PROTOCOL_VERSION
        return {"protocol_version":PROTOCOL_VERSION,**(preview if method.endswith("preview") else restart)(service.learning,**params)}
    if method=="system.installation":
        from studyflow.infrastructure.installation import installation_info
        return installation_info(service.settings)
    if method=="workspace.export":
        from studyflow.modules.workspace.repository import export_workspace
        return {"ok":True,**export_workspace(service.settings,params["path"])}
    if method=="workspace.validate":
        from studyflow.modules.workspace.repository import validate_backup
        return validate_backup(params["path"])
    if method=="workspace.restore":
        from pathlib import Path
        target=Path(params["target_root"]).resolve()
        if target==service.settings.workspace_root.resolve():raise DomainError("ACTIVE_WORKSPACE_RESTORE_FORBIDDEN","不能直接覆盖活动工作区，请选择新目录。")
        from studyflow.modules.workspace.repository import restore_workspace
        return restore_workspace(params["path"],target)
    if method in {"course.update.preview","course.update.apply"}:
        from studyflow.modules.courses.revisions import preview, apply
        return (preview if method.endswith("preview") else apply)(service.courses,**params)
    if method=="assignment.summary":
        from studyflow.modules.reviews.queue_queries import summary
        return summary(service.reviews,**params)
    if method=="assignment.context":
        from studyflow.modules.reviews.queue_queries import context
        return context(service,**params)
    if method=="review.retest.publish":
        from studyflow.modules.reviews.retests import publish
        return publish(service.reviews,**params)
    if method=="submission.resolve-branch":
        from studyflow.modules.learning.branches import resolve
        return resolve(service.learning,**params)
    if method=="system.changes":
        return service.queries.change_token()
    if method=="system.schema":
        from studyflow.interfaces.engine.schemas import schemas
        return schemas(params.get("method"))
    raise DomainError("METHOD_NOT_FOUND","方法不存在。")
