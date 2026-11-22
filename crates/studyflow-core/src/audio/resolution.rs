use rusqlite::{params, OptionalExtension};
use serde::Serialize;
use serde_json::Value;

use crate::{infrastructure::StorageError, learning::english_check, workspace::Workspace};

use super::dictionary::{DictionaryProvider, Entry};

pub struct FrozenPronunciation {
    reference: Value,
    accepted: Option<String>,
}

#[derive(Serialize)]
pub struct Pronunciation {
    #[serde(flatten)]
    entry: Entry,
    course_gloss: String,
    whole_sentence: bool,
}

impl FrozenPronunciation {
    pub fn read(
        workspace: &Workspace,
        session: &str,
        exercise: &str,
    ) -> Result<Self, StorageError> {
        if session.trim().is_empty() || exercise.trim().is_empty() {
            return Err(StorageError::new("INVALID_ARGUMENT"));
        }
        let mut connection = workspace.inspect()?;
        let tx = connection.transaction()?;
        let snapshot: String = tx
            .query_row(
                "SELECT snapshot_json FROM course_study_sessions WHERE id=?",
                [session],
                |row| row.get(0),
            )
            .optional()?
            .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))?;
        let snapshot: Value = serde_json::from_str(&snapshot)
            .map_err(|error| StorageError::caused_by("DATABASE_ERROR", error))?;
        let reference = frozen_reference(&snapshot, exercise)?;
        let answer: Option<String> = tx.query_row(
            "SELECT answer_text FROM submissions WHERE study_session_id=? AND exercise_id=? AND retest_task_id IS NULL ORDER BY attempt_number DESC, created_at DESC, id DESC LIMIT 1",
            params![session, exercise],
            |row| row.get(0),
        ).optional()?;
        let accepted = match answer {
            Some(answer) => english_check::matched_variant(&reference, &answer)?.map(str::to_owned),
            None => None,
        };
        Ok(Self {
            reference,
            accepted,
        })
    }

    pub fn lookup(
        &self,
        provider: &DictionaryProvider,
        accent: &str,
        word_index: Option<usize>,
    ) -> Result<Pronunciation, StorageError> {
        let target = self.target();
        let words = english_check::tokens(target);
        let word = match word_index {
            Some(index) => words
                .get(index)
                .map(String::as_str)
                .ok_or_else(|| StorageError::new("INVALID_ARGUMENT"))?,
            None => target,
        };
        let mut entry = provider.lookup(
            word,
            accent,
            (word_index.is_some() || words.len() == 1).then_some(word),
        )?;
        let note = word_index.and_then(|index| self.note(index));
        let phonetic = if word_index.is_some() && words.len() > 1 {
            note.and_then(|item| item["phonetic"].as_str())
        } else {
            self.reference["phonetic"].as_str()
        };
        entry.use_course_phonetic(phonetic.unwrap_or_default());
        let gloss = match word_index {
            Some(_) => note.and_then(|item| item["gloss"].as_str()),
            None => self.reference["gloss"].as_str(),
        };
        Ok(Pronunciation {
            entry,
            course_gloss: gloss.unwrap_or_default().to_owned(),
            whole_sentence: word_index.is_none() && words.len() > 1,
        })
    }

    pub fn metadata(
        &self,
        provider: &DictionaryProvider,
        accent: &str,
    ) -> Result<Value, StorageError> {
        use serde_json::json;
        let target = self.target();
        let mut words = Vec::new();
        for (index, word) in english_check::tokens(target).into_iter().enumerate() {
            let entry = json!(provider.lookup(&word, accent, Some(&word))?);
            words.push(json!({
                "word_index": index, "word": word,
                "phonetic": entry["phonetic"], "definitions": entry["definitions"],
                "metadata_status": entry["metadata_status"], "definition_provider": entry["definition_provider"],
                "accent_verified": entry["accent_verified"],
            }));
        }
        Ok(
            json!({"target": target, "words": words, "requested_accent": accent, "sentence_transcription": false}),
        )
    }

    fn target(&self) -> &str {
        self.accepted
            .as_deref()
            .unwrap_or_else(|| self.reference["target"].as_str().unwrap_or_default())
    }

    fn note(&self, index: usize) -> Option<&Value> {
        if self
            .accepted
            .as_deref()
            .is_some_and(|accepted| self.reference["target"] != accepted)
        {
            return None;
        }
        self.reference["sentence_parts"]
            .as_array()?
            .iter()
            .find_map(|part| {
                let start = part["start"].as_u64()? as usize;
                let end = part["end"].as_u64()? as usize;
                (start..end)
                    .contains(&index)
                    .then(|| &part["words"][index - start])
            })
    }
}

fn frozen_reference(snapshot: &Value, exercise: &str) -> Result<Value, StorageError> {
    if snapshot["course"]["learning_mode"] != "english" {
        return Err(StorageError::new("COURSE_MODE_MISMATCH"));
    }
    snapshot["lessons"]
        .as_array()
        .into_iter()
        .flatten()
        .flat_map(|lesson| lesson["exercises"].as_array().into_iter().flatten())
        .find(|item| item["id"] == exercise)
        .and_then(|item| item.get("english"))
        .filter(|spec| spec["target"].as_str().is_some())
        .cloned()
        .ok_or_else(|| StorageError::new("OBJECT_NOT_FOUND"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn frozen_word_uses_course_note_and_metadata_keeps_word_positions() {
        let provider =
            DictionaryProvider::with_fetch(|_| Err(StorageError::new("FIXTURE_OFFLINE")));
        let mut frozen = FrozenPronunciation {
            reference: json!({"target":"Wait here!", "sentence_parts":[
                {"start":0,"end":2,"words":[{"phonetic":"weɪt","gloss":"等待"},{"gloss":"这里"}]}
            ]}),
            accepted: None,
        };
        let word = json!(frozen.lookup(&provider, "en-GB", Some(0)).unwrap());
        assert_eq!(word["target"], "Wait");
        assert_eq!(word["course_gloss"], "等待");
        assert_eq!(word["phonetic"], "weɪt");
        assert_eq!(word["whole_sentence"], false);
        let data = frozen.metadata(&provider, "en-GB").unwrap();
        assert_eq!(data["words"][1]["word"], "here");
        assert_eq!(data["words"][1]["word_index"], 1);
        assert_eq!(data["requested_accent"], "en-GB");
        assert_eq!(data["sentence_transcription"], false);
        frozen.accepted = Some("Stay here.".into());
        let word = json!(frozen.lookup(&provider, "en-GB", Some(0)).unwrap());
        assert_eq!(word["target"], "Stay");
        assert_eq!(word["course_gloss"], "");
        assert!(frozen.lookup(&provider, "en-GB", Some(2)).is_err());
    }
}
