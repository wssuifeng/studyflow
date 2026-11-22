use std::path::PathBuf;

use studyflow_core::courses::packages;

#[test]
fn parser_rejects_duplicate_fields_and_accepts_utf8_bom() {
    let payload = br#"{"schema":"studyflow.course-package/1","package_id":"sample","plan_line":"Test plan","course":{"title":"Lesson"},"lessons":[{"id":"intro","title":"Intro","blocks":[{"id":"start","type":"concept","title":"Start","body":"Plain sentence"}]}]}"#;
    let mut bytes = b"\xef\xbb\xbf".to_vec();
    bytes.extend_from_slice(payload);
    let package = packages::parse(&bytes).unwrap();
    assert_eq!(packages::inspect(&package).unwrap()["knowledge_total"], 1);
    let duplicate = br#"{"course":{"title":"one","title":"two"}}"#;
    let error = packages::parse(duplicate).unwrap_err();
    assert_eq!(error.field, "json");
    assert!(error.reason.contains("重复字段 title"));
    let over_limit = vec![b' '; 4 * 1024 * 1024 + 1];
    assert_eq!(packages::parse(&over_limit).unwrap_err().field, "file");
}

#[test]
#[ignore = "Requires W0.3 course fixture paths under STUDYFLOW_F2_PACKAGES"]
fn all_eight_course_revisions_accept_and_reject_old_fixtures() {
    let fixture_dir = PathBuf::from(std::env::var_os("STUDYFLOW_F2_PACKAGES").unwrap());
    for version in 1..=8 {
        let expect = format!("studyflow.course-package/{version}");
        let accepted =
            packages::read(&fixture_dir.join(format!("v{version}-accept.json"))).unwrap();
        assert_eq!(accepted["schema"], expect);
        let rejected =
            packages::read(&fixture_dir.join(format!("v{version}-reject.json"))).unwrap_err();
        assert!(!rejected.field.is_empty() && !rejected.reason.is_empty());
    }
}

#[test]
#[ignore = "Requires W2.2 old presentation and reference fixtures under STUDYFLOW_PRESENTATION_EVIDENCE"]
fn fallback_and_structured_lesson_projection_preserve_original_semantics() {
    use serde_json::Value;
    use studyflow_core::courses::presentation;
    let path = PathBuf::from(std::env::var_os("STUDYFLOW_PRESENTATION_EVIDENCE").unwrap());
    let fixtures: Vec<Value> = serde_json::from_slice(&std::fs::read(path).unwrap()).unwrap();
    assert_eq!(fixtures.len(), 12);
    for fixture in fixtures {
        if let Some(markdown) = fixture["fallback"].as_str() {
            assert_eq!(
                presentation::fallback_markdown(&fixture["lesson"]),
                markdown,
                "{}",
                fixture["fixture"]
            );
            for entry in fixture["exercise_checks"].as_array().unwrap() {
                let exercise = &entry["exercise"];
                let hash = presentation::question_fingerprint(exercise);
                assert_eq!(hash, entry["fingerprint"]);
                if let Some(expected) = entry["reference_hash"].as_str() {
                    assert_eq!(
                        presentation::reference_fingerprint(&exercise["review_reference"], &hash),
                        expected
                    );
                }
            }
        } else {
            let ids =
                serde_json::from_value::<Vec<String>>(fixture["exercise_ids"].clone()).unwrap();
            let markdown = fixture["document"].as_str().unwrap();
            let blocks = presentation::render_blocks(markdown, &ids).unwrap();
            let mut projected = serde_json::to_value(blocks).unwrap();
            let mut expected = fixture["projection"].clone();
            canonical_html(&mut projected);
            canonical_html(&mut expected);
            assert_eq!(projected, expected, "{}", fixture["fixture"]);
        }
    }
}

fn canonical_html(value: &mut serde_json::Value) {
    if let Some(fields) = value.as_object_mut() {
        for (key, data) in fields.iter_mut() {
            if key.ends_with("_html") {
                if let Some(html) = data.as_str() {
                    *data = html.trim_end().into();
                }
            } else {
                canonical_html(data);
            }
        }
    } else if let Some(items) = value.as_array_mut() {
        for item in items {
            canonical_html(item);
        }
    }
}
