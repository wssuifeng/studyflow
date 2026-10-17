"""Single Core implementation of deterministic authoring-quality checks.

W1 design ``docs/30_系统设计/W1生成侧质量工具与接口详细设计-v1.md`` §2: rules live
only here (``rules.py``/``report.py``/``chains.py``); the Skill script becomes a
thin proxy. ``analyze`` is read-only and never mutates its inputs.
"""
from .chains import build_teaching_chain_list
from .report import REPORT_SCHEMA, analyze
from .rules import RULE_VERSION

__all__ = ["REPORT_SCHEMA", "RULE_VERSION", "analyze", "build_teaching_chain_list"]
