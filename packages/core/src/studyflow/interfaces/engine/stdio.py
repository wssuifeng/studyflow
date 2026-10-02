from __future__ import annotations
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, TextIO
from studyflow.config import Settings
from studyflow.db import build_engine, build_session_factory, init_db
from studyflow.domain import DomainError
from studyflow.diagnostics import record_engine_error
from studyflow.engine_protocol import CAPABILITIES, PROTOCOL_VERSION, capabilities_payload, error_payload, make_response, version_payload
from studyflow.services import AppService
from studyflow.presentation import course_summary, submission_summary
from . import dispatcher
from .dispatcher import run_stdio


def main() -> None:
    # The desktop bridge always sends UTF-8 bytes, regardless of Windows locale.
    sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    engine = dispatcher.StudyFlowEngine()
    try:
        run_stdio(engine)
    finally:
        engine.close()
