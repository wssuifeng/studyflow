from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import bleach
import markdown as markdown_lib
import yaml

from .domain import DomainError


@dataclass(frozen=True)
class DocumentInspection:
    relative_path: str
    status: str
    file_size: int = 0
    modified_at: datetime | None = None
    content_hash: str = ""
    html: str = ""


ALLOWED_TAGS = set(bleach.sanitizer.ALLOWED_TAGS) | {
    "p", "h1", "h2", "h3", "h4", "hr", "pre", "code",
    "blockquote", "table", "thead", "tbody", "tr", "th", "td",
    "del", "input", "br",
}
ALLOWED_ATTRIBUTES = {
    **bleach.sanitizer.ALLOWED_ATTRIBUTES,
    "input": ["type", "checked", "disabled"],
    "code": ["class"],
    "pre": ["class"],
}


def safe_resolve(workspace_root: Path, relative_path: str | Path) -> Path:
    root = workspace_root.resolve()
    raw = Path(relative_path).expanduser()
    candidate = (raw if raw.is_absolute() else root / raw).resolve()
    if candidate != root and root not in candidate.parents:
        raise DomainError("PATH_OUTSIDE_WORKSPACE", "文档路径必须位于配置的工作区目录内。", "调整 STUDYFLOW_WORKSPACE 或将 Markdown 文件移动到工作区中。")
    return candidate


def resolve_import_path(workspace_root: Path, path: str | Path) -> tuple[Path, str]:
    candidate = safe_resolve(workspace_root, path)
    if not candidate.is_file():
        raise DomainError("DOCUMENT_NOT_FOUND", f"Markdown 文件不存在：{path}", "确认文件路径后重试。")
    if candidate.suffix.lower() not in {".md", ".markdown"}:
        raise DomainError("UNSUPPORTED_DOCUMENT_TYPE", "课程导入目前只接受 Markdown 文件。", "使用 .md 或 .markdown 文件。")
    return candidate, candidate.relative_to(workspace_root.resolve()).as_posix()


def parse_front_matter(content: str) -> tuple[dict[str, Any], str]:
    if not content.startswith("---\n") and not content.startswith("---\r\n"):
        raise DomainError("FRONT_MATTER_REQUIRED", "Markdown 文件需要以 YAML Front Matter 开始。", "添加包含 course、lesson、plan_line 的 Front Matter。")
    lines = content.splitlines(keepends=True)
    closing = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if closing is None:
        raise DomainError("FRONT_MATTER_INVALID", "YAML Front Matter 缺少结束分隔符。", "使用单独一行 --- 结束元数据区。")
    try:
        metadata = yaml.safe_load("".join(lines[1:closing])) or {}
    except yaml.YAMLError as exc:
        raise DomainError("FRONT_MATTER_INVALID", f"YAML Front Matter 无法解析：{exc}", "修正 YAML 缩进、引号或列表格式。") from exc
    if not isinstance(metadata, dict):
        raise DomainError("FRONT_MATTER_INVALID", "YAML Front Matter 顶层必须是键值对象。", "将元数据写成 key: value 格式。")
    body = "".join(lines[closing + 1:]).lstrip("\r\n")
    return metadata, body


def validate_import_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    required = ("course", "lesson", "plan_line")
    missing = [key for key in required if not isinstance(metadata.get(key), str) or not metadata[key].strip()]
    if missing:
        raise DomainError("FRONT_MATTER_REQUIRED_FIELD", f"Front Matter 缺少必填字段：{', '.join(missing)}", "填写 course、lesson 和 plan_line 字段。")
    exercises = metadata.get("exercises", [])
    if exercises is None:
        exercises = []
    if not isinstance(exercises, list) or any(not isinstance(item, dict) for item in exercises):
        raise DomainError("FRONT_MATTER_INVALID_EXERCISES", "exercises 必须是对象列表。", "检查 YAML exercises 列表缩进。")
    normalized = dict(metadata)
    normalized["course"] = metadata["course"].strip()
    normalized["lesson"] = metadata["lesson"].strip()
    normalized["plan_line"] = metadata["plan_line"].strip()
    normalized["exercises"] = exercises
    return normalized


def render_markdown(content: str, strip_front_matter: bool = False) -> str:
    if strip_front_matter and content.startswith("---"):
        _, content = parse_front_matter(content)
    # Remove executable container contents before Markdown conversion; sanitizing only the
    # tag would leave visible JavaScript text in the rendered lesson.
    content = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", "", content, flags=re.IGNORECASE | re.DOTALL)
    rendered = markdown_lib.markdown(content, extensions=["extra", "sane_lists", "toc"])
    return bleach.clean(rendered, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, protocols={"http", "https", "mailto"}, strip=True)


def inspect_document(workspace_root: Path, relative_path: str, render: bool = False) -> DocumentInspection:
    candidate = safe_resolve(workspace_root, relative_path)
    if not candidate.exists():
        return DocumentInspection(relative_path=relative_path, status="MISSING")
    if not candidate.is_file():
        return DocumentInspection(relative_path=relative_path, status="UNREADABLE")
    try:
        content = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return DocumentInspection(relative_path=relative_path, status="UNREADABLE")
    stat = candidate.stat()
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    html = render_markdown(content, strip_front_matter=True) if render else ""
    return DocumentInspection(relative_path, "PRESENT", stat.st_size, datetime.fromtimestamp(stat.st_mtime), digest, html)
