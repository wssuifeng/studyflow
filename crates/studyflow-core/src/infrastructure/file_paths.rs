use std::{fs, io, path::Path};

use super::StorageError;

pub fn portable_relative(value: &str) -> Result<(), StorageError> {
    let valid = !value.is_empty()
        && value.trim() == value
        && value.split('/').all(|part| {
            if part.is_empty()
                || part == "."
                || part == ".."
                || part.ends_with(['.', ' '])
                || part
                    .chars()
                    .any(|ch| ch.is_control() || "\\:<>\"|?*".contains(ch))
            {
                return false;
            }
            let stem = part
                .split('.')
                .next()
                .unwrap_or_default()
                .trim_end()
                .to_ascii_uppercase();
            !matches!(
                stem.as_str(),
                "CON" | "PRN" | "AUX" | "NUL" | "CONIN$" | "CONOUT$"
            ) && !["COM", "LPT"].iter().any(|prefix| {
                stem.strip_prefix(prefix).is_some_and(|tail| {
                    matches!(
                        tail,
                        "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9" | "¹" | "²" | "³"
                    )
                })
            })
        });
    if !valid {
        return Err(StorageError::new("BACKUP_PATH_INVALID"));
    }
    Ok(())
}

pub fn is_link(metadata: &fs::Metadata) -> bool {
    if metadata.file_type().is_symlink() {
        return true;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
        metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0
    }
    #[cfg(not(windows))]
    false
}

#[cfg(windows)]
pub fn available_bytes(directory: &Path) -> Result<u64, io::Error> {
    use std::{os::windows::ffi::OsStrExt, ptr};
    use windows_sys::Win32::Storage::FileSystem::GetDiskFreeSpaceExW;

    let mut path: Vec<u16> = directory.as_os_str().encode_wide().collect();
    path.push(0);
    let mut bytes = 0;
    // The path is a NUL-terminated wide string and bytes is writable.
    if unsafe { GetDiskFreeSpaceExW(path.as_ptr(), &mut bytes, ptr::null_mut(), ptr::null_mut()) }
        == 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(bytes)
}

#[cfg(unix)]
pub fn available_bytes(directory: &Path) -> Result<u64, io::Error> {
    use std::{ffi::CString, mem::MaybeUninit, os::unix::ffi::OsStrExt};
    let path = CString::new(directory.as_os_str().as_bytes())?;
    let mut data = MaybeUninit::<libc::statvfs>::uninit();
    // statvfs initializes the result when it succeeds.
    if unsafe { libc::statvfs(path.as_ptr(), data.as_mut_ptr()) } == -1 {
        return Err(io::Error::last_os_error());
    }
    let data = unsafe { data.assume_init() };
    Ok(u64::from(data.f_bavail).saturating_mul(u64::from(data.f_frsize)))
}

pub fn is_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

pub fn workspace_path(root: &Path, requested: &Path) -> Result<std::path::PathBuf, StorageError> {
    let root = super::config::absolute(root)?;
    let path = super::config::absolute(&root.join(super::config::expand_home(requested)?))?;
    relative_in_workspace(&path, &root)?;
    Ok(path)
}

pub(crate) fn relative_in_workspace(
    path: &Path,
    root: &Path,
) -> Result<std::path::PathBuf, StorageError> {
    #[cfg(windows)]
    let (path, root) = (comparison_path(path), comparison_path(root));
    path.strip_prefix(root)
        .map(Path::to_owned)
        .map_err(|error| StorageError::caused_by("PATH_OUTSIDE_WORKSPACE", error))
}

