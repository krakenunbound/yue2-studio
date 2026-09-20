# Local Effects uploads — 2026-09-15

Effects now offers **Upload your own sound** alongside generation. Choose a local audio file, edit its name, and save it to the Effects library. Imports require no AI model.

Supported inputs: WAV, MP3, FLAC, M4A, AAC, OGG, OPUS and WebM, up to 512 MiB. The original remains unchanged. Each import stores a copy under `outputs/effects/<unique-id>/source.<extension>`, a playable stereo 44.1 kHz PCM WAV, and detected duration/audio metadata. Invalid or incomplete imports are cleaned up and never published in the library.

The desktop file picker streams the file to the local service without encoding the whole file in JSON. Browser mode uses a binary request. Add to Studio places the full-length clip on the shared Effects lane while preserving existing session tracks.

## Verification

- Full Python suite: 288 tests and 10 subtests passed.
- Native Rust tests: 3 passed, including exact binary transfer, Unicode naming, invalid files, and filenames containing dots.
- Production desktop build passed; installed `YuE2 Studio.exe` hash matches the release build. Previous executable preserved under `outputs/effects-upload-qa/`.
- Real HTTP import of a 3.25-second WAV preserved source bytes and detected duration correctly. WAV and MP3 conversion also covered by automated tests.
- Browser UI verified imported name, duration, preview playback state, Add to Studio, and the loaded 0:00.00–0:03.25 clip on the Effects lane.
- Browser file chooser automation was blocked by the extension's file URL permission. Native picker interaction was not automated end to end; its validation and binary transport were tested separately.

QA used an isolated library under `outputs/effects-upload-qa/fixture`, not the user's songs.
