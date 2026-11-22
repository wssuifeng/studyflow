use std::fs::{self, File, OpenOptions};
use std::io;
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};

use super::{config, StorageError};

pub struct Lease {
    file: File,
}

impl Lease {
    pub fn shared(root: &Path) -> Result<Self, StorageError> {
        Self::acquire(root, false)
    }

    pub fn exclusive(root: &Path) -> Result<Self, StorageError> {
        Self::acquire(root, true)
    }

    fn acquire(root: &Path, exclusive: bool) -> Result<Self, StorageError> {
        Self::acquire_file(&lock_path(root)?, exclusive, "WORKSPACE_MAINTENANCE_BUSY")
    }

    pub(crate) fn exclusive_file(
        path: &Path,
        busy_code: &'static str,
    ) -> Result<Self, StorageError> {
        Self::acquire_file(path, true, busy_code)
    }

    fn acquire_file(
        path: &Path,
        exclusive: bool,
        busy_code: &'static str,
    ) -> Result<Self, StorageError> {
        fs::create_dir_all(
            path.parent()
                .ok_or_else(|| StorageError::new("INVALID_WORKSPACE_PATH"))?,
        )?;
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(path)?;
        lock(&file, exclusive).map_err(|error| StorageError::caused_by(busy_code, error))?;
        // Closing the descriptor releases the advisory lock. Keep the stable
        // sibling lock file so a rename/restore cannot split the lock identity.
        Ok(Self { file })
    }
}

impl Drop for Lease {
    fn drop(&mut self) {
        unlock(&self.file);
    }
}

pub fn lock_path(root: &Path) -> Result<PathBuf, StorageError> {
    let root = config::absolute(root)?;
    let parent = root
        .parent()
        .ok_or_else(|| StorageError::new("INVALID_WORKSPACE_PATH"))?;
    let raw = root
        .to_str()
        .ok_or_else(|| StorageError::new("INVALID_WORKSPACE_PATH"))?;
    #[cfg(windows)]
    let normalized = windows_normcase(raw)?;
    #[cfg(not(windows))]
    let normalized = raw;
    let digest = format!("{:x}", Sha256::digest(normalized.as_bytes()));
    Ok(parent.join(format!(".studyflow-{}.lease", &digest[..24])))
}

#[cfg(windows)]
fn windows_normcase(path: &str) -> Result<String, StorageError> {
    use std::ptr;
    use windows_sys::Win32::Globalization::{
        LCMapStringEx, LCMAP_LOWERCASE, LOCALE_NAME_INVARIANT,
    };

    let source: Vec<u16> = path.replace('/', "\\").encode_utf16().collect();
    let length =
        i32::try_from(source.len()).map_err(|_| StorageError::new("INVALID_WORKSPACE_PATH"))?;
    let map = |destination, capacity| unsafe {
        LCMapStringEx(
            LOCALE_NAME_INVARIANT,
            LCMAP_LOWERCASE,
            source.as_ptr(),
            length,
            destination,
            capacity,
            ptr::null(),
            ptr::null(),
            0,
        )
    };
    let required = map(ptr::null_mut(), 0);
    if required == 0 {
        return Err(StorageError::caused_by(
            "INVALID_WORKSPACE_PATH",
            io::Error::last_os_error(),
        ));
    }
    let mut buffer = vec![0; required as usize];
    if map(buffer.as_mut_ptr(), required) != required {
        return Err(StorageError::caused_by(
            "INVALID_WORKSPACE_PATH",
            io::Error::last_os_error(),
        ));
    }
    String::from_utf16(&buffer)
        .map_err(|error| StorageError::caused_by("INVALID_WORKSPACE_PATH", error))
}

#[cfg(windows)]
fn lock(file: &File, exclusive: bool) -> io::Result<()> {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Storage::FileSystem::{
        LockFileEx, LOCKFILE_EXCLUSIVE_LOCK, LOCKFILE_FAIL_IMMEDIATELY,
    };
    use windows_sys::Win32::System::IO::OVERLAPPED;

    let mut overlap = OVERLAPPED::default();
    let flags = LOCKFILE_FAIL_IMMEDIATELY
        | if exclusive {
            LOCKFILE_EXCLUSIVE_LOCK
        } else {
            0
        };
    // Same offset and one-byte range as the 1.8.27 Python runtime.
    let success = unsafe { LockFileEx(file.as_raw_handle(), flags, 0, 1, 0, &mut overlap) };
    if success == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

#[cfg(unix)]
fn lock(file: &File, exclusive: bool) -> io::Result<()> {
    use std::os::fd::AsRawFd;
    let flags = libc::LOCK_NB
        | if exclusive {
            libc::LOCK_EX
        } else {
            libc::LOCK_SH
        };
    if unsafe { libc::flock(file.as_raw_fd(), flags) } != 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

#[cfg(windows)]
fn unlock(file: &File) {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::Storage::FileSystem::UnlockFileEx;
    use windows_sys::Win32::System::IO::OVERLAPPED;
    let mut overlap = OVERLAPPED::default();
    unsafe {
        UnlockFileEx(file.as_raw_handle(), 0, 1, 0, &mut overlap);
    }
}

#[cfg(unix)]
fn unlock(file: &File) {
    use std::os::fd::AsRawFd;
    unsafe {
        libc::flock(file.as_raw_fd(), libc::LOCK_UN);
    }
}
