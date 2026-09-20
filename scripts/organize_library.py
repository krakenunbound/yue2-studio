"""Retitle genre-named songs and group the YuE2 library by genre.

The script is intentionally explicit: it creates a plan first and only moves
files when invoked with --apply. Existing audio, lyrics, covers, stems, and
studio data stay inside each song directory.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "outputs" / "library"
PLAN_PATH = ROOT / "outputs" / "library-organization-manifest.json"


def safe_stem(value: str, fallback: str = "song") -> str:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "-", value.strip()).strip(" .")[:120]
    return stem or fallback


def genre_folder(genre: str) -> str:
    return safe_stem(genre.strip() or "Uncategorized", "Uncategorized")


def clean_title(value: str) -> str:
    value = re.sub(r"^(?:title\s*:\s*)", "", str(value or ""), flags=re.I)
    value = re.sub(r"\s+", " ", value).strip(" .\"'")
    return safe_stem(value, "Untitled Song")[:120]


def lyric_fallback(metadata: dict[str, Any]) -> str:
    lyrics = str(metadata.get("lyrics") or "")
    section = ""
    candidates: list[tuple[int, str]] = []
    for raw in lyrics.splitlines():
        line = raw.strip()
        if not line:
            continue
        tag = re.fullmatch(r"\[([^]]+)\]", line)
        if tag:
            section = tag.group(1).casefold()
            continue
        words = re.findall(r"[\w'’-]+", line, flags=re.UNICODE)
        if not 2 <= len(words) <= 9:
            continue
        score = 2 if section in {"chorus", "refrain", "hook", "pre-chorus"} else 0
        if any(word.casefold() in {"the", "and", "that", "with", "just"} for word in words):
            score += 1
        candidates.append((score * 100 + len(words), line))
    if candidates:
        return clean_title(max(candidates, key=lambda item: item[0])[1])
    description = str(metadata.get("description") or "")
    phrase = re.split(r"\b(?:rather than|not|instrumental)\b", description, maxsplit=1, flags=re.I)[0]
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*", phrase)
    return clean_title(" ".join(words[-4:])) or "Untitled Song"


def needs_retitle(metadata: dict[str, Any]) -> bool:
    title = str(metadata.get("title") or "").strip()
    genre = str(metadata.get("genre") or "").strip()
    return bool(title and genre and title.casefold() == genre.casefold())


def read_entries() -> list[tuple[Path, dict[str, Any]]]:
    entries: list[tuple[Path, dict[str, Any]]] = []
    for manifest in sorted(LIBRARY.glob("*/song.json")):
        try:
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(metadata, dict):
            entries.append((manifest.parent, metadata))
    return entries


def generate_title(item: tuple[Path, dict[str, Any]]) -> tuple[Path, str, str | None]:
    folder, metadata = item
    old_title = str(metadata.get("title") or "").strip()
    if not needs_retitle(metadata):
        return folder, old_title, None
    try:
        # An empty current title tells the existing title helper to replace the
        # genre label rather than preserve it.
        sys.path.insert(0, str(ROOT / "python"))
        import ai_assist

        result = ai_assist.write(
            "title",
            title="",
            description=str(metadata.get("description") or ""),
            lyrics=str(metadata.get("lyrics") or ""),
            language=str(metadata.get("lyrics_language") or "en"),
        )
        title = clean_title(result.get("title", ""))
        if title and title.casefold() != str(metadata.get("genre") or "").strip().casefold():
            return folder, title, None
    except Exception as error:  # fallback keeps one bad request from blocking the batch
        return folder, lyric_fallback(metadata), f"{type(error).__name__}: {error}"
    return folder, lyric_fallback(metadata), None


def build_plan(entries: list[tuple[Path, dict[str, Any]]]) -> list[dict[str, Any]]:
    titles: dict[Path, str] = {}
    errors: dict[Path, str] = {}
    work = [item for item in entries if needs_retitle(item[1])]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(generate_title, item) for item in work]
        for index, future in enumerate(as_completed(futures), 1):
            folder, title, error = future.result()
            titles[folder] = title
            if error:
                errors[folder] = error
            if index % 10 == 0 or index == len(futures):
                print(f"Generated {index}/{len(futures)} replacement titles", flush=True)

    used: dict[str, set[str]] = {}
    plan: list[dict[str, Any]] = []
    for folder, metadata in entries:
        old_title = str(metadata.get("title") or folder.name).strip()
        title = titles.get(folder, old_title) or lyric_fallback(metadata)
        group = genre_folder(str(metadata.get("genre") or ""))
        group_used = used.setdefault(group.casefold(), set())
        base = safe_stem(title)
        candidate = base
        suffix = 2
        while candidate.casefold() in group_used:
            candidate = f"{base} ({suffix})"
            suffix += 1
        group_used.add(candidate.casefold())
        plan.append({
            "source_folder": folder.name,
            "id": metadata.get("id"),
            "genre": str(metadata.get("genre") or ""),
            "genre_folder": group,
            "old_title": old_title,
            "new_title": candidate,
            "retitled": candidate != old_title,
            "title_generation_error": errors.get(folder),
            "target_folder": f"{group}/{candidate}",
        })
    return plan


def rename_audio(folder: Path, metadata: dict[str, Any], title: str) -> None:
    current_name = str(metadata.get("audio") or "song.wav")
    current = folder / Path(current_name).name
    if not current.is_file():
        return
    target = folder / f"{safe_stem(title)}{current.suffix.lower()}"
    if target != current and target.exists():
        index = 2
        while True:
            target = folder / f"{safe_stem(title)} ({index}){current.suffix.lower()}"
            if not target.exists():
                break
            index += 1
    if target != current:
        current.replace(target)
    metadata["audio"] = target.name


def apply_plan(entries: list[tuple[Path, dict[str, Any]]], plan: list[dict[str, Any]]) -> None:
    by_source = {item["source_folder"]: item for item in plan}
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
    for source, metadata in entries:
        item = by_source[source.name]
        metadata["original_title"] = item["old_title"]
        metadata["title"] = item["new_title"]
        metadata["organization"] = {
            "genre_folder": item["genre_folder"],
            "organized_at": stamp,
            "original_folder": item["source_folder"],
        }
        rename_audio(source, metadata, item["new_title"])
        source.joinpath("song.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    # Stage every source first. Some source folder names are also genre names,
    # so moving directly to genre/title would otherwise mean moving a folder
    # into one of its own children.
    staging = LIBRARY / ".library-organization-staging"
    if staging.exists():
        raise RuntimeError(f"Staging folder already exists: {staging}")
    staging.mkdir()
    for source, _ in entries:
        source.replace(staging / source.name)

    for source, metadata in entries:
        item = by_source[source.name]
        destination = LIBRARY / item["genre_folder"] / item["new_title"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        (staging / source.name).replace(destination)
    staging.rmdir()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write metadata and move the song folders")
    parser.add_argument("--apply-plan", action="store_true", help="apply the existing manifest without regenerating titles")
    args = parser.parse_args()
    entries = read_entries()
    if not entries and not args.apply_plan:
        print("No top-level song manifests found.")
        return 1
    if args.apply_plan:
        payload = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
        plan = payload["songs"]
        # Recover a plan that was interrupted after moving one or more
        # directories. Put those entries back at the original staging point
        # so the complete move can be resumed atomically at the directory
        # level.
        for item in plan:
            source = LIBRARY / item["source_folder"]
            destination = LIBRARY / item["target_folder"]
            if not source.exists() and destination.is_dir():
                destination.replace(source)
        entries = [(LIBRARY / item["source_folder"], json.loads((LIBRARY / item["source_folder"] / "song.json").read_text(encoding="utf-8"))) for item in plan]
        if any(not folder.is_dir() for folder, _ in entries):
            raise RuntimeError("The saved plan no longer matches the top-level library")
        print(f"Using existing plan: {PLAN_PATH}")
    else:
        plan = build_plan(entries)
        PLAN_PATH.write_text(json.dumps({"created_at": datetime.now().astimezone().isoformat(), "songs": plan}, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Plan written: {PLAN_PATH}")
    print(f"Songs: {len(plan)}; retitled: {sum(1 for item in plan if item['retitled'])}; genre folders: {len({item['genre_folder'] for item in plan})}")
    if args.apply or args.apply_plan:
        apply_plan(entries, plan)
        print("Library organization applied.")
    else:
        print("Dry run only. Re-run with --apply to move and rename the songs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
