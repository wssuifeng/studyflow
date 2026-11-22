//! Shared application services for StudyFlow's native runtime.

pub const APP_VERSION: &str = env!("CARGO_PKG_VERSION");
pub mod application;
pub mod audio;
pub mod authoring;
pub mod courses;
pub mod documents;
pub mod infrastructure;
pub mod learning;
pub mod mistakes;
pub mod planning;
pub mod reviews;
pub mod speech_generation;
pub mod workspace;
