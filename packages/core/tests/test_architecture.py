"""Architecture guards: public compatibility and module ownership."""
import ast
import importlib
from pathlib import Path

EXPECTED_TABLES = {"plan_lines", "stages", "tasks", "time_blocks", "courses", "plan_course_items", "course_schedule_items", "lessons", "exercises", "submissions", "review_feedback", "learning_progress", "submission_write_receipts", "course_write_receipts", "documents", "context_snapshots", "event_logs", "course_study_sessions", "study_notes", "study_note_receipts", "plan_notebooks", "plan_notebook_receipts", "submission_chain_links", "retest_tasks", "course_revisions", "plan_write_receipts"}


def test_business_modules_are_importable():
    for name in ("planning", "courses", "learning", "reviews", "documents", "workspace"):
        importlib.import_module(f"studyflow.modules.{name}.models")
        importlib.import_module(f"studyflow.modules.{name}.service")


def test_registered_models_keep_exact_schema_table_names():
    from studyflow import models
    from studyflow.db import Base
    assert set(Base.metadata.tables) == EXPECTED_TABLES
    assert models.Course.__module__ == "studyflow.modules.courses.models"
    assert models.Submission.__module__ == "studyflow.modules.learning.models"


def test_business_modules_do_not_import_application_facade():
    import studyflow
    modules = Path(studyflow.__file__).parent / "modules"
    assert modules.is_dir()
    for path in modules.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("studyflow.application"), path
                assert "AppService" not in {name.name for name in node.names}, path


def test_compatibility_facade_has_no_database_queries():
    import studyflow.application.facade as facade
    tree = ast.parse(Path(facade.__file__).read_text(encoding="utf-8"))
    assert not any(isinstance(n, ast.Name) and n.id in {"select", "joinedload", "selectinload"} for n in ast.walk(tree))
    from studyflow.services import AppService
    assert AppService is facade.AppService


def test_legacy_dto_imports_delegate_to_business_modules():
    from studyflow.schemas import ReviewInput, SubmissionInput
    from studyflow.modules.reviews.schemas import ReviewInput as review
    from studyflow.modules.learning.schemas import SubmissionInput as submission
    assert ReviewInput is review
    assert SubmissionInput is submission


def test_single_src_layout_owns_the_package():
    import studyflow
    core = Path(__file__).resolve().parents[1]
    assert Path(studyflow.__file__).resolve().parent == core / "src/studyflow"


def test_desktop_engine_ipc_runs_off_the_window_thread():
    """Static regression guard; native-window interaction still needs real testing."""
    root = Path(__file__).resolve().parents[3]
    source = (root / "apps/desktop/src-tauri/src/commands.rs").read_text(encoding="utf-8")
    for name in ("engine_call", "engine_status"):
        signature = f"pub(super) async fn {name}("
        assert signature in source, f"{name} must not block the window event handler"
        body = source.split(signature, 1)[1].split("#[tauri::command]", 1)[0]
        assert "tauri::async_runtime::spawn_blocking" in body
