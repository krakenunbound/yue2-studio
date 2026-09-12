# Local error logging

The existing desktop executable loads the Python backend from this project. On its next launch, errors and full tracebacks are written to `outputs/logs/studio.log`. The log rotates at 2 MB and retains three backups. Closing the app does not delete these files; recent records are restored to the Logs panel on startup, keeping multiline tracebacks attached to their error entry.

Worker failures are recorded at ERROR level with the complete Python traceback and CUDA allocator statistics when available. Gemini API keys and URL key parameters are redacted. The local credential vault is never included. All outputs remain excluded from Git.

Before acoustic synthesis, the worker saves the exact score, prefix, semantic tokens and local generation request under `outputs/recovery/<id>`. The log records the checkpoint path and token counts, followed by allocated/reserved GPU memory at each synthesis step. These local checkpoints allow a failure to be investigated without regenerating its musical input. They contain song text, so they should remain local.

Validation covers exception persistence after handler shutdown, recovery into the Logs panel including ERROR filtering, credential redaction, and readable worker error forwarding. Errors from sessions before this change cannot be recovered from the old memory-only logger.
