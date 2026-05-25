//! Tauri shell for the Maverick installer.
//!
//! Owns the window. All wizard logic lives in the Python sidecar
//! (`bridge.py`) which is the same code the `maverick init` CLI uses;
//! the shell just forwards Tauri invoke calls to it via stdin/stdout.
//!
//! This keeps the Rust footprint tiny (single binary, ~5 MB) while
//! sharing 100% of the wizard logic with the CLI.

use serde::{Deserialize, Serialize};
use std::process::Stdio;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::Command;
use tokio::sync::Mutex;

struct PythonSidecar {
    inner: Mutex<Option<tokio::process::Child>>,
}

#[derive(Serialize, Deserialize)]
struct WizardStep {
    id: String,
    question: String,
    choices: Vec<String>,
}

#[tauri::command]
async fn wizard_next(
    sidecar: tauri::State<'_, PythonSidecar>,
    answer: String,
) -> Result<WizardStep, String> {
    let mut guard = sidecar.inner.lock().await;
    let child = guard
        .as_mut()
        .ok_or_else(|| "sidecar not started".to_string())?;
    let stdin = child.stdin.as_mut().ok_or_else(|| "no stdin".to_string())?;
    stdin
        .write_all(format!("{}\n", answer).as_bytes())
        .await
        .map_err(|e| e.to_string())?;
    stdin.flush().await.map_err(|e| e.to_string())?;

    let stdout = child
        .stdout
        .as_mut()
        .ok_or_else(|| "no stdout".to_string())?;
    let mut reader = BufReader::new(stdout);
    let mut line = String::new();
    reader
        .read_line(&mut line)
        .await
        .map_err(|e| e.to_string())?;
    serde_json::from_str(&line).map_err(|e| format!("bad sidecar response: {e}"))
}

fn start_sidecar() -> Result<tokio::process::Child, String> {
    Command::new("python3")
        .args(["-m", "maverick_installer.bridge"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("failed to start Python sidecar: {e}"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let child = start_sidecar().expect("sidecar spawn failed");
    let sidecar = PythonSidecar {
        inner: Mutex::new(Some(child)),
    };
    tauri::Builder::default()
        .manage(sidecar)
        .invoke_handler(tauri::generate_handler![wizard_next])
        .run(tauri::generate_context!())
        .expect("tauri runtime error");
}

fn main() {
    run();
}
