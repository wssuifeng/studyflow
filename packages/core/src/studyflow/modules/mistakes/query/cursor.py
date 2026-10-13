"""Opaque continuation bound to the exact query scope, not an authorization token."""
import base64
import json
from studyflow.modules.learning.write_contract import digest
from studyflow.shared.domain import DomainError


def fingerprint(scope, domain, notebook_id, identifier=None):
    defaults = {"plan_line_id": None, "domain": None, "notebook_id": None, "course_id": None,
                "archived": False, "objective_id": None, "since": None, "until": None, "view": "training_errors"}
    return digest({"scope": {**defaults, **scope}, "domain": domain, "notebook_id": notebook_id, "identifier": identifier})


def encode(last_id, scope_hash):
    raw = json.dumps({"v": 1, "last": last_id, "scope": scope_hash}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode(cursor, scope_hash):
    try:
        if not isinstance(cursor, str) or len(cursor) > 512: raise ValueError()
        value = json.loads(base64.b64decode(cursor + "="*(-len(cursor)%4), altchars=b"-_", validate=True))
        if not isinstance(value, dict) or value.get("v") != 1 or value.get("scope") != scope_hash or not isinstance(value.get("last"), str) or len(value["last"]) != 36:
            raise ValueError()
        return value["last"]
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise DomainError("INVALID_CURSOR", "分页游标无效或查询范围已改变，请重新读取第一页。") from None
