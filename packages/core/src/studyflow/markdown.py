"""Compatibility import; implementation lives in studyflow.infrastructure.markdown."""
from studyflow.infrastructure.markdown import DocumentInspection, safe_resolve, resolve_import_path, parse_front_matter, validate_import_metadata, render_markdown, inspect_document, ALLOWED_TAGS, ALLOWED_ATTRIBUTES

__all__ = ['DocumentInspection', 'safe_resolve', 'resolve_import_path', 'parse_front_matter', 'validate_import_metadata', 'render_markdown', 'inspect_document', 'ALLOWED_TAGS', 'ALLOWED_ATTRIBUTES']
