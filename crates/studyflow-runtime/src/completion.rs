use std::{io, process::ExitCode};

use crate::{cli, cli_help};

const MARKER: &str = "# StudyFlow native CLI completion";

pub fn run(install: bool, mut args: impl Iterator<Item = String>) -> ExitCode {
    let shell = args.next().unwrap_or_else(|| "powershell".to_owned());
    if !matches!(shell.as_str(), "powershell" | "pwsh") || args.next().is_some() {
        return cli::usage_error();
    }
    let script = script();
    if !install {
        print!("{script}");
        return ExitCode::SUCCESS;
    }
    match install_current_user(&shell, &script) {
        Ok(path) => {
            println!("{}", path.display());
            ExitCode::SUCCESS
        }
        Err(error) => {
            eprintln!("StudyFlow completion: {error}");
            ExitCode::FAILURE
        }
    }
}

fn script() -> String {
    use std::fmt::Write;

    let mut script = format!("{MARKER}\n");
    script.push_str(
        "Register-ArgumentCompleter -Native -CommandName studyflow,studyflow.exe -ScriptBlock {\n",
    );
    script
        .push_str("    param($wordToComplete, $commandAst, $cursorPosition)\n    $commands = @{\n");
    for (path, options) in cli_help::COMMANDS {
        writeln!(script, "        '{path}' = '{options}'").expect("write to String");
    }
    script.push_str(
        r#"    }
    $path = ''
    foreach ($element in ($commandAst.CommandElements | Select-Object -Skip 1)) {
        if ($element.Extent.EndOffset -gt ($cursorPosition - $wordToComplete.Length)) { break }
        $candidate = ($path + ' ' + $element.Extent.Text).Trim()
        if (-not $commands.ContainsKey($candidate)) { break }
        $path = $candidate
    }
    $prefix = if ($path) { $path + ' ' } else { '' }
    $children = $commands.Keys | Where-Object { $_.StartsWith($prefix) -and $_ -ne $path } |
        ForEach-Object { $_.Substring($prefix.Length).Split(' ')[0] }
    ($children + ($commands[$path] -split ' ') + '--help') | Sort-Object -Unique |
        Where-Object { $_ -and $_.StartsWith($wordToComplete, [StringComparison]::OrdinalIgnoreCase) } |
        ForEach-Object { [System.Management.Automation.CompletionResult]::new($_) }
}
"#,
    );
    script
}

fn install_current_user(shell: &str, script: &str) -> io::Result<std::path::PathBuf> {
    let output = std::process::Command::new(shell)
        .args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); [Console]::Write($PROFILE.CurrentUserAllHosts)",
        ])
        .output()?;
    let path =
        std::path::PathBuf::from(String::from_utf8(output.stdout).map_err(io::Error::other)?);
    if !output.status.success() || !path.is_absolute() {
        return Err(io::Error::other(
            "Could not determine the PowerShell profile path.",
        ));
    }
    let parent = path
        .parent()
        .ok_or_else(|| io::Error::other("Missing profile directory."))?;
    std::fs::create_dir_all(parent)?;
    append_once(&path, script)?;
    Ok(path)
}

fn append_once(path: &std::path::Path, script: &str) -> io::Result<()> {
    use std::io::{Read, Write};

    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .append(true)
        .create(true)
        .open(path)?;
    file.lock()?;
    let mut current = Vec::new();
    file.read_to_end(&mut current)?;
    let block = format!("\r\n{}", script.replace('\n', "\r\n"));
    let (marker, block) = match current.get(..2) {
        Some([0xff, 0xfe]) => (
            utf16(MARKER, u16::to_le_bytes),
            utf16(&block, u16::to_le_bytes),
        ),
        Some([0xfe, 0xff]) => (
            utf16(MARKER, u16::to_be_bytes),
            utf16(&block, u16::to_be_bytes),
        ),
        _ => (MARKER.as_bytes().to_vec(), block.into_bytes()),
    };
    if !current.windows(marker.len()).any(|window| window == marker) {
        file.write_all(&block)?;
        file.sync_all()?;
    }
    Ok(())
}

fn utf16(text: &str, to_bytes: fn(u16) -> [u8; 2]) -> Vec<u8> {
    text.encode_utf16().flat_map(to_bytes).collect()
}

#[cfg(test)]
mod tests {
    use super::{append_once, script, utf16};

    #[test]
    fn completion_install_preserves_profile_encoding_and_is_idempotent() {
        let path =
            std::env::temp_dir().join(format!("studyflow-profile-{}.ps1", std::process::id()));
        let prefix = utf16("\u{feff}# existing profile\r\n", u16::to_le_bytes);
        std::fs::write(&path, &prefix).unwrap();
        let script = script();
        append_once(&path, &script).unwrap();
        let first = std::fs::read(&path).unwrap();
        append_once(&path, &script).unwrap();
        let second = std::fs::read(&path).unwrap();
        std::fs::remove_file(path).unwrap();
        assert!(first.starts_with(&prefix));
        assert!(first.ends_with(&utf16(&script.replace('\n', "\r\n"), u16::to_le_bytes)));
        assert_eq!(first, second);
    }
}
