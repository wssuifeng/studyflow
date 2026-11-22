use std::process::ExitCode;

// Command paths exposed by the native dispatcher. The same list feeds shell completion.
pub const COMMANDS: &[(&str, &str)] = &[
    ("", "--show-completion --install-completion --help"),
    ("db-upgrade", "--format"),
    ("init", ""),
    ("status", "--date --plan-line --kind --format"),
    ("today", "--date --plan-line --kind --format"),
    ("version", "--format"),
    ("capabilities", "--format"),
    ("doctor", "--format"),
    ("call", "--method --file --format"),
    ("plan", ""),
    ("course", ""),
    ("submission", ""),
    ("review", ""),
    ("document", ""),
    ("snapshot", ""),
    ("task", ""),
    ("assignment", ""),
    ("workspace", ""),
    ("plan list", "--format"),
    ("plan create", "--name --priority --format"),
    ("plan task-list", "--date --plan-line --kind --format"),
    ("plan task-create", "--title --date --kind --plan-line --description --priority --format"),
    ("plan detail", "--id --format"),
    ("plan notebook-get", "--id --format"),
    ("plan notebook-save", "--id --file --expected-version --idempotency-key --format"),
    ("plan notebook-read", "--id --course --lesson --entry --query --offset --limit --expected-version --format"),
    ("plan notebook-apply", "--id --file --expected-version --idempotency-key --format"),
    ("course list", "--plan-line --format"),
    ("course detail", "--id --format"),
    ("course import", "--file --format"),
    ("course study-open", "--id --idempotency-key --new-version --format"),
    ("course study-detail", "--study-id --format"),
    ("course notes-get", "--study-id --format"),
    ("course notes-save", "--study-id --lesson-id --file --expected-version --idempotency-key --format"),
    ("course validate-package", "--file --format"),
    ("course import-package", "--file --format"),
    ("course readback-check", "--course --plan-line --format"),
    ("course quality-check", "--file --blueprint --sources --related --validation-receipt --rendering-receipt --long-section-chars --format"),
    ("course reset-learning", "--id --dry-run --confirm --state-hash --content-hash --idempotency-key --format"),
    ("course update-preview", "--id --file --expected-revision --format"),
    ("course update-apply", "--id --file --expected-revision --preview-hash --idempotency-key --format"),
    ("course answers", ""),
    ("submission get", "--id --format"),
    ("submission list-pending", "--format"),
    ("submission revise", "--parent --file --idempotency-key --format"),
    ("submission retest", "--parent --file --idempotency-key --format"),
    ("review write", "--submission --summary --file --issue-count --needs-revision --decision --next-action --idempotency-key --format"),
    ("document read", "--path --format"),
    ("document check", "--path --format"),
    ("snapshot generate", "--scope --format"),
    ("task list", "--date --plan-line --kind --format"),
    ("task create", "--title --date --kind --plan-line --description --priority --format"),
    ("assignment queue", "--plan-line --format --full --role --limit"),
    ("workspace export", "--output --format"),
    ("workspace purge-legacy-notes", "--dry-run --confirm --preview-token --format"),
    ("workspace purge-courses", "--id --dry-run --confirm --backup --format"),
    ("workspace import", "--file --target --format"),
    ("course answers get", "--id --format"),
    ("course answers save", "--id --file --idempotency-key --format"),
    ("course answers submit", "--id --file --idempotency-key --format"),
    ("authoring-workspace", "--root"),
];

pub fn print(path: &[String]) -> Option<ExitCode> {
    let name = path.join(" ");
    if matches!(name.as_str(), "" | "authoring-workspace") {
        return None;
    }
    let (_, options) = COMMANDS.iter().find(|(command, _)| *command == name)?;
    println!(
        "Usage: studyflow {name}{}",
        if options.is_empty() { "" } else { " [OPTIONS]" }
    );
    let prefix = format!("{name} ");
    for (command, _) in COMMANDS {
        if let Some(child) = command
            .strip_prefix(&prefix)
            .filter(|child| !child.contains(' '))
        {
            println!("  {child}");
        }
    }
    for option in options.split_whitespace() {
        println!("  {option}");
    }
    println!("  --help");
    Some(ExitCode::SUCCESS)
}
