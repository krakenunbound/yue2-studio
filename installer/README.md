# Windows installer

Build with `pwsh -File scripts/build-installer.ps1` from the repository root. A full CPython 3.11 installation, Node.js, Rust and the usual Tauri Windows build prerequisites are needed on the build machine only. The staging script discovers the base Python from the local sidecar environment, or accepts `-PythonHome`.

The setup executable is copied to `release/` with a SHA256 file. It installs for the current Windows user, supports choosing a writable destination, creates a Start menu shortcut, and creates empty directories for model downloads, songs, logs and local settings. WebView2 is installed if required; that step needs Internet access. The large feature models and runtimes remain explicit choices inside Models.

The payload is an allowlisted copy of application support files and a clean, relocatable Python distribution. `audit-installer.ps1` rejects the local vault/user-output paths and scans every payload file for the exact local Gemini key without printing it. Never add `outputs/`, model weights, or a developer virtual environment to the resource map.

Installer artwork was created with the built-in image generator. Source assets and installer-ready bitmaps are in `installer/art/`. Sidebar prompt: tall midnight-navy artwork with a restrained sculptural cyan-to-violet ribbon of sound, fine wave lines, no text or logo. Header prompt: matching wide cyan-to-violet wave ribbon on midnight navy, no text or logo. Bitmap conversion only resizes the generated images for the native installer.

The installer is unsigned unless a signing certificate is configured separately. The installer artwork does not imply Windows publisher verification.
