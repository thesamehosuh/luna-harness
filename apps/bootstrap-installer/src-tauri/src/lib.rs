//! Luna’s thin dashboard launcher, adapted from the vendored Hermes Tauri bootstrap.
mod launcher;
#[allow(dead_code)]
mod events;
#[allow(dead_code)]
mod powershell;
pub use launcher::run;
