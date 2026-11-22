use super::StorageError;

#[cfg(windows)]
pub(crate) fn dpapi(bytes: &[u8], decrypt: bool) -> Result<Vec<u8>, StorageError> {
    use std::{
        ptr::{null, null_mut},
        slice,
    };
    use windows_sys::Win32::{
        Foundation::LocalFree,
        Security::Cryptography::{
            CryptProtectData, CryptUnprotectData, CRYPTPROTECT_UI_FORBIDDEN, CRYPT_INTEGER_BLOB,
        },
    };

    let unavailable = || StorageError::new("KEY_STORE_UNAVAILABLE");
    let input = CRYPT_INTEGER_BLOB {
        cbData: u32::try_from(bytes.len()).map_err(|_| unavailable())?,
        pbData: bytes.as_ptr().cast_mut(),
    };
    let mut output = CRYPT_INTEGER_BLOB::default();
    // DPAPI owns the output allocation. Neither call mutates the input bytes.
    let ok = unsafe {
        if decrypt {
            CryptUnprotectData(
                &input,
                null_mut(),
                null(),
                null(),
                null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        } else {
            CryptProtectData(
                &input,
                null(),
                null(),
                null(),
                null(),
                CRYPTPROTECT_UI_FORBIDDEN,
                &mut output,
            )
        }
    };
    if ok == 0 || output.pbData.is_null() {
        return Err(unavailable());
    }
    let data = unsafe {
        let data = slice::from_raw_parts(output.pbData, output.cbData as usize).to_vec();
        if decrypt {
            for index in 0..output.cbData as usize {
                output.pbData.add(index).write_volatile(0);
            }
        }
        LocalFree(output.pbData.cast());
        data
    };
    Ok(data)
}

#[cfg(not(windows))]
pub(crate) fn dpapi(_: &[u8], _: bool) -> Result<Vec<u8>, StorageError> {
    Err(StorageError::new("KEY_STORE_UNAVAILABLE"))
}
