"""Thin proxy to the StudyFlow CLI: `studyflow course quality-check`.

自 W1 设计（docs/30_系统设计/W1生成侧质量工具与接口详细设计-v1.md §2/§7）起，本脚本
不再内置任何规则实现：确定性制课质量检查的唯一实现位于 StudyFlow Core，作者主入口是
只读 CLI 命令 `studyflow course quality-check`。本脚本只做参数原样转发与
stdout/stderr/退出码透传；找不到 CLI 时以退出码 2 明确报错，不静默降级。
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

QUALITY_CHECK_COMMAND = ("course", "quality-check")
CLI_NOT_FOUND_EXIT = 2


def _sibling_cli() -> str | None:
    """与 sys.executable 同目录下的 studyflow / studyflow.exe。"""
    base = Path(sys.executable).resolve().parent
    for name in ("studyflow", "studyflow.exe"):
        candidate = base / name
        if candidate.is_file():
            return str(candidate)
    return None


def resolve_cli() -> str | None:
    """CLI 定位顺序：PATH 中的 studyflow（shutil.which）→ 解释器同目录的 studyflow/studyflow.exe。"""
    found = shutil.which("studyflow")
    if found:
        return found
    return _sibling_cli()


def main() -> int:
    cli = resolve_cli()
    if cli is None:
        sys.stderr.write(
            "错误：找不到 studyflow CLI。本脚本已改为StudyFlow CLI薄代理，"
            "需要在已安装 studyflow CLI 的环境中运行。\n"
            "定位顺序：PATH 中的 studyflow，或与运行本脚本的 Python 解释器同目录的 "
            "studyflow/studyflow.exe。请先安装/定位 CLI，再运行 "
            "studyflow course quality-check --file <package.json>。\n"
        )
        return CLI_NOT_FOUND_EXIT
    completed = subprocess.run([cli, *QUALITY_CHECK_COMMAND, *sys.argv[1:]])
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
