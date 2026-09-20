# YuE2 Studio MCP

This folder contains a local stdio MCP server for YuE2 Studio. It does not automate the desktop window. Instead it calls the Studio's loopback service and reports each action back to the app's visible **MCP** page.

The installed Codex entry uses `python/venv/Scripts/python.exe` and `MCP/server.py`. Open YuE2 Studio before calling a tool. Set `YUE2_STUDIO_URL` only if you intentionally moved the local service.

Available tools cover status, songs, generation and jobs, song editing and ratings, playlists, voice profiles, AI writing, and sound effects. See `SKILL.md` for agent behavior and safety guidance.
