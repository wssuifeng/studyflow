use std::io;
use std::process::ExitCode;

fn main() -> ExitCode {
    let mut args = std::env::args().skip(1);
    match args.next().as_deref() {
        Some("--speech-worker") => {
            return match (args.next(), args.next(), args.next()) {
                (Some(job), Some(launch), None) => {
                    studyflow_runtime::run_speech_worker(&job, &launch)
                }
                _ => ExitCode::from(2),
            }
        }
        Some("--managed-desktop") => {
            return match (args.next(), args.next(), args.next()) {
                (Some(version), Some(protocol), None) => studyflow_runtime::serve_managed_engine(
                    io::stdin().lock(),
                    io::stdout().lock(),
                    &version,
                    &protocol,
                )
                .map(|()| ExitCode::SUCCESS)
                .unwrap_or_else(io_error),
                _ => ExitCode::from(2),
            };
        }
        None => (),
        _ => return ExitCode::from(2),
    }
    studyflow_runtime::serve_engine(io::stdin().lock(), io::stdout().lock())
        .map(|()| ExitCode::SUCCESS)
        .unwrap_or_else(io_error)
}

fn io_error(error: io::Error) -> ExitCode {
    eprintln!("Engine stdio: {error}");
    ExitCode::FAILURE
}
