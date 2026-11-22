use serde_json::{json, Value};

use crate::{
    audio::{
        assets::{Format, MAX_AUDIO_BYTES},
        duration::parse_wav,
    },
    infrastructure::StorageError,
};

use super::jobs::Segment;

pub(super) struct Dialogue {
    output: Vec<u8>,
    format: Vec<u8>,
    rate: u32,
    frames: usize,
    captions: Vec<Value>,
}

impl Dialogue {
    pub(super) fn new() -> Self {
        Self {
            output: Vec::new(),
            format: Vec::new(),
            rate: 0,
            frames: 0,
            captions: Vec::new(),
        }
    }

    pub(super) fn append(&mut self, bytes: &[u8], segment: &Segment) -> Result<(), StorageError> {
        let pcm = parse_wav(bytes)?;
        if self.output.is_empty() {
            self.format = pcm.format.to_owned();
            self.rate = pcm.rate;
            self.output.extend_from_slice(b"RIFF\0\0\0\0WAVEfmt ");
            self.output
                .extend_from_slice(&(self.format.len() as u32).to_le_bytes());
            self.output.extend_from_slice(&self.format);
            self.output
                .resize(self.output.len() + (self.format.len() & 1), 0);
            self.output.extend_from_slice(b"data\0\0\0\0");
        }
        if pcm.format != self.format || self.output.len() + pcm.frames.len() + 1 > MAX_AUDIO_BYTES {
            return Err(StorageError::new("INVALID_AUDIO"));
        }
        let start = self.frames as f64 / f64::from(self.rate);
        self.frames += pcm.frames.len() / pcm.frame_bytes;
        let end = self.frames as f64 / f64::from(self.rate);
        self.captions
            .push(json!({"start":start,"end":end,"text":segment.text}));
        self.output.extend_from_slice(pcm.frames);
        Ok(())
    }

    pub(super) fn finish(mut self) -> Result<(Vec<u8>, f64, Vec<Value>), StorageError> {
        if self.output.is_empty() {
            return Err(StorageError::new("INVALID_AUDIO"));
        }
        let header = 20 + self.format.len() + (self.format.len() & 1) + 8;
        let data_len = self.output.len() - header;
        if data_len & 1 != 0 {
            self.output.push(0);
        }
        let riff_len = self.output.len() - 8;
        self.output[4..8].copy_from_slice(&(riff_len as u32).to_le_bytes());
        self.output[header - 4..header].copy_from_slice(&(data_len as u32).to_le_bytes());
        let duration = Format::Wav.duration(&self.output)?;
        Ok((self.output, duration, self.captions))
    }
}
