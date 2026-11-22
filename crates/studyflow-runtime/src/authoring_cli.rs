use serde_json::{json, Value};
use std::{collections::BTreeMap, path::Path, process::ExitCode};
use studyflow_core::authoring::{Error, MaterialRoot, Query};

const USAGE: &str = "Usage: studyflow authoring-workspace --root <author-root> <query|select|coverage|link|audit> [options]";
const COMMANDS: &[(&str, &str, &str)] = &[
    ("authoring_workspace_query", "studyflow authoring-workspace --root <root> query --source <id=path> --word <word>", "read"),
    ("authoring_workspace_select", "studyflow authoring-workspace --root <root> select --recipe <json> --output <dir>", "write"),
    ("authoring_workspace_coverage", "studyflow authoring-workspace --root <root> coverage --source <id=path> --selections-dir <dir>", "read"),
    ("authoring_workspace_link", "studyflow authoring-workspace --root <root> link --selection <dir> --receipt <json> --course <id> --content-revision <n>", "write"),
    ("authoring_workspace_audit", "studyflow authoring-workspace --root <root> audit --config <json>", "read"),
];

pub(crate) fn capabilities() -> &'static [(&'static str, &'static str, &'static str)] {
    COMMANDS
}

pub fn execute(args: impl Iterator<Item = String>) -> ExitCode {
    let args: Vec<_> = args.collect();
    if args.iter().any(|arg| arg == "--help" || arg == "-h") {
        println!("{USAGE}");
        for (_, command, _) in COMMANDS {
            println!("  {command}");
        }
        println!("query also accepts --contains, --browse with --purpose, --limit, --max-chars, --cursor and --exclude-selections-dir");
        return ExitCode::SUCCESS;
    }
    let result = run(&args).unwrap_or_else(|error| json!({"ok":false,"error":{"code":error.code,"message":error.message.chars().take(500).collect::<String>()}}));
    println!("{result}");
    if result["ok"] == true {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

fn argument(message: &str) -> Error {
    Error {
        code: "ARGUMENT",
        message: format!("ARGUMENT: {message}"),
    }
}

fn run(args: &[String]) -> Result<Value, Error> {
    let first = args.first().ok_or_else(|| argument(USAGE))?;
    let (path, args) = if let Some(path) = first.strip_prefix("--root=") {
        (path, &args[1..])
    } else if first == "--root" && args.len() >= 2 {
        (args[1].as_str(), &args[2..])
    } else {
        return Err(argument(USAGE));
    };
    let (command, args) = args.split_first().ok_or_else(|| argument(USAGE))?;
    let (required, optional): (&[&str], &[&str]) = match command.as_str() {
        "query" => (
            &["--source"],
            &[
                "--word",
                "--contains",
                "--browse",
                "--purpose",
                "--limit",
                "--max-chars",
                "--cursor",
                "--exclude-selections-dir",
            ],
        ),
        "select" => (&["--recipe", "--output"], &[]),
        "coverage" => (&["--source", "--selections-dir"], &[]),
        "link" => (
            &["--selection", "--receipt", "--course", "--content-revision"],
            &[],
        ),
        "audit" => (&["--config"], &[]),
        _ => return Err(argument(USAGE)),
    };
    let mut options = BTreeMap::<&str, Vec<&str>>::new();
    let mut args = args.iter().map(String::as_str);
    while let Some(flag) = args.next() {
        let (key, value) = flag
            .split_once('=')
            .map_or((flag, None), |(key, value)| (key, Some(value)));
        if !required.contains(&key) && !optional.contains(&key) {
            return Err(argument("unknown option"));
        }
        let value = match (key, value) {
            ("--browse", None) => "true",
            ("--browse", Some(_)) => return Err(argument("--browse is a switch")),
            (_, value) => value
                .or_else(|| args.next().filter(|arg| !arg.starts_with("--")))
                .ok_or_else(|| argument("option needs a value"))?,
        };
        options.entry(key).or_default().push(value);
    }
    if required.iter().any(|key| !options.contains_key(key)) {
        return Err(argument("missing required options"));
    }
    let get = |key| options.get(key).and_then(|values| values.last().copied());
    let string = |key| get(key).unwrap_or_default();
    let number = |key, default| {
        get(key).map_or(Ok(default), |value| {
            value
                .trim()
                .parse::<i64>()
                .map_err(|_| argument("expected an integer"))
        })
    };
    let sources = || {
        options["--source"]
            .iter()
            .map(|value| {
                value
                    .split_once('=')
                    .map(|(id, path)| (id.to_owned(), path.to_owned()))
                    .ok_or_else(|| Error {
                        code: "SOURCE_ID",
                        message: "SOURCE_ID: use stable-id=relative-path".into(),
                    })
            })
            .collect::<Result<Vec<_>, _>>()
    };
    let root = MaterialRoot::open(Path::new(path))?;
    match command.as_str() {
        "query" => root.query(&Query {
            sources: sources()?,
            words: options
                .get("--word")
                .into_iter()
                .flatten()
                .map(|word| (*word).to_owned())
                .collect(),
            contains: string("--contains").to_owned(),
            browse: options.contains_key("--browse"),
            purpose: string("--purpose").to_owned(),
            limit: usize::try_from(number("--limit", 20)?).unwrap_or(0),
            max_chars: usize::try_from(number("--max-chars", 16000)?).unwrap_or(0),
            cursor: get("--cursor").map(str::to_owned),
            exclude_selections_dir: get("--exclude-selections-dir").map(str::to_owned),
        }),
        "select" => root.select(string("--recipe"), string("--output")),
        "coverage" => root.coverage(&sources()?, string("--selections-dir")),
        "link" => root.link(
            string("--selection"),
            string("--receipt"),
            string("--course"),
            number("--content-revision", 0)?,
        ),
        "audit" => root.audit(string("--config")),
        _ => unreachable!("validated author command"),
    }
}
