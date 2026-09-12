# Model downloads — September 10, 2026

Built and tested the native `YuE2 Studio.exe`, SHA256 `5694D9AE1F0F28BC321CF1ABDE8A4612446F6B8FA43BDD6D78B95E1A77501BF2`. Download actions below were initiated through the executable's Models screen with Computer Use, not through direct API calls.

- Installed models are omitted. YuE2 and Demucs were absent initially; no required-model section appeared because YuE2 was already installed.
- Clicked Whisper Download and install. Observed progress for the 1,543 MB checkpoint, cancelled the running transfer, then clicked Download and install again. The server returned HTTP 206 and resumed the retained partial file. The model and runtime verification succeeded; the Whisper card disappeared.
- Clicked cover-art Download and install. The missing local SD 1.5 configuration files downloaded, the existing checkpoint was verified, and runtime imports succeeded. Its card disappeared. Separately loaded the actual cover pipeline with `local_files_only=True` and the installed configuration successfully; this check did not generate a new cover image.
- Only Stable Audio 3 remained. Clicked its download button without credentials. The publisher denied access; the app displayed instructions to open the model page, accept its terms, and provide a Hugging Face read token. Full sound-model installation and generation remain unverified without publisher access.
- Complete Python suite: 164 passed, 2 subtests passed. Tests include empty-body install requests, active-job exclusion, low disk space, checksum failures, atomic replacement, cancellation, HTTP range resume, credential redaction, and Windows CRLF-compatible Git identities.
- Native production build passed. No source files at `F:\MiniMaxM3` were modified. Local API-key vault and installation state remain excluded from Git.

The installer uses frozen upstream file revisions and content identities from `python/model_catalog.json`. Each feature has a separate user-initiated download, disk-space reserve, runtime setup, cancellation, retained partial downloads, and persisted failure state. Runtime download sizes are estimates. Existing runtimes are checked by imports during installation. English lyric alignment is included; other alignment languages may download on first sync, as explained on screen. Transcription fallback requires the explicitly installed local Whisper checkpoint.
