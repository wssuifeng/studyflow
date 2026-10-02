from pathlib import Path

import pytest

from studyflow.domain import DomainError
from studyflow.markdown import parse_front_matter, render_markdown


def test_front_matter_parses_generic_learning_metadata():
    metadata, body = parse_front_matter("""---
course: Software Design
lesson: Relational Model
plan_line: Software Designer
subject: Database
content_type: EXAM_PREP
difficulty: FOUNDATION
source_type: CODEX
exercises:
  - title: Candidate key
    type: EXAM_QUESTION
    prompt: Explain candidate keys.
---
# Lesson body
""")
    assert metadata["plan_line"] == "Software Designer"
    assert metadata["exercises"][0]["type"] == "EXAM_QUESTION"
    assert body.strip() == "# Lesson body"


def test_front_matter_requires_mapping_and_valid_yaml():
    with pytest.raises(DomainError):
        parse_front_matter("---\n[not, a, mapping]\n---\nbody")


def test_markdown_rendering_strips_script_tags():
    rendered = render_markdown("# Safe\n\n<script>alert(1)</script><b>ok</b>")
    assert "<h1>Safe</h1>" in rendered
    assert "<script" not in rendered
    assert "alert(1)" not in rendered


def test_markdown_import_does_not_escape_workspace(tmp_path):
    outside = tmp_path.parent / "outside-studyflow.md"
    try:
        with pytest.raises(DomainError):
            from studyflow.markdown import resolve_import_path
            resolve_import_path(tmp_path, outside)
    finally:
        outside.unlink(missing_ok=True)
