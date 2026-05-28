//! Tauri shell for the Maverick installer.
//!
//! Owns the window. All wizard logic lives in the Python sidecar
//! (`bridge.py`) which mirrors the CLI's consumer flow; the shell just
//! forwards Tauri invoke calls to it via stdin/stdout.
//!
//! This keeps the Rust footprint tiny (single binary, ~5 MB) while
//! sharing the wizard logic with the CLI.
//!
//! NOTE: until the embedded-Python work lands (tracked separately),
//! this spawns the system Python interpreter. A packaged bundle on a
//! machine without Python will surface a clear error in the UI rather
//! than crashing silently.

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
    #[serde(default)]
    kind: String,
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

/// Find a usable Python interpreter and start the sidecar.
///
/// Tries `python3` then `python` (Windows ships the launcher as
/// `python`). Returns an actionable error string if neither works, so
/// the UI can tell the user to install Python instead of crashing.
fn start_sidecar() -> Result<tokio::process::Child, String> {
    let candidates = ["python3", "python"];
    let mut last_err = String::new();
    for exe in candidates {
        match Command::new(exe)
            .args(["-m", "maverick_installer.bridge"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
        {
            Ok(child) => return Ok(child),
            Err(e) => last_err = format!("{exe}: {e}"),
        }
    }
    Err(format!(
        "Could not start Python (tried python3, python). Install Python 3.10+ \
         and the maverick-installer package, then relaunch. Last error: {last_err}"
    ))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Don't panic if Python is missing: hold None and let wizard_next
    // surface "sidecar not started" to the UI.
    let child = start_sidecar().ok();
    let sidecar = PythonSidecar {
        inner: Mutex::new(child),
    };
    tauri::Builder::default()
        .manage(sidecar)
        .invoke_handler(tauri::generate_handler![wizard_next])
        .run(tauri::generate_context!())
        .expect("tauri runtime error");
}
