"""Check the public source boundary without exposing matched secret values.

Tracked mode is used before commits and by CI. All mode is for a fresh export.
This is a conservative publication guard, not a full secret scanner.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {".gitignore", ".gitattributes", "README.md", "AGENTS.md", "CONTRIBUTING.md", "SECURITY.md"}
TREES = {"desktop", "studyflow_app", "docs", "skills", "scripts", ".github"}
APP_TREES = {"studyflow", "migrations", "tests", "templates", "static"}
APP_FILES = {"pyproject.toml", "alembic.ini", ".env.example", "engine_entry.py", "README.md"}
DESKTOP_TREES = {"src", "scripts", "src-tauri"}
DESKTOP_FILES = {"package.json", "package-lock.json", "index.html", "tsconfig.json", "tsconfig.node.json", "vite.config.ts"}
TAURI_TREES = {"src", "capabilities", "icons"}
TAURI_FILES = {"Cargo.toml", "Cargo.lock", "build.rs", "tauri.conf.json"}
DEMO = "studyflow_app/content/lessons/java-reference.md"
BINARY_ASSETS = {"desktop/src-tauri/icons/icon.png", "desktop/src-tauri/icons/icon.ico"}
TEXT_SUFFIXES = {".md", ".py", ".ps1", ".vue", ".ts", ".css", ".html", ".svg", ".rs", ".json", ".toml", ".lock", ".ini", ".yaml", ".yml", ".example", ".mako"}
GENERATED_PARTS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "node_modules", "target", "dist", "build", "out", "test-results", "runtime", ".studyflow", "gen"}
PRIVATE_PARTS = {"就业计划", "英语四级计划", "软考_软件设计师计划", "项目理解与掌握计划", "归档", "示例PDF与PDF生成参考提示词", "design-explorations"}
FORBIDDEN = re.compile(r"\.(?:db(?:-wal|-shm)?|sqlite\d?(?:-wal|-shm)?|exe|msi|zip|7z|rar|pdf|pem|key|p12|pfx|log|jsonl|bak)(?:\.|$)", re.I)
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "github-token": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})"),
    "api-key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "personal-windows-path": re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\s<>\"']+", re.I),
}


def path_problem(relative: str) -> str | None:
    path = PurePosixPath(relative)
    parts = path.parts
    if not parts or path.is_absolute() or ".." in parts:
        return "unsafe-path"
    if any(p in GENERATED_PARTS or p in PRIVATE_PARTS or p.endswith(".egg-info") or p.startswith("pytest-of-") for p in parts):
        return "private-or-generated-directory"
    if FORBIDDEN.search(path.name) or path.name.startswith(".env") and path.name != ".env.example":
        return "private-or-generated-file"
    if len(parts) == 1:
        return None if relative in TOP_FILES else "unapproved-root-file"
    if parts[0] not in TREES:
        return "unapproved-root-directory"
    if parts[0] == "studyflow_app":
        if relative == DEMO:
            return None
        if len(parts) == 2 and parts[1] not in APP_FILES:
            return "unapproved-app-file"
        if len(parts) > 2 and parts[1] not in APP_TREES:
            return "unapproved-app-directory"
    if parts[0] == "desktop":
        if len(parts) == 2 and parts[1] not in DESKTOP_FILES:
            return "unapproved-desktop-file"
        if len(parts) > 2 and parts[1] not in DESKTOP_TREES:
            return "unapproved-desktop-directory"
        if len(parts) > 2 and parts[1] == "src-tauri":
            if len(parts) == 3 and parts[2] not in TAURI_FILES:
                return "unapproved-tauri-file"
            if len(parts) > 3 and parts[2] not in TAURI_TREES:
                return "unapproved-tauri-directory"
            if parts[2] == "icons" and relative not in BINARY_ASSETS:
                return "unapproved-binary-asset"
    if relative in BINARY_ASSETS:
        return None
    if path.suffix not in TEXT_SUFFIXES and relative not in {".github/CODEOWNERS"}:
        return "unapproved-file-type"
    return None


def check_paths(paths: list[str]) -> dict:
    issues: list[dict] = []
    for relative in sorted(set(paths)):
        reason = path_problem(relative)
        if reason:
            issues.append({"path": relative, "reason": reason})
            continue
        file = ROOT / relative
        if file.is_symlink() or any(p.is_symlink() for p in file.parents if p != ROOT):
            issues.append({"path": relative, "reason": "linked-path"})
            continue
        if file.resolve().is_relative_to(ROOT) is False:
            issues.append({"path": relative, "reason": "outside-project"})
            continue
        if relative in BINARY_ASSETS:
            continue
        try:
            text = file.read_text(encoding="utf-8-sig")
        except (UnicodeError, OSError):
            issues.append({"path": relative, "reason": "unreadable-text"})
            continue
        for name, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                issues.append({"path": relative, "reason": name, "line": text.count("\n", 0, match.start()) + 1})
    return {"ok": not issues, "checked_files": len(set(paths)), "issues": issues,
            "scope": "public-source-boundary", "business_acceptance": "not_evaluated"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--tracked", action="store_true")
    mode.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if args.tracked:
        result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True)
        paths = [p for p in result.stdout.decode("utf-8").split("\0") if p]
    else:
        paths = []
        for file in ROOT.rglob("*"):
            parts = file.relative_to(ROOT).parts
            if any(p in GENERATED_PARTS or p.endswith(".egg-info") for p in parts):
                continue
            if file.is_file() or file.is_symlink():
                paths.append(file.relative_to(ROOT).as_posix())
    report = check_paths(paths)
    if not paths:
        report["ok"] = False
        report["issues"].append({"reason": "empty-scope"})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