// A canonical short root can have descendants that require a verbatim prefix.
// Use a common prefix representation only for comparing resolved paths.
#[cfg(windows)]
fn comparison_path(path: &Path) -> std::borrow::Cow<'_, Path> {
    use std::path::{Component, PathBuf, Prefix};
    let mut parts = path.components();
    if let Some(Component::Prefix(prefix)) = parts.next() {
        let normal = match prefix.kind() {
            Prefix::VerbatimDisk(letter) => Some(format!("{}:", char::from(letter))),
            Prefix::VerbatimUNC(server, share) => {
                let mut unc = std::ffi::OsString::from(r"\\");
                unc.push(server);
                unc.push(r"\");
                unc.push(share);
                return std::borrow::Cow::Owned(
                    PathBuf::from(unc).join(
                        parts
                            .as_path()
                            .strip_prefix(r"\")
                            .unwrap_or(parts.as_path()),
                    ),
                );
            }
            _ => None,
        };
        if let Some(normal) = normal {
            return std::borrow::Cow::Owned(
                PathBuf::from(format!(r"{normal}\")).join(
                    parts
                        .as_path()
                        .strip_prefix(r"\")
                        .unwrap_or(parts.as_path()),
                ),
            );
        }
    }
    std::borrow::Cow::Borrowed(path)
}

pub fn write_if_absent(path: &Path, data: &[u8]) -> Result<bool, StorageError> {
    use std::io::Write;
    stage_and_publish(path, |file| file.write_all(data))
}

fn stage_and_publish(
    path: &Path,
    write: impl FnOnce(&mut fs::File) -> io::Result<()>,
) -> Result<bool, StorageError> {
    let parent = path
        .parent()
        .ok_or_else(|| StorageError::new("INVALID_WORKSPACE_PATH"))?;
    let staged = parent.join(format!(
        ".studyflow-write-{}.tmp",
        uuid::Uuid::new_v4().simple()
    ));
    let mut file = fs::File::create_new(&staged)?;
    let result = (|| {
        write(&mut file)?;
        file.sync_all()?;
        drop(file);
        match rename_new(&staged, path) {
            Ok(()) => Ok(true),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => Ok(false),
            Err(error) => Err(StorageError::from(error)),
        }
    })();
    let _ = fs::remove_file(staged);
    result
}

#[cfg(windows)]
fn rename_new(from: &Path, to: &Path) -> io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{MoveFileExW, MOVEFILE_WRITE_THROUGH};
    let wide = |path: &Path| {
        path.as_os_str()
            .encode_wide()
            .chain([0])
            .collect::<Vec<_>>()
    };
    // The system call needs verbatim paths when a workspace and a digest
    // addressed filename together exceed MAX_PATH.
    let parent = |path: &Path| -> io::Result<std::path::PathBuf> {
        let dir = path.parent().ok_or(io::ErrorKind::InvalidInput)?;
        let name = path.file_name().ok_or(io::ErrorKind::InvalidInput)?;
        Ok(fs::canonicalize(dir)?.join(name))
    };
    let from = wide(&parent(from)?);
    let to = wide(&parent(to)?);
    // No replace flag. A concurrent publisher's file remains intact.
    if unsafe { MoveFileExW(from.as_ptr(), to.as_ptr(), MOVEFILE_WRITE_THROUGH) } == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

#[cfg(unix)]
fn rename_new(from: &Path, to: &Path) -> io::Result<()> {
    fs::hard_link(from, to)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn interrupted_asset_write_leaves_no_visible_reference_or_temporary_file() {
        let root = std::env::temp_dir().join(format!("studyflow-publish-{}", uuid::Uuid::new_v4()));
        fs::create_dir(&root).unwrap();
        let destination = root.join("asset.wav");
        let error = stage_and_publish(&destination, |file| {
            file.write_all(b"partial")?;
            assert!(!destination.exists());
            Err(io::Error::from(io::ErrorKind::WriteZero))
        });
        assert!(error.is_err());
        assert_eq!(root.read_dir().unwrap().count(), 0);
        assert!(write_if_absent(&destination, b"complete").unwrap());
        assert_eq!(fs::read(&destination).unwrap(), b"complete");
        fs::remove_file(destination).unwrap();
        fs::remove_dir(root).unwrap();
    }
}
