# maverick-installer-desktop (planned)

Native GUI installer for users who never open a terminal. The wizard's
logic lives in the Python core; this app is a Tauri shell that calls
into it via a small IPC bridge and renders a friendly UI.

## Why Tauri

- Single Rust binary; no Electron-sized bundles (~5 MB vs ~150 MB)
- Cross-platform: macOS (notarized DMG), Windows (signed MSIX), Linux (AppImage)
- The Maverick core already ships a Rust hot-path via `agent-shield`'s
  `rust-core/`, so Rust is in the toolchain regardless.
- Web frontend (Svelte/Solid) for the wizard UI — cheap to iterate.

## Status

Stub. Code lands next session. The plan:

```
apps/installer-desktop/
  src-tauri/         Tauri Rust shell (window, IPC)
  src/               Svelte frontend (the wizard UI)
  bridge.py          Python sidecar process that the shell calls
  package.json       pnpm workspace member
  tauri.conf.json    bundle config (icons, signing, updater)
```

The `bridge.py` is a thin wrapper around
`maverick_installer.wizard` that exposes the same steps as JSON-RPC
over stdio, so the GUI and CLI stay in lockstep.

## Distribution

| Platform | Format | Auto-update |
|---|---|---|
| macOS | Notarized DMG, signed | Sparkle via Tauri updater |
| Windows | Signed MSIX | Tauri updater |
| Linux | AppImage + .deb + .rpm | AppImageUpdate |

Releases ship from GitHub Actions on every tag.
