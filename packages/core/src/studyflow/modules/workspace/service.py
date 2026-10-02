from __future__ import annotations
from datetime import date
from studyflow.modules.workspace.models import ContextSnapshot
from studyflow.shared.ids import new_id
from studyflow.shared.constants import AGENT_SOURCE


from studyflow.infrastructure.runtime import Runtime, Service


class WorkspaceService(Service):
    def __init__(self, runtime: Runtime, dashboard_provider):
        super().__init__(runtime)
        self.dashboard_provider = dashboard_provider

    def generate_snapshot(self, target_date: date | None = None, scope: str = "today") -> ContextSnapshot:
        target_date = target_date or date.today()
        dashboard = self.dashboard_provider(target_date)
        lines = [f"# StudyFlow 上下文快照 · {target_date}", "", f"- 当前范围：{scope}", f"- 主任务：{dashboard['primary_task'].title if dashboard['primary_task'] else '暂无'}", f"- 待批改：{len(dashboard['pending'])}", "", "## 下一动作", "打开今日工作台，继续主任务。"]
        relative_path = f"content/snapshots/{target_date}-snapshot.md"
        file_path = self.settings.workspace_root / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.session() as db:
            snapshot = ContextSnapshot(id=new_id(), snapshot_date=target_date, scope=scope, relative_path=relative_path, current_pointer=dashboard["primary_task"].title if dashboard["primary_task"] else "", summary="\n".join(lines))
            db.add(snapshot)
            db.flush()
            self._event(db, AGENT_SOURCE, "snapshot", snapshot.id, "GENERATE", "生成上下文快照")
            return snapshot
