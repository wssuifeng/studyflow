use crate::infrastructure::StorageError;

pub(crate) struct Pcm<'a> {
    pub(crate) format: &'a [u8],
    pub(crate) frames: &'a [u8],
    pub(crate) frame_bytes: usize,
    pub(crate) rate: u32,
}

pub fn wav(data: &[u8]) -> Result<f64, StorageError> {
    let pcm = parse_wav(data)?;
    Ok(rounded(
        (pcm.frames.len() / pcm.frame_bytes) as f64 / f64::from(pcm.rate),
    ))
}

pub(crate) fn parse_wav(data: &[u8]) -> Result<Pcm<'_>, StorageError> {
    let err = || StorageError::new("INVALID_AUDIO");
    if data.len() < 12 || &data[..4] != b"RIFF" || &data[8..12] != b"WAVE" {
        return Err(err());
    }
    let end = 8 + le_u32(&data[4..8]) as usize;
    if end > data.len() || end < 12 {
        return Err(err());
    }
    let mut offset = 12;
    let mut pcm = None;
    while offset + 8 <= end {
        let key = &data[offset..offset + 4];
        let length = le_u32(&data[offset + 4..offset + 8]) as usize;
        let start = offset + 8;
        let stop = start
            .checked_add(length)
            .filter(|&end_of_chunk| end_of_chunk <= end)
            .ok_or_else(err)?;
        let bytes = &data[start..stop];
        if key == b"fmt " {
            let (frame_bytes, rate) = wav_format(bytes).ok_or_else(err)?;
            pcm = Some((bytes, frame_bytes, rate));
        }
        if key == b"data" {
            let (format, frame_bytes, rate) = pcm.ok_or_else(err)?;
            let frames = length / frame_bytes;
            if frames == 0 {
                return Err(err());
            }
            return Ok(Pcm {
                format,
                frames: &bytes[..frames * frame_bytes],
                frame_bytes,
                rate,
            });
        }
        offset = stop + (length & 1);
    }
    Err(err())
}

fn wav_format(bytes: &[u8]) -> Option<(usize, u32)> {
    const PCM_GUID: [u8; 16] = [1, 0, 0, 0, 0, 0, 16, 0, 128, 0, 0, 170, 0, 56, 155, 113];
    if bytes.len() < 16 {
        return None;
    }
    let code = le_u16(&bytes[..2]);
    if code != 1 && (code != 0xfffe || bytes.get(24..40) != Some(&PCM_GUID)) {
        return None;
    }
    let channels = usize::from(le_u16(&bytes[2..4]));
    let rate = le_u32(&bytes[4..8]);
    let width = usize::from(le_u16(&bytes[14..16])).div_ceil(8);
    (channels > 0 && rate > 0 && width > 0).then_some((channels * width, rate))
}

pub fn mp3(data: &[u8]) -> Result<f64, StorageError> {
    const BITRATE_V1: [usize; 14] = [
        32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320,
    ];
    const BITRATE_OTHER: [usize; 14] = [8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160];
    const FREQUENCIES: [usize; 3] = [44_100, 48_000, 32_000];
    let mut offset = 0;
    if data.starts_with(b"ID3") && data.len() >= 10 && data[6..10].iter().all(|&byte| byte < 128) {
        let tag_size = data[6..10]
            .iter()
            .fold(0usize, |value, &byte| (value << 7) | usize::from(byte));
        offset = 10
            + tag_size
            + if data[3] == 4 && data[5] & 16 != 0 {
                10
            } else {
                0
            };
    }
    let end = data
        .len()
        .checked_sub(128)
        .filter(|&tag| data.get(tag..tag + 3) == Some(b"TAG"))
        .unwrap_or(data.len());
    let mut frames = 0;
    let mut duration = 0.0;
    while offset + 4 <= end {
        let first = data[offset];
        let second = data[offset + 1];
        let third = data[offset + 2];
        let version = (second >> 3) & 3;
        let layer = (second >> 1) & 3;
        let rate_index = usize::from((third >> 2) & 3);
        let bitrate_index = usize::from(third >> 4);
        if first != 255
            || second & 224 != 224
            || version == 1
            || layer != 1
            || rate_index >= 3
            || !(1..=14).contains(&bitrate_index)
        {
            break;
        }
        let divisor = match version {
            3 => 1,
            2 => 2,
            _ => 4,
        };
        let rate = FREQUENCIES[rate_index] / divisor;
        let (samples, bitrate) = if version == 3 {
            (1152, BITRATE_V1[bitrate_index - 1])
        } else {
            (576, BITRATE_OTHER[bitrate_index - 1])
        };
        let padding = usize::from((third >> 1) & 1);
        offset += samples * bitrate * 1000 / (8 * rate) + padding;
        duration += samples as f64 / rate as f64;
        frames += 1;
    }
    if frames < 2 || offset != end {
        return Err(StorageError::new("INVALID_AUDIO"));
    }
    Ok(rounded(duration))
}

fn rounded(value: f64) -> f64 {
    (value * 1000.0).round_ties_even() / 1000.0
}

fn le_u16(bytes: &[u8]) -> u16 {
    u16::from_le_bytes(bytes.try_into().expect("two bytes"))
}
fn le_u32(bytes: &[u8]) -> u32 {
    u32::from_le_bytes(bytes.try_into().expect("four bytes"))
}
