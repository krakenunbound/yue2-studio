# Third-party notices

YuE2 Studio uses the following third-party components. The Windows installer includes CPython and the basic application service. Model weights and GPU feature runtimes are downloaded separately when selected in Models.

| Component | Source | Notes |
|---|---|---|
| CPython | https://www.python.org/ | The bundled distribution includes its LICENSE.txt. |
| Tauri | https://github.com/tauri-apps/tauri | Native Windows host; MIT / Apache-2.0. |
| React | https://github.com/facebook/react | Application interface; MIT. |
| FastAPI, Starlette, Uvicorn, HTTPX | https://github.com/fastapi/fastapi | Local application service; their package license files are included with the bundled Python packages. |
| imageio-ffmpeg / FFmpeg | https://github.com/imageio/imageio-ffmpeg | Local media conversion; bundled distribution notices accompany the Python package. |
| Demucs | https://github.com/facebookresearch/demucs | MIT-licensed local GPU source separation; the optional `htdemucs` checkpoint is stored under `models/stems/`. |

YuE2, Whisper, Stable Diffusion and Stable Audio downloads retain their respective publishers' terms. Downloading Stable Audio requires publisher access. No Gemini key, Hugging Face token, personal library, or developer settings are included in the installer.

This document is a navigation aid, not a replacement for the component's upstream license terms.
