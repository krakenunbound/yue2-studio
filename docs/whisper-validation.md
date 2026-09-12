# Whisper lyric synchronization

Installed the copied setup's WhisperX 3.8.4 with CUDA PyTorch/torchaudio 2.8.0 in this app's independent `python/lyrics_runtime`. Copied the existing English alignment checkpoint into `models/lyrics/torch/hub/checkpoints`. MiniMax was read only; the alignment worker's SHA256 matches its source exactly.

The library menu now shows **Sync lyrics (Whisper)** for vocal songs with saved lyrics, even when the runtime is absent (disabled with the setup explanation). Previously the entire option disappeared. Rebuilt and installed the desktop EXE.

September 10, 2026: invoked the menu on Nemeton in the real desktop app. The job completed in 39 seconds with 31 timed lines, JSON, LRC and ASS output. The app showed `Timed lyrics ready`, and playback displayed the synchronized-lyrics panel. The worker exited after completion. The user began playback during the check, so the app was left under their control.

This reuses MiniMax's existing known-lyrics alignment workflow; it does not replace saved lyrics with newly invented text.
