from __future__ import annotations

import argparse
import gc
import json
import math
import re
import sys
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_configure_stdio()


LANGUAGES_WITHOUT_SPACES = {"ja", "zh", "ko"}
PUNCTUATION_CHARS = {
    ".",
    ",",
    "!",
    "?",
    ":",
    ";",
    "\"",
    "'",
    "(",
    ")",
    "[",
    "]",
    "{",
    "}",
    "<",
    ">",
    "/",
    "\\",
    "-",
    "_",
    "*",
    "#",
    "~",
    "…",
    "，",
    "。",
    "！",
    "？",
    "：",
    "；",
    "（",
    "）",
    "【",
    "】",
    "「",
    "」",
    "『",
    "』",
}


@dataclass
class TimedToken:
    token: str
    start: float
    end: float


def emit(event: str, **payload: Any) -> None:
    line = json.dumps({"event": event, **payload}, ensure_ascii=True)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((line + "\n").encode("utf-8"))
        sys.stdout.buffer.flush()


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def format_timestamp(seconds: float, separator: str = ".") -> str:
    safe_seconds = max(0.0, float(seconds))
    minutes = int(safe_seconds // 60)
    remainder = safe_seconds - (minutes * 60)
    whole = int(remainder)
    centiseconds = int(round((remainder - whole) * 100))
    if centiseconds == 100:
        centiseconds = 0
        whole += 1
        if whole == 60:
            whole = 0
            minutes += 1
    return f"{minutes:02d}:{whole:02d}{separator}{centiseconds:02d}"


def format_ass_timestamp(seconds: float) -> str:
    safe_seconds = max(0.0, float(seconds))
    hours = int(safe_seconds // 3600)
    minutes = int((safe_seconds % 3600) // 60)
    remainder = safe_seconds - (hours * 3600) - (minutes * 60)
    whole = int(remainder)
    centiseconds = int(round((remainder - whole) * 100))
    if centiseconds == 100:
        centiseconds = 0
        whole += 1
    if whole == 60:
        whole = 0
        minutes += 1
    if minutes == 60:
        minutes = 0
        hours += 1
    return f"{hours}:{minutes:02d}:{whole:02d}.{centiseconds:02d}"


def tokenize_for_match(text: str, language: str) -> List[str]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return []
    if language in LANGUAGES_WITHOUT_SPACES:
        return [char for char in cleaned if char.strip() and char not in PUNCTUATION_CHARS]
    return [token for token in re.findall(r"[\w']+", cleaned.lower(), flags=re.UNICODE) if token]


def split_display_units(text: str, language: str) -> List[str]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return []
    if language in LANGUAGES_WITHOUT_SPACES:
        return [char for char in cleaned if char.strip()]
    return [part for part in re.split(r"\s+", cleaned) if part]


def extract_lyric_lines(text: str, language: str) -> List[Dict[str, Any]]:
    lines: List[Dict[str, Any]] = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            continue
        if line.startswith("(") and line.endswith(")"):
            continue
        # Strip leading section markers like "[Verse 1]" or "(Chorus)" from the
        # beginning of lyric lines so they do not pollute the alignment tokens.
        line = re.sub(r"^\[.*?\]\s*", "", line).strip()
        line = re.sub(r"^\(.*?\)\s*", "", line).strip()
        if not line:
            continue
        tokens = tokenize_for_match(line, language)
        if not tokens:
            continue
        lines.append({"text": line, "tokens": tokens})
    return lines


def build_transcription_prompt(lyrics_text: str, language: str, max_chars: int = 800) -> str:
    prompt_lines = [line["text"] for line in extract_lyric_lines(lyrics_text, language)[:16]]
    prompt = " ".join(prompt_lines).strip()
    if not prompt:
        return ""
    return prompt[:max_chars].strip()


def flatten_aligned_words(result: Dict[str, Any], language: str) -> List[TimedToken]:
    tokens: List[TimedToken] = []
    for segment in result.get("segments", []):
        if not isinstance(segment, dict):
            continue
        words = segment.get("words") or []
        for word in words:
            if not isinstance(word, dict):
                continue
            word_text = str(word.get("word") or word.get("text") or "").strip()
            start = word.get("start")
            end = word.get("end")
            if not word_text or start is None or end is None:
                continue
            start_time = float(start)
            end_time = float(end)
            if not math.isfinite(start_time) or not math.isfinite(end_time) or end_time <= start_time:
                continue
            word_tokens = tokenize_for_match(word_text, language)
            if not word_tokens:
                continue
            if language in LANGUAGES_WITHOUT_SPACES and len(word_tokens) > 1:
                span = end_time - start_time
                step = span / len(word_tokens)
                for index, token in enumerate(word_tokens):
                    token_start = start_time + (index * step)
                    token_end = end_time if index == len(word_tokens) - 1 else start_time + ((index + 1) * step)
                    tokens.append(TimedToken(token=token, start=token_start, end=token_end))
                continue
            tokens.append(TimedToken(token=word_tokens[0], start=start_time, end=end_time))
    return tokens


def overlap_ratio(candidate: List[str], target: List[str]) -> float:
    if not candidate or not target:
        return 0.0
    remaining = list(candidate)
    matched = 0
    for token in target:
        if token in remaining:
            remaining.remove(token)
            matched += 1
    return matched / max(1, len(target))


def score_candidate(candidate: List[str], target: List[str]) -> float:
    if not candidate or not target:
        return 0.0
    candidate_text = " ".join(candidate)
    target_text = " ".join(target)
    ratio = SequenceMatcher(None, candidate_text, target_text).ratio()
    overlap = overlap_ratio(candidate, target)
    length_penalty = abs(len(candidate) - len(target)) / max(1, len(target))
    return (ratio * 0.55) + (overlap * 0.45) - (length_penalty * 0.18)


def proportional_word_segments(text: str, start: float, end: float, language: str) -> List[Dict[str, Any]]:
    units = split_display_units(text, language)
    if not units:
        return []
    total_duration = max(0.18, end - start)
    weights = [max(1, len(tokenize_for_match(unit, language))) for unit in units]
    weight_total = sum(weights) or len(units)
    cursor = start
    output: List[Dict[str, Any]] = []
    for index, unit in enumerate(units):
        portion = total_duration * (weights[index] / weight_total)
        unit_end = end if index == len(units) - 1 else cursor + portion
        output.append({"text": unit, "start": round(cursor, 3), "end": round(unit_end, 3)})
        cursor = unit_end
    return output


def aligned_word_segments(
    text: str,
    matched_tokens: List[TimedToken],
    start: float,
    end: float,
    language: str,
) -> List[Dict[str, Any]]:
    units = split_display_units(text, language)
    if not units:
        return []
    if not matched_tokens:
        return proportional_word_segments(text, start, end, language)

    target_weights = [max(1, len(tokenize_for_match(unit, language))) for unit in units]
    total_target = sum(target_weights) or len(units)
    token_count = len(matched_tokens)
    if token_count <= 0:
        return proportional_word_segments(text, start, end, language)

    output: List[Dict[str, Any]] = []
    assigned_end = 0
    consumed_target = 0
    for index, unit in enumerate(units):
        consumed_target += target_weights[index]
        if index == len(units) - 1:
            slice_end = token_count
        else:
            slice_end = max(
                assigned_end + 1,
                min(token_count, round((consumed_target / total_target) * token_count)),
            )
        slice_tokens = matched_tokens[assigned_end:slice_end]
        if slice_tokens:
            unit_start = float(slice_tokens[0].start)
            unit_end = float(slice_tokens[-1].end)
        elif output:
            unit_start = float(output[-1]["end"])
            unit_end = unit_start + max(0.12, (end - start) / max(1, len(units)))
        else:
            unit_start = start
            unit_end = min(end, start + max(0.12, (end - start) / max(1, len(units))))
        if unit_end <= unit_start:
            unit_end = unit_start + 0.12
        output.append({"text": unit, "start": round(unit_start, 3), "end": round(unit_end, 3)})
        assigned_end = slice_end

    if not output:
        return []

    normalized: List[Dict[str, Any]] = []
    cursor = start
    total_duration = max(0.18, end - start)
    minimum_step = min(0.12, total_duration / max(1, len(output)))
    for index, word in enumerate(output):
        remaining = len(output) - index
        latest_start = max(start, end - (minimum_step * remaining))
        word_start = max(cursor, min(latest_start, float(word["start"])))
        latest_end = end - (minimum_step * max(0, remaining - 1))
        word_end = min(latest_end, max(word_start + minimum_step, float(word["end"])))
        normalized.append({"text": word["text"], "start": round(word_start, 3), "end": round(word_end, 3)})
        cursor = word_end
    normalized[0]["start"] = round(start, 3)
    normalized[-1]["end"] = round(end, 3)
    for index in range(1, len(normalized)):
        normalized[index]["start"] = round(max(float(normalized[index]["start"]), float(normalized[index - 1]["end"])), 3)
        normalized[index]["end"] = round(max(float(normalized[index]["end"]), float(normalized[index]["start"])), 3)
    return normalized


def word_segments_for_line(
    text: str,
    matched_tokens: List[TimedToken],
    start: float,
    end: float,
    language: str,
) -> List[Dict[str, Any]]:
    if not matched_tokens:
        return proportional_word_segments(text, start, end, language)
    tolerance = 0.5
    if float(matched_tokens[0].start) < start - tolerance or float(matched_tokens[-1].end) > end + tolerance:
        return proportional_word_segments(text, start, end, language)
    return aligned_word_segments(text, matched_tokens, start, end, language)


def token_match_score(left: str, right: str) -> float:
    if not left or not right:
        return -1.2
    if left == right:
        return 2.6
    ratio = SequenceMatcher(None, left, right).ratio()
    if ratio >= 0.92:
        return 2.2
    if ratio >= 0.8:
        return 1.6
    if ratio >= 0.68:
        return 0.8
    if left in right or right in left:
        return 0.7
    return -1.2


def align_token_sequences(lyric_tokens: List[str], aligned_tokens: List[TimedToken]) -> Tuple[List[Optional[int]], List[float]]:
    if not lyric_tokens or not aligned_tokens:
        return ([None] * len(lyric_tokens), [0.0] * len(lyric_tokens))

    lyric_gap_penalty = -0.95
    audio_gap_penalty = -0.35
    lyric_count = len(lyric_tokens)
    audio_count = len(aligned_tokens)
    stride = audio_count + 1
    backtrace = bytearray((lyric_count + 1) * (audio_count + 1))
    previous = [0.0] * (audio_count + 1)

    for audio_index in range(1, audio_count + 1):
        previous[audio_index] = previous[audio_index - 1] + audio_gap_penalty
        backtrace[audio_index] = 3

    for lyric_index in range(1, lyric_count + 1):
        current = [0.0] * (audio_count + 1)
        current[0] = previous[0] + lyric_gap_penalty
        backtrace[lyric_index * stride] = 2
        lyric_token = lyric_tokens[lyric_index - 1]
        row_offset = lyric_index * stride
        for audio_index in range(1, audio_count + 1):
            similarity = token_match_score(lyric_token, aligned_tokens[audio_index - 1].token)
            diagonal = previous[audio_index - 1] + similarity
            up = previous[audio_index] + lyric_gap_penalty
            left = current[audio_index - 1] + audio_gap_penalty
            best = diagonal
            move = 1
            if up > best:
                best = up
                move = 2
            if left > best:
                best = left
                move = 3
            current[audio_index] = best
            backtrace[row_offset + audio_index] = move
        previous = current

    matches: List[Optional[int]] = [None] * lyric_count
    match_scores: List[float] = [0.0] * lyric_count
    lyric_index = lyric_count
    audio_index = audio_count
    while lyric_index > 0 or audio_index > 0:
        move = backtrace[(lyric_index * stride) + audio_index]
        if move == 1:
            score = token_match_score(lyric_tokens[lyric_index - 1], aligned_tokens[audio_index - 1].token)
            if score > 0:
                matches[lyric_index - 1] = audio_index - 1
                match_scores[lyric_index - 1] = score
            lyric_index -= 1
            audio_index -= 1
        elif move == 2:
            lyric_index -= 1
        elif move == 3:
            audio_index -= 1
        else:
            break
    return matches, match_scores


def estimate_seconds_per_token(
    line_records: List[Dict[str, Any]],
    lyric_lines: List[Dict[str, Any]],
    duration_seconds: float,
) -> float:
    total_duration = 0.0
    total_tokens = 0
    for index, record in enumerate(line_records):
        matched_tokens = record.get("matched_tokens") or []
        if not matched_tokens:
            continue
        total_duration += max(0.12, float(record["end"]) - float(record["start"]))
        total_tokens += max(1, len(lyric_lines[index]["tokens"]))
    if total_tokens <= 0:
        fallback = duration_seconds / max(1, sum(max(1, len(line["tokens"])) for line in lyric_lines))
        return clamp(fallback, 0.22, 0.9)
    return clamp(total_duration / total_tokens, 0.22, 0.9)


def line_match_is_confident(
    lyric_tokens: List[str],
    matched_pairs: List[Tuple[int, float]],
    matched_window: List[TimedToken],
) -> bool:
    if not lyric_tokens or not matched_pairs or not matched_window:
        return False

    token_count = max(1, len(lyric_tokens))
    matched_count = len(matched_pairs)
    coverage = matched_count / token_count
    window_duration = max(0.0, float(matched_window[-1].end) - float(matched_window[0].start))
    average_score = sum(score for _, score in matched_pairs) / matched_count
    normalized_score = sum(score for _, score in matched_pairs) / token_count
    seconds_per_lyric_token = window_duration / token_count

    if token_count <= 2:
        min_matches = token_count
    elif token_count <= 4:
        min_matches = 2
    else:
        min_matches = 3

    if matched_count < min_matches:
        return False
    if coverage < 0.45 and not (matched_count >= 3 and average_score >= 2.0):
        return False
    if average_score < 1.15 and normalized_score < 1.0:
        return False
    if seconds_per_lyric_token < 0.12:
        return False
    return True


def matched_run_length(line_records: List[Dict[str, Any]], anchor_index: int, step: int) -> int:
    length = 0
    index = anchor_index
    while 0 <= index < len(line_records):
        if not line_records[index].get("matched_tokens"):
            break
        length += 1
        index += step
    return length


def assign_block_timings(
    line_records: List[Dict[str, Any]],
    lyric_lines: List[Dict[str, Any]],
    start_index: int,
    end_index: int,
    window_start: float,
    window_end: float,
    language: str,
) -> None:
    available = max(0.18 * (end_index - start_index + 1), window_end - window_start)
    weights = [max(1, len(lyric_lines[index]["tokens"])) for index in range(start_index, end_index + 1)]
    total_weight = sum(weights) or len(weights)
    cursor = window_start
    for relative_index, line_index in enumerate(range(start_index, end_index + 1)):
        line_duration = available * (weights[relative_index] / total_weight)
        line_end = window_end if line_index == end_index else cursor + line_duration
        line_records[line_index]["start"] = round(cursor, 3)
        line_records[line_index]["end"] = round(max(cursor + 0.18, line_end), 3)
        line_records[line_index]["matched_tokens"] = []
        line_records[line_index]["word_segments"] = proportional_word_segments(
            lyric_lines[line_index]["text"],
            float(line_records[line_index]["start"]),
            float(line_records[line_index]["end"]),
            language,
        )
        cursor = float(line_records[line_index]["end"])


def fill_unmatched_line_timings(
    line_records: List[Dict[str, Any]],
    lyric_lines: List[Dict[str, Any]],
    duration_seconds: float,
    language: str,
) -> None:
    if not line_records:
        return

    seconds_per_token = estimate_seconds_per_token(line_records, lyric_lines, duration_seconds)
    index = 0
    record_count = len(line_records)
    while index < record_count:
        if line_records[index].get("matched_tokens"):
            index += 1
            continue
        block_start = index
        while index < record_count and not line_records[index].get("matched_tokens"):
            index += 1
        block_end = index - 1

        previous_index = block_start - 1 if block_start > 0 and line_records[block_start - 1].get("matched_tokens") else None
        next_index = index if index < record_count and line_records[index].get("matched_tokens") else None
        token_budget = sum(max(1, len(lyric_lines[line_index]["tokens"])) for line_index in range(block_start, block_end + 1))
        estimated_duration = clamp(token_budget * seconds_per_token, 0.8 * (block_end - block_start + 1), 6.0)

        if previous_index is not None and next_index is not None:
            gap_start = float(line_records[previous_index]["end"])
            gap_end = float(line_records[next_index]["start"])
            gap_duration = gap_end - gap_start
            if gap_duration >= 0.3 and gap_duration <= max(estimated_duration * 1.8, 1.2 * (block_end - block_start + 1)):
                assign_block_timings(line_records, lyric_lines, block_start, block_end, gap_start, gap_end, language)
                continue
            if gap_duration >= 0.3:
                previous_run = matched_run_length(line_records, previous_index, -1)
                next_run = matched_run_length(line_records, next_index, 1)
                if next_run > previous_run:
                    window_end = gap_end
                    window_start = max(gap_start, window_end - estimated_duration)
                    assign_block_timings(line_records, lyric_lines, block_start, block_end, window_start, window_end, language)
                    continue
                if previous_run > next_run:
                    window_start = gap_start
                    window_end = min(gap_end, window_start + estimated_duration)
                    assign_block_timings(line_records, lyric_lines, block_start, block_end, window_start, window_end, language)
                    continue
                centered_start = max(gap_start, gap_start + ((gap_duration - estimated_duration) / 2.0))
                centered_end = min(gap_end, centered_start + estimated_duration)
                assign_block_timings(line_records, lyric_lines, block_start, block_end, centered_start, centered_end, language)
                continue

        if next_index is not None:
            window_end = float(line_records[next_index]["start"])
            window_start = max(0.0, window_end - estimated_duration)
            assign_block_timings(line_records, lyric_lines, block_start, block_end, window_start, window_end, language)
            continue

        if previous_index is not None:
            window_start = float(line_records[previous_index]["end"])
            window_end = min(duration_seconds, window_start + estimated_duration)
            assign_block_timings(line_records, lyric_lines, block_start, block_end, window_start, window_end, language)
            continue

        assign_block_timings(
            line_records,
            lyric_lines,
            block_start,
            block_end,
            0.0,
            min(duration_seconds, estimated_duration),
            language,
        )


def distribute_line_timings(lines: List[Dict[str, Any]], duration_seconds: float, language: str) -> List[Dict[str, Any]]:
    if not lines:
        return []
    total_weight = sum(max(1, len(line["tokens"])) for line in lines)
    cursor = 0.0
    output: List[Dict[str, Any]] = []
    for index, line in enumerate(lines):
        line_duration = max(1.4, duration_seconds * (max(1, len(line["tokens"])) / total_weight))
        line_end = duration_seconds if index == len(lines) - 1 else min(duration_seconds, cursor + line_duration)
        output.append(
            {
                "index": index + 1,
                "text": line["text"],
                "start": round(cursor, 3),
                "end": round(line_end, 3),
                "words": proportional_word_segments(line["text"], cursor, line_end, language),
            }
        )
        cursor = line_end
    return output


def align_lyric_lines(
    lyric_lines: List[Dict[str, Any]],
    aligned_tokens: List[TimedToken],
    duration_seconds: float,
    language: str,
) -> List[Dict[str, Any]]:
    if not lyric_lines:
        return []
    if not aligned_tokens:
        return distribute_line_timings(lyric_lines, duration_seconds, language)

    lyric_token_stream: List[str] = []
    line_ranges: List[Tuple[int, int]] = []
    for lyric_line in lyric_lines:
        start_index = len(lyric_token_stream)
        lyric_token_stream.extend(lyric_line["tokens"])
        line_ranges.append((start_index, len(lyric_token_stream)))

    token_matches, token_scores = align_token_sequences(lyric_token_stream, aligned_tokens)
    line_records: List[Dict[str, Any]] = []
    for line_index, lyric_line in enumerate(lyric_lines):
        token_start, token_end = line_ranges[line_index]
        matched_pairs = [
            (token_matches[token_index], token_scores[token_index])
            for token_index in range(token_start, token_end)
            if token_matches[token_index] is not None
        ]
        matched_indices = [match_index for match_index, _ in matched_pairs]
        matched_window = [aligned_tokens[match_index] for match_index in matched_indices]
        match_score = sum(score for _, score in matched_pairs) / max(1, len(lyric_line["tokens"]))
        if matched_window:
            if line_match_is_confident(lyric_line["tokens"], matched_pairs, matched_window):
                start_time = float(matched_window[0].start)
                end_time = float(matched_window[-1].end)
                word_segments = word_segments_for_line(lyric_line["text"], matched_window, start_time, end_time, language)
            else:
                start_time = 0.0
                end_time = 0.0
                matched_window = []
                word_segments = []
        else:
            start_time = 0.0
            end_time = 0.0
            word_segments = []
        line_records.append(
            {
                "index": line_index + 1,
                "text": lyric_line["text"],
                "start": round(start_time, 3),
                "end": round(end_time, 3),
                "matchScore": round(match_score, 4),
                "matched_tokens": matched_window,
                "word_segments": word_segments,
            }
        )

    fill_unmatched_line_timings(line_records, lyric_lines, duration_seconds, language)

    timed_lines: List[Dict[str, Any]] = []
    for line_index, record in enumerate(line_records):
        start_time = max(0.0, float(record["start"]))
        if timed_lines:
            start_time = max(start_time, float(timed_lines[-1]["end"]))
        end_time = max(start_time + 0.18, float(record["end"]))
        end_time = min(duration_seconds, end_time)
        matched_window = record.get("matched_tokens") or []
        if matched_window:
            words = word_segments_for_line(
                lyric_lines[line_index]["text"],
                matched_window,
                start_time,
                end_time,
                language,
            )
        else:
            words = proportional_word_segments(
                lyric_lines[line_index]["text"],
                start_time,
                end_time,
                language,
            )
        timed_lines.append(
            {
                "index": line_index + 1,
                "text": lyric_lines[line_index]["text"],
                "start": round(start_time, 3),
                "end": round(end_time, 3),
                "matchScore": round(float(record.get("matchScore") or 0.0), 4),
                "words": words,
            }
        )

    if timed_lines:
        timed_lines[-1]["end"] = round(min(duration_seconds, max(float(timed_lines[-1]["end"]), float(timed_lines[-1]["start"]) + 0.18)), 3)
    return timed_lines


def build_lrc(lines: List[Dict[str, Any]]) -> str:
    rows = [f"[{format_timestamp(line['start'])}]{line['text']}" for line in lines]
    return "\n".join(rows).strip() + ("\n" if rows else "")


def build_ass(title: str, lines: List[Dict[str, Any]]) -> str:
    header = """[Script Info]
Title: {title}
ScriptType: v4.00+
WrapStyle: 2
PlayResX: 1280
PlayResY: 720
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Plus Jakarta Sans,34,&H00FFFFFF,&H004D8AFF,&H0011141A,&H6E000000,1,0,0,0,100,100,0,0,1,2.4,0,2,80,80,52,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dialogue_rows: List[str] = []
    for line in lines:
        words = line.get("words") or []
        karaoke_parts: List[str] = []
        if words:
            for word in words:
                word_start = float(word["start"])
                word_end = float(word["end"])
                centiseconds = max(1, int(round((word_end - word_start) * 100)))
                karaoke_parts.append(rf"{{\k{centiseconds}}}{word['text']}")
        else:
            total_centiseconds = max(1, int(round((float(line["end"]) - float(line["start"])) * 100)))
            karaoke_parts.append(rf"{{\k{total_centiseconds}}}{line['text']}")
        dialogue_rows.append(
            f"Dialogue: 0,{format_ass_timestamp(float(line['start']))},{format_ass_timestamp(float(line['end']))},Default,,0,0,0,,{' '.join(karaoke_parts)}"
        )
    return header.format(title=title.replace("\n", " ").strip()) + "\n".join(dialogue_rows) + ("\n" if dialogue_rows else "")


def find_vocals_stem(output_root: Path) -> Optional[Path]:
    matches = sorted(output_root.glob("**/*vocals.wav"))
    return matches[0] if matches else None


def write_wav_pcm16(path: Path, waveform: Any, samplerate: int) -> None:
    import wave

    import numpy as np
    import torch

    tensor = waveform.detach().cpu()
    if tensor.ndim != 2:
        raise RuntimeError("Expected Demucs waveform to have [channels, samples] shape.")
    pcm = (
        tensor.clamp(-1.0, 1.0)
        .mul(32767.0)
        .round()
        .to(torch.int16)
        .transpose(0, 1)
        .contiguous()
        .numpy()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(int(pcm.shape[1]) if pcm.ndim == 2 else 1)
        handle.setsampwidth(2)
        handle.setframerate(int(samplerate))
        handle.writeframes(np.asarray(pcm, dtype="<i2").tobytes())


def run_demucs(audio_path: Path, output_root: Path, device: str) -> Optional[Path]:
    emit("progress", phase="stems", message="Separating vocals with Demucs.")
    from demucs.apply import BagOfModels, apply_model
    from demucs.htdemucs import HTDemucs
    from demucs.separate import get_model_from_args, get_parser, load_track

    args = get_parser().parse_args(
        [
            "--two-stems=vocals",
            "--out",
            str(output_root),
            "--filename",
            "{track}.{stem}.{ext}",
            "--segment",
            "7",
            "-d",
            device,
            str(audio_path),
        ]
    )
    model = get_model_from_args(args)

    max_allowed_segment = float("inf")
    if isinstance(model, HTDemucs):
        max_allowed_segment = float(model.segment)
    elif isinstance(model, BagOfModels):
        max_allowed_segment = float(model.max_allowed_segment)
    if args.segment is not None and float(args.segment) > max_allowed_segment:
        args.segment = int(max_allowed_segment)

    model.cpu()
    model.eval()
    wav = load_track(audio_path, model.audio_channels, model.samplerate)
    ref = wav.mean(0)
    wav -= ref.mean()
    wav /= ref.std()
    sources = apply_model(
        model,
        wav[None],
        device=args.device,
        shifts=args.shifts,
        split=args.split,
        overlap=args.overlap,
        progress=False,
        num_workers=args.jobs,
        segment=args.segment,
    )[0]
    sources *= ref.std()
    sources += ref.mean()

    out_dir = Path(args.out) / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    vocals_path = out_dir / args.filename.format(
        track=audio_path.name.rsplit(".", 1)[0],
        trackext=audio_path.name.rsplit(".", 1)[-1],
        stem="vocals",
        ext="wav",
    )
    write_wav_pcm16(vocals_path, sources[model.sources.index("vocals")], model.samplerate)
    return vocals_path


def choose_language(language: str) -> str:
    normalized = str(language or "").strip().lower()
    if not normalized or normalized == "instrumental":
        return "en"
    return normalized


def choose_device(requested: str) -> str:
    if requested in {"cpu", "cuda"}:
        return requested
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


def count_aligned_words(result: Dict[str, Any], language: str) -> int:
    return len(flatten_aligned_words(result, language))


def transcribe_with_faster_whisper(
    audio_path: Path,
    language: str,
    device: str,
    model_name: str,
    lyrics_prompt: str,
) -> Dict[str, Any]:
    from faster_whisper import WhisperModel

    compute_type = "float16" if device == "cuda" else "int8"
    emit("progress", phase="transcribe", message=f"Transcribing vocals with Faster-Whisper on {device} using {model_name}.")
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments_iter, info = model.transcribe(
        str(audio_path),
        language=language,
        beam_size=5,
        best_of=5,
        condition_on_previous_text=True,
        word_timestamps=True,
        vad_filter=True,
        temperature=0.0,
        initial_prompt=lyrics_prompt or None,
    )
    segments: List[Dict[str, Any]] = []
    for segment in list(segments_iter):
        word_rows: List[Dict[str, Any]] = []
        for word in segment.words or []:
            word_rows.append(
                {
                    "word": str(word.word or ""),
                    "start": None if word.start is None else float(word.start),
                    "end": None if word.end is None else float(word.end),
                }
            )
        segments.append(
            {
                "start": float(segment.start),
                "end": float(segment.end),
                "text": str(segment.text or ""),
                "words": word_rows,
            }
        )
    aligned = {"segments": segments}
    return {
        "aligned": aligned,
        "language": choose_language(str(getattr(info, "language", None) or language)),
        "device": device,
        "duration_seconds": float(getattr(info, "duration", 0.0) or 0.0),
        "transcript_word_count": count_aligned_words(aligned, language),
        "aligned_audio_path": str(audio_path),
    }


def transcribe_with_whisperx(audio_path: Path, language: str, device: str, model_name: str) -> Dict[str, Any]:
    import torch
    import whisperx

    compute_type = "float16" if device == "cuda" else "int8"
    emit("progress", phase="transcribe", message=f"Transcribing with WhisperX on {device} using {model_name}.")
    asr_model = whisperx.load_model(
        model_name,
        device=device,
        compute_type=compute_type,
        language=language,
        asr_options={"condition_on_previous_text": False},
        vad_method="silero",
    )
    audio = whisperx.load_audio(str(audio_path))
    transcription = asr_model.transcribe(audio, batch_size=8, chunk_size=30, print_progress=False, verbose=False)

    del asr_model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    align_language = choose_language(str(transcription.get("language") or language))
    emit("progress", phase="align", message=f"Loading WhisperX align model for {align_language}.")
    align_model, align_metadata = whisperx.load_align_model(language_code=align_language, device=device)
    emit("progress", phase="align", message="Aligning recognized vocals to timestamps.")
    aligned = whisperx.align(
        transcription["segments"],
        align_model,
        align_metadata,
        audio,
        device,
        return_char_alignments=False,
        print_progress=False,
    )

    del align_model
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()

    return {"aligned": aligned, "language": align_language, "device": device}


def force_align_known_lyrics(
    audio_path: Path,
    lyric_lines: List[Dict[str, Any]],
    language: str,
    device: str,
) -> Dict[str, Any]:
    """Force-align the saved lyrics directly instead of trusting ASR wording.

    Generated singing often causes speech recognition to omit or invent words.
    WhisperX's CTC alignment model accepts known text, which gives the karaoke
    renderer the exact words the user wrote along with their audio timestamps.
    """
    import whisperx

    known_text = " ".join(str(line.get("text") or "").strip() for line in lyric_lines).strip()
    expected_tokens = [token for line in lyric_lines for token in line.get("tokens") or []]
    if not known_text or not expected_tokens:
        raise RuntimeError("No saved lyric text is available for forced alignment.")

    emit("progress", phase="align", message=f"Force-aligning the saved lyrics on {device}.")
    align_model, align_metadata = whisperx.load_align_model(language_code=language, device=device)
    audio = whisperx.load_audio(str(audio_path))
    # whisperx.load_audio returns 16 kHz mono samples.
    duration_seconds = len(audio) / 16000.0
    forced = whisperx.align(
        [{"start": 0.0, "end": duration_seconds, "text": known_text}],
        align_model,
        align_metadata,
        audio,
        device=device,
        return_char_alignments=False,
        print_progress=False,
    )
    words = list(forced.get("word_segments") or [])
    if len(words) < max(3, math.ceil(len(expected_tokens) * 0.9)):
        raise RuntimeError("Forced alignment returned too few timed lyric words.")

    return {
        "aligned": {"segments": [{"start": 0.0, "end": duration_seconds, "text": known_text, "words": words}]},
        "language": language,
        "device": device,
        "duration_seconds": duration_seconds,
        "aligned_audio_path": str(audio_path),
        "alignment_method": "whisperx-forced-known-lyrics",
    }


def transcribe_with_fallback(
    audio_path: Path,
    language: str,
    requested_device: str,
    model_name: str,
    lyrics_text: str,
    fallback_audio_path: Optional[Path] = None,
) -> Dict[str, Any]:
    if not (Path(model_name) / "model.bin").is_file():
        raise RuntimeError("Transcription fallback needs the local Whisper model. Open Models and install Whisper lyrics and karaoke, then retry.")
    primary_device = choose_device(requested_device)
    attempts = [primary_device]
    if primary_device == "cuda":
        attempts.append("cpu")
    prompt = build_transcription_prompt(lyrics_text, language)
    candidate_paths = [audio_path]
    if fallback_audio_path and fallback_audio_path.resolve() != audio_path.resolve():
        candidate_paths.append(fallback_audio_path.resolve())
    best_result: Optional[Dict[str, Any]] = None
    best_word_count = -1
    last_error = RuntimeError("No transcription run completed.")
    minimum_usable_words = 16

    for candidate_path in candidate_paths:
        for attempt_device in attempts:
            try:
                result = transcribe_with_faster_whisper(candidate_path, language, attempt_device, model_name, prompt)
                word_count = int(result.get("transcript_word_count") or 0)
                if word_count > best_word_count:
                    best_result = result
                    best_word_count = word_count
                if word_count >= minimum_usable_words:
                    if candidate_path != audio_path:
                        emit("progress", phase="transcribe", message="Using the full mix for lyric sync because the vocals stem transcript was too sparse.")
                    return result
                emit("progress", phase="transcribe", message="Transcript was too sparse for reliable lyric sync, trying another pass.")
            except Exception as exc:
                last_error = exc
                emit("progress", phase="transcribe", message=f"Faster-Whisper failed on {attempt_device}, trying fallback.")

    if best_result and best_word_count > 0:
        return best_result

    for candidate_path in candidate_paths:
        for attempt_device in attempts:
            try:
                result = transcribe_with_whisperx(candidate_path, language, attempt_device, model_name)
                result["aligned_audio_path"] = str(candidate_path)
                return result
            except Exception as exc:
                last_error = exc
                emit("progress", phase="transcribe", message=f"WhisperX failed on {attempt_device}, trying fallback.")

    raise last_error


def main() -> None:
    parser = argparse.ArgumentParser(description="Align song lyrics to audio and emit karaoke subtitle files.")
    parser.add_argument("--audio", required=True)
    parser.add_argument("--lyrics-file", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--title", default="Untitled Song")
    parser.add_argument("--language", default="en")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--model-name", default="large-v3-turbo")
    parser.add_argument("--use-vocals-stem", action="store_true")
    args = parser.parse_args()

    audio_path = Path(args.audio).resolve()
    lyrics_path = Path(args.lyrics_file).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not audio_path.exists():
        raise SystemExit(f"Audio file not found: {audio_path}")
    if not lyrics_path.exists():
        raise SystemExit(f"Lyrics file not found: {lyrics_path}")

    language = choose_language(args.language)
    lyrics_text = read_text(lyrics_path)
    lyric_lines = extract_lyric_lines(lyrics_text, language)
    if not lyric_lines:
        raise SystemExit("No usable lyric lines were found. Instrumentals do not need lyric sync.")

    output_dir.mkdir(parents=True, exist_ok=True)
    aligned_audio_path = audio_path
    vocals_path: Optional[Path] = None
    try:
        if args.use_vocals_stem:
            stems_dir = output_dir / "stems"
            vocals_path = run_demucs(audio_path, stems_dir, choose_device(args.device))
            aligned_audio_path = vocals_path or audio_path
    except Exception as exc:
        emit("progress", phase="stems", message=f"Vocals stem failed, falling back to full mix: {exc}")
        aligned_audio_path = audio_path
        vocals_path = None

    chosen_device = choose_device(args.device)
    try:
        alignment_result = force_align_known_lyrics(
            aligned_audio_path,
            lyric_lines,
            language,
            chosen_device,
        )
    except Exception as exc:
        emit("progress", phase="align", message=f"Known-lyrics alignment was unavailable, using transcription fallback: {exc}")
        alignment_result = transcribe_with_fallback(
            aligned_audio_path,
            language,
            args.device,
            args.model_name,
            lyrics_text,
            fallback_audio_path=audio_path,
        )
    aligned = alignment_result["aligned"]
    aligned_language = choose_language(alignment_result.get("language") or language)
    used_device = str(alignment_result.get("device") or choose_device(args.device))
    aligned_audio_path = Path(str(alignment_result.get("aligned_audio_path") or aligned_audio_path))
    duration_seconds = 0.0
    for segment in aligned.get("segments", []):
        if isinstance(segment, dict) and segment.get("end"):
            duration_seconds = max(duration_seconds, float(segment.get("end") or 0.0))
    reported_duration = float(alignment_result.get("duration_seconds") or 0.0)
    if reported_duration > duration_seconds:
        duration_seconds = reported_duration
    if duration_seconds <= 0:
        duration_seconds = max(1.0, 4.0 * len(lyric_lines))

    emit("progress", phase="map", message="Matching your saved lyrics against the aligned vocal words.")
    aligned_tokens = flatten_aligned_words(aligned, aligned_language)
    timed_lines = align_lyric_lines(lyric_lines, aligned_tokens, duration_seconds, aligned_language)
    if not timed_lines:
        raise SystemExit("Lyric timing failed: no timed lines were produced.")

    emit("progress", phase="write", message="Writing JSON, LRC, and ASS karaoke files.")
    timed_json_path = output_dir / "timed_lyrics.json"
    lrc_path = output_dir / "timed_lyrics.lrc"
    ass_path = output_dir / "karaoke.ass"

    result_payload = {
        "title": args.title,
        "language": aligned_language,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "audio_path": str(audio_path),
        "aligned_audio_path": str(aligned_audio_path),
        "vocals_path": str(vocals_path) if vocals_path else "",
        "duration_seconds": duration_seconds,
        "line_count": len(timed_lines),
        "word_count": sum(len(line.get("words") or []) for line in timed_lines),
        "model_name": args.model_name,
        "device": used_device,
        "used_vocals_stem": bool(vocals_path),
        "alignment_method": str(alignment_result.get("alignment_method") or "transcription-fallback"),
        "lines": timed_lines,
    }
    write_json(timed_json_path, result_payload)
    write_text(lrc_path, build_lrc(timed_lines))
    write_text(ass_path, build_ass(args.title, timed_lines))

    emit(
        "result",
        status="completed",
        json_path=str(timed_json_path),
        lrc_path=str(lrc_path),
        ass_path=str(ass_path),
        vocals_path=str(vocals_path) if vocals_path else "",
        aligned_audio_path=str(aligned_audio_path),
        duration_seconds=duration_seconds,
        line_count=len(timed_lines),
        word_count=result_payload["word_count"],
        model_name=args.model_name,
        device=result_payload["device"],
        used_vocals_stem=result_payload["used_vocals_stem"],
        alignment_method=result_payload["alignment_method"],
    )


if __name__ == "__main__":
    main()
