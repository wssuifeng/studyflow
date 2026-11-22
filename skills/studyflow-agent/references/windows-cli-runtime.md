# Windows CLI runtime diagnosis

1. Use the absolute CLI path from Workspace settings or `system.installation.cli_argv`. Keep the explicitly selected data workspace and display the reported `workspace.root` before taking action.
2. Run `version --format json` and `doctor --format json`. Record the version, `workspace.write_access` and `database.write_access` fields. Their `reason`, `phase` and `scope` distinguish a missing directory, an access failure and a failed write probe. Preserve the exit code.
3. If `healthy` or `workspace.writable` is false, pause business writes and report the path and failing probe. Verify the expected Windows account and available disk space. If a maintenance lease is held, close the StudyFlow process using that workspace before a confirmed upgrade or restore.
4. Resume writes only after the same approved executable can verify the intended workspace and the selected capability. A reachable database is insufficient to confirm writability. Use the application's backup and restore commands to protect the SQLite and course-file snapshot.
