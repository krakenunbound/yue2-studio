# Windows synthesis memory fix

The Windows PyTorch build can use a math attention fallback during acoustic synthesis. YuE2 0.1.5 defaults to processing all query rows together on CUDA, causing a large temporary attention allocation for longer sequences. Raising the app's memory allowance would not address this scaling problem.

`python/yue2_memory.py` calls the published acoustic solver with `query_chunk_size=256`. Each query batch still sees the full applicable key/value sequence. The release solver, seed, context, codec tokens, generation steps, causal offsets, cancellation and prefix validation are preserved. No model weights or installed package files are modified. The worker also reports synthesis step progress.

The unsupported Windows `expandable_segments` default is no longer added by the controller. Existing user-supplied allocator environment settings are preserved.

## Validation

- Regression suite after persistent logging changes: 144 tests passed.
- Numerical comparison: tiled and untiled attention match within float32 tolerances, including causal block offsets and grouped-query heads.
- Adapter checks: full token sequence, seed, 32-step setting, cancellation and invalid-prefix rejection are preserved.
- RTX 3090 full-model stress fixture: 3,642 prefix tokens plus 9,000 synthetic music tokens; synthesis and stereo decoding completed, yielding approximately 360 seconds of audio shape. Peak PyTorch allocated VRAM was 9.63 GiB under the same 19.6 GiB cap. PyTorch reserved memory and total device usage can be higher than allocated memory.
- The initial stress fixture used two midpoint steps. A subsequent full 32-step run also completed synthesis and stereo decoding with the same 9.63 GiB allocated peak in 654.7 seconds. Synthetic token output is a memory test, not a musical quality evaluation or proof of the desktop workflow.

Reproduce using `python/runtime/Scripts/python.exe scripts/check_yue2_memory.py --gpu` with no competing generation. Results are recorded in `docs/memory-validation.json`.

Add `--full` for the 32-step run, recorded in `docs/memory-validation-full.json`. The user's later OOM did not leave a traceback in the old memory-only logger; its precise cause has not been established. Persistent logs and exact pre-synthesis checkpoints now retain the evidence needed to diagnose such a failure. See `logging.md`.

The desktop executable loads the worker from this folder. After a failed job the worker is terminated; the next attempt loads the patched worker. Restarting the app also loads the updated controller settings.
