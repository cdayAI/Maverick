# maverick-installer-desktop

Native Tauri GUI installer for users who never open a terminal.
Wraps the same `maverick_installer.wizard` logic the CLI uses, behind a
Svelte UI.

## Status: builds an unsigned bundle

The structural blockers are fixed — `pnpm tauri build` now produces a
bundle on all three platforms (see `.github/workflows/desktop.yml`).
What's done:

- `[[bin]]` target in `Cargo.toml`, logic split into `lib.rs` (run())
  + a thin `main.rs` — the standard Tauri v2 layout
- Tauri v2 `src-tauri/capabilities/default.json` allowlist (scoped to
  the `wizard_next` command + core window ops; no shell, no fs)
- A committed source icon at `src-tauri/icons/icon.png`; the CI step
  + local builds run `pnpm tauri icon` to generate the platform
  variants the bundler expects
- GitHub Actions matrix (`desktop.yml`) on macOS / Windows / Linux

**Two things still gate a consumer-grade release:**

1. **Embedded Python.** The sidecar shells out to the system Python
   (`python3` then `python`). A packaged bundle on a machine without
   Python surfaces a clear error in the UI instead of crashing — but
   it still won't *run* the wizard there. Bundling
   `python-build-standalone` is the fix (tracked separately; ~3-5 days).
2. **Code signing.** `desktop.yml` produces UNSIGNED bundles, which
   trip SmartScreen (Windows) and Gatekeeper (macOS). The signing
   secret placeholders are wired in the workflow; they activate once
   the Apple Developer Program / Azure Trusted Signing certs exist.

Until both land, the CLI wizard (`maverick init`) is the supported
install path. The desktop bundle is buildable for development +
internal testing.

## Local development

```bash
cd apps/installer-desktop
pnpm install
pnpm tauri dev
```

This starts the Tauri dev shell with hot-reload on the Svelte frontend
and the Python sidecar (`bridge.py`) reachable from the UI via Tauri's
invoke API.

## Producing native bundles

```bash
pnpm tauri build
```

Outputs (per platform):
- macOS: `.app` + `.dmg` (sign + notarize for distribution)
- Windows: `.exe` MSI installer + standalone executable
- Linux: `.AppImage` + `.deb`

## Why Tauri vs Electron

| | Tauri | Electron |
|---|---|---|
| Bundle size | ~5 MB | ~150 MB |
| Memory at idle | ~50 MB | ~250 MB |
| Native webview | system (WebKit / WebView2 / WebKitGTK) | bundled Chromium |
| Rust shell | yes (security, smaller attack surface) | no |

Maverick already needs Rust in the toolchain for the agent-shield
performance core, so adding Tauri is essentially free.

## Architecture

```
  +------------------+      Tauri invoke      +-------------------+
  | Svelte UI (TS)   | <--------------------> | Rust shell (main) |
  +------------------+                        +---------+---------+
                                                        |
                                                        | stdin/stdout JSON-RPC
                                                        v
                                              +-------------------+
                                              | bridge.py (sidecar) |
                                              | imports maverick    |
                                              | + maverick_installer|
                                              +-------------------+
```

The Rust shell handles window + IPC. Everything else (wizard
questions, config writes, API key validation) goes through the same
Python code the CLI wizard uses.
