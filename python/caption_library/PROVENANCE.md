# Caption library provenance

The `references/` and `templates/` folders in this directory are vendored verbatim
from MiniMax's official `music-caption-rewriter` agent skill:

  https://github.com/MiniMax-AI/MiniMax-Music3/tree/main/skills/music-caption-rewriter

`UPSTREAM_SKILL.md` is the upstream SKILL.md, kept for reference. MiniMax Music 3
Studio does not execute it as a skill; `python/caption_library.py` implements the
same progressive-disclosure routing locally in Python so the app can pick 1-3
matching reference captions without shipping the whole library to an LLM.

Contents: 19 family index files + genre-router.md, and 1000 complete structured
caption templates.

Check the upstream repository for its current license terms before redistributing
this app publicly.
