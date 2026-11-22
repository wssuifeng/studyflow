use rusqlite::{params, Connection, OptionalExtension};

use crate::infrastructure::StorageError;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Track {
    Main,
    Supplement,
}

impl Track {
    fn key(self) -> &'static str {
        match self {
            Self::Main => "MAIN",
            Self::Supplement => "SUPPLEMENT",
        }
    }
}

/// Call within the transaction that attaches or publishes a course.
pub fn ensure_membership(
    db: &Connection,
    plan_id: &str,
    course_id: &str,
    track: Track,
) -> Result<String, StorageError> {
    let existing = db
        .query_row(
            "SELECT id FROM plan_course_items WHERE plan_line_id=? AND course_id=?",
            params![plan_id, course_id],
            |row| row.get::<_, String>(0),
        )
        .optional()?;
    if let Some(id) = existing {
        return Ok(id);
    }
    let id = uuid::Uuid::new_v4().to_string();
    db.execute(
        "INSERT INTO plan_course_items(id,plan_line_id,course_id,sequence_number,status,track,management_position,management_reason)
         SELECT ?,?,?,COALESCE(MAX(sequence_number),0)+1,'PLANNED',?,'NORMAL',''
         FROM plan_course_items WHERE plan_line_id=? AND track=?",
        params![id,plan_id,course_id,track.key(),plan_id,track.key()],
    )?;
    Ok(id)
}
