"""Compatibility import; implementation lives in studyflow.interfaces.engine.protocol."""
from studyflow.interfaces.engine.protocol import redact_sensitive_text, error_payload, make_response, discovery_metadata, version_payload, capabilities_payload, PROTOCOL_VERSION, CAPABILITIES, _CREDENTIAL_URL, _SENSITIVE_QUERY

__all__ = ['redact_sensitive_text', 'error_payload', 'make_response', 'discovery_metadata', 'version_payload', 'capabilities_payload', 'PROTOCOL_VERSION', 'CAPABILITIES', '_CREDENTIAL_URL', '_SENSITIVE_QUERY']
