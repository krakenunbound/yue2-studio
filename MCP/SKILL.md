# YuE2 Studio MCP

Use this MCP when an agent needs to work with the running YuE2 Studio desktop app without controlling its window. It speaks to the app's existing local service and every tool invocation is shown in the Studio **MCP** screen.

## Preconditions

- YuE2 Studio must be open and ready. The local service listens only on `127.0.0.1:7794`.
- Start with `studio_status`; do not queue generation when the service reports unavailable or another incompatible job is active.
- Treat song generation, cancellation, updates, ratings, playlists, profile creation, and effect generation as state-changing actions. Explain the intended action before invoking it when appropriate.

## Tool guide

Use `list_songs` before addressing a song, then pass its exact `folder_name` to `get_song`, `update_song`, or `rate_song`. Use `generate_song` to submit a normal YuE2 generation; it returns a job id, which should be followed with `get_job`. `cancel_job` only cancels an active job.

`write_song` is for the app's configured AI-writing capability; it does not generate audio. `voices` manages or compiles the Studio voice profiles. `effects` lists effects or queues a sound-effect job. `playlists` handles playlist listing and membership.

## Visibility and privacy

The MCP records the tool name, outcome, and a non-sensitive summary in the Studio MCP page. It never sends local Studio data outside the machine by itself. API keys remain inside YuE2 Studio's local vault and are never returned by this MCP.

Do not use browser or computer-control tools for normal YuE2 work once this MCP is connected. Use the Studio GUI only to let the user inspect connection status, live activity, generated jobs, and results.
