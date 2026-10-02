"""Compatibility import; implementation lives in studyflow.application.facade."""
from studyflow.application.facade import AppService

__all__ = ['AppService']

from studyflow.shared.ids import new_id
from studyflow.shared.constants import AGENT_SOURCE, PASSED_STATES, QUEUE_STATUSES, FOLLOWUP_ALLOWED_STATUSES
