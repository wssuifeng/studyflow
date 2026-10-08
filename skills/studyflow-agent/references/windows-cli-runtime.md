# Windows source CLI runtime diagnosis

Use this only when a known source CLI reports `workspace.writable=false` or SQLite `attempt to write a readonly database`. It is an operational diagnosis, not permission to raise privileges or change product architecture.

## Distinguish the causes

- A reachable database is not necessarily writable. app1.3.0 `doctor` can report `healthy=true` together with `workspace.writable=false`; require both flags before business writes.
- Check the known launcher with `icacls "<source-checkout>\packages\core\.venv\Scripts\python.exe"` (read only). `Low Mandatory Level` is a Windows integrity label, not the file's ReadOnly attribute. A normal shell does not prove its Python child has the same integrity level.
- Use a uniquely named, immediately cleaned diagnostic file in the selected workspace only if needed; never probe by SQL or modifying real data. Stop the business write on denial.
- When an independent Python file-create probe is denied before importing StudyFlow, do not misdiagnose the course parser. A process integrity comparison or OS error can then establish the runtime access restriction.
- In app1.3.0, SQLite read-only errors were wrapped as `INTERNAL_ERROR`; preserve that historical evidence. App1.4.0 classifies read-only, lock, constraint and disk-full failures, and doctor includes write/flush/fsync probes. This guide does not repair ACLs or a genuinely restricted process.

## Explicit authorized runtime selection

**If the current Agent is still subject to a sandbox that excludes this workspace, stop and request appropriate authorization. Do not switch interpreters, brokers, launch users, or file APIs to escape that restriction.**

Only when ordinary local access is already authorized, and the source launcher itself has a stale Low label, select the normal installed Python declared by that venv's `pyvenv.cfg`. Verify the same Python major/minor version and the expected CLI source. Do not guess another Python install, reinstall globally, clear labels, modify ACLs, use RunAs, or change the workspace/database to hide the error.

Run the existing CLI with its existing source and matching venv dependencies (environment changes are process-local):

```powershell
$checkout = '<source-checkout>'
$python = '<normal-installed-python-matching-pyvenv.cfg>'
$env:PYTHONPATH = (Join-Path $checkout 'packages\core\src') + ';' + (Join-Path $checkout 'packages\core\.venv\Lib\site-packages')
$env:STUDYFLOW_WORKSPACE = '<same-explicit-data-workspace>'
& $python -B -X utf8 -m studyflow version --format json
& $python -B -X utf8 -m studyflow doctor --format json
```

Check zero exit status, parseable JSON, unchanged `workspace.root`, `healthy=true` and `workspace.writable=true` again. Inspect `studyflow.interfaces.cli.runtime.__file__` if package resolution is uncertain. With these checks satisfied, the authorized external Agent resumes supported CLI writes, after backup and existing-record discovery; do not turn the workflow into a routine manual task for the learner. If denial remains, stop and preserve the evidence rather than retrying blindly.

This does not install a standalone CLI, persist PATH, change the desktop Engine, or authorize an administrator process. Record the selected runtime and the successful CLI readback, and preserve prior failure evidence.
