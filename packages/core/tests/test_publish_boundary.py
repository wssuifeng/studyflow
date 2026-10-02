"""A layout migration must not widen the public publication boundary."""
from pathlib import Path
import runpy
import pytest

GUARD = runpy.run_path(str(Path(__file__).resolve().parents[3] / "scripts/check_publish_boundary.py"))


@pytest.mark.parametrize("path", [
    "apps/desktop/src/app/App.vue",
    "apps/desktop/scripts/test-course-answers.cjs",
    "apps/desktop/src-tauri/src/engine.rs",
    "apps/desktop/src-tauri/icons/icon.png",
    "packages/core/pyproject.toml",
    "packages/core/.env.example",
    "packages/core/src/studyflow/modules/planning/models.py",
    "packages/core/src/studyflow/resources/migrations/versions/0005_course_answers.py",
    "packages/core/src/studyflow/resources/content/lessons/java-reference.md",
])
def test_known_source_paths_remain_publishable(path):
    assert GUARD["path_problem"](path) is None


@pytest.mark.parametrize("path", [
    "apps/desktop/scripts/unknown.cjs",
    "apps/other/src/main.ts", "packages/other/src/main.py",
    "packages/core/src/private/main.py", "studyflow_app/studyflow/cli.py",
    "packages/core/.venv/pyvenv.cfg", "packages/core/.studyflow/studyflow.db",
    "packages/core/content/answers.md",
    "packages/core/src/studyflow/resources/content/real-answers.md",
    "apps/desktop/test-results/screenshots/private.png",
    "packages/core/.env", "packages/core/studyflow.db", "../private.md",
])
def test_private_generated_and_unknown_subprojects_are_rejected(path):
    assert GUARD["path_problem"](path) is not None
