"""Compatibility import; implementation lives in studyflow.modules.workspace.repository."""
from studyflow.modules.workspace.repository import _sha256_file, _safe_relative, _safe_archive_member, _workspace_file, _schema_revision, _document_paths, _snapshot_sqlite, export_workspace, _read_manifest, _extract_member, restore_workspace

__all__ = ['_sha256_file', '_safe_relative', '_safe_archive_member', '_workspace_file', '_schema_revision', '_document_paths', '_snapshot_sqlite', 'export_workspace', '_read_manifest', '_extract_member', 'restore_workspace']
