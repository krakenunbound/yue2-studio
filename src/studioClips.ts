/**
 * Non-destructive Studio clip math.
 * Timeline time is independent of source-file time so clips can be split,
 * slid, and faded without rewriting audio.
 */

export type StudioClip = {
  id: string;
  start: number;
  source_in: number;
  source_out: number | null;
  fade_in: number;
  fade_out: number;
  gain?: number;
  gain_left?: number;
  gain_right?: number;
};

export const CLIP_GAIN_MAX = 2;

export type StudioRange = { start: number; end: number };

export const MIN_WORKSPACE_SECONDS = 600;
export const WORKSPACE_TAIL_SECONDS = 45;

export function clipId(prefix = "clip"): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

export function clipLength(clip: StudioClip, sourceDuration = 0): number {
  const sourceOut = clip.source_out == null ? Math.max(clip.source_in, sourceDuration) : clip.source_out;
  return Math.max(0, sourceOut - clip.source_in);
}

export function clipEnd(clip: StudioClip, sourceDuration = 0): number {
  return clip.start + clipLength(clip, sourceDuration);
}

export function sourceTimeAt(clip: StudioClip, timelineTime: number): number {
  return clip.source_in + Math.max(0, timelineTime - clip.start);
}

export function clipAtTime(clips: StudioClip[], timelineTime: number, sourceDuration = 0): StudioClip | undefined {
  return clips.find((clip) => timelineTime >= clip.start && timelineTime < clipEnd(clip, sourceDuration));
}

/** Equal-power / Premiere-style cosine fade, 0–1. */
export function cosineGain(progress: number): number {
  const value = Math.min(1, Math.max(0, progress));
  return 0.5 * (1 - Math.cos(Math.PI * value));
}

export function fadeFactor(clip: StudioClip, timelineTime: number, sourceDuration = 0): number {
  const length = clipLength(clip, sourceDuration);
  if (length <= 0) return 0;
  const local = timelineTime - clip.start;
  if (local < 0 || local > length) return 0;
  let factor = 1;
  if (clip.fade_in > 0) factor = Math.min(factor, cosineGain(local / clip.fade_in));
  if (clip.fade_out > 0) factor = Math.min(factor, cosineGain((length - local) / clip.fade_out));
  return Math.min(1, Math.max(0, factor));
}

/** Keep a clip inside the real source file so a 5s thunder hit cannot become a 2:30 block. */
export function fitClipToSource(clip: StudioClip, sourceDuration: number): StudioClip {
  if (!(sourceDuration > 0)) return clip;
  const sourceOut = clip.source_out == null ? sourceDuration : Math.min(clip.source_out, sourceDuration);
  const sourceIn = Math.min(clip.source_in, Math.max(0, sourceOut - 0.01));
  if (sourceOut === clip.source_out && sourceIn === clip.source_in) return clip;
  return { ...clip, source_in: sourceIn, source_out: sourceOut };
}

export function makeClip(partial: Partial<StudioClip> = {}): StudioClip {
  return {
    id: partial.id || clipId(),
    start: Math.max(0, partial.start ?? 0),
    source_in: Math.max(0, partial.source_in ?? 0),
    source_out: partial.source_out ?? null,
    fade_in: Math.max(0, partial.fade_in ?? 0),
    fade_out: Math.max(0, partial.fade_out ?? 0),
    gain: Math.max(0, Math.min(CLIP_GAIN_MAX, partial.gain ?? 1)),
    gain_left: Math.max(0, Math.min(CLIP_GAIN_MAX, partial.gain_left ?? 1)),
    gain_right: Math.max(0, Math.min(CLIP_GAIN_MAX, partial.gain_right ?? 1)),
  };
}

export function clipGain(clip: StudioClip): number {
  return Math.max(0, Math.min(CLIP_GAIN_MAX, clip.gain ?? 1));
}

export function clipChannelGain(clip: StudioClip, side: "left" | "right"): number {
  const extra = side === "left" ? clip.gain_left : clip.gain_right;
  return clipGain(clip) * Math.max(0, Math.min(CLIP_GAIN_MAX, extra ?? 1));
}

export function gainToLinePercent(gain: number): number {
  return (1 - Math.max(0, Math.min(CLIP_GAIN_MAX, gain)) / CLIP_GAIN_MAX) * 100;
}

export function linePercentToGain(percent: number): number {
  return Math.max(0, Math.min(CLIP_GAIN_MAX, (1 - percent / 100) * CLIP_GAIN_MAX));
}

/** Build clips from the older one-block offset / trim / cut session. */
export function clipsFromLegacy(state: {
  offset?: number;
  trim_start?: number;
  trim_end?: number | null;
  fade_in?: number;
  fade_out?: number;
  cuts?: StudioRange[];
}, sourceDuration = 0): StudioClip[] {
  const offset = Math.max(0, state.offset ?? 0);
  const start = Math.max(offset, state.trim_start ?? 0);
  const sourceIn = Math.max(0, start - offset);
  const sourceOut = state.trim_end == null ? (sourceDuration > 0 ? sourceDuration : null) : Math.max(sourceIn, state.trim_end - offset);
  const base = makeClip({
    start,
    source_in: sourceIn,
    source_out: sourceOut,
    fade_in: state.fade_in ?? 0,
    fade_out: state.fade_out ?? 0,
  });
  return splitOutRanges([base], state.cuts ?? [], sourceDuration);
}

export function ensureClips(state: {
  use_clips?: boolean;
  clips?: StudioClip[];
  offset?: number;
  trim_start?: number;
  trim_end?: number | null;
  fade_in?: number;
  fade_out?: number;
  cuts?: StudioRange[];
}, sourceDuration = 0): StudioClip[] {
  if (state.use_clips) return [...(state.clips ?? [])];
  if (state.clips?.length) return [...state.clips];
  return clipsFromLegacy(state, sourceDuration);
}

export function splitClip(clip: StudioClip, timelineTime: number, sourceDuration = 0): StudioClip[] {
  const end = clipEnd(clip, sourceDuration);
  if (timelineTime <= clip.start + 0.02 || timelineTime >= end - 0.02) return [clip];
  const local = timelineTime - clip.start;
  const mid = clip.source_in + local;
  const leftLen = local;
  const rightLen = end - timelineTime;
  const leftFadeOut = Math.min(clip.fade_out, leftLen);
  const rightFadeIn = Math.min(clip.fade_in, rightLen);
  return [
    { ...clip, source_out: mid, fade_in: Math.min(clip.fade_in, leftLen), fade_out: leftFadeOut },
    makeClip({
      start: timelineTime,
      source_in: mid,
      source_out: clip.source_out,
      fade_in: rightFadeIn,
      fade_out: Math.min(clip.fade_out, rightLen),
    }),
  ];
}

export function splitClipsAt(clips: StudioClip[], timelineTime: number, sourceDuration = 0): StudioClip[] {
  return clips.flatMap((clip) => splitClip(clip, timelineTime, sourceDuration));
}

export function splitOutRanges(clips: StudioClip[], ranges: StudioRange[], sourceDuration = 0): StudioClip[] {
  let next = clips;
  for (const range of ranges) {
    if (range.end - range.start < 0.02) continue;
    next = splitClipsAt(next, range.start, sourceDuration);
    next = splitClipsAt(next, range.end, sourceDuration);
    next = next.filter((clip) => clipEnd(clip, sourceDuration) <= range.start + 0.001 || clip.start >= range.end - 0.001);
  }
  return next;
}

/** Remove a range AND close the gap it leaves, pulling later clips left.
 *
 * splitOutRanges alone leaves silence where the audio was, which is right for
 * "mute this bit" and wrong for "delete this bit" -- the song should get
 * shorter. Ripple is the normal expectation in an audio editor.
 */
export function rippleDelete(clips: StudioClip[], range: StudioRange, sourceDuration = 0): StudioClip[] {
  const span = range.end - range.start;
  if (span < 0.02) return clips;
  const cleared = splitOutRanges(clips, [range], sourceDuration);
  return shiftClipsAfter(cleared, range.end - 0.001, -span, sourceDuration);
}

export function moveClips(clips: StudioClip[], delta: number, ids?: Set<string>): StudioClip[] {
  return clips.map((clip) => {
    if (ids && !ids.has(clip.id)) return clip;
    return { ...clip, start: Math.max(0, clip.start + delta) };
  });
}

export function shiftClipsAfter(clips: StudioClip[], timelineTime: number, delta: number, sourceDuration = 0): StudioClip[] {
  return clips.map((clip) => (clip.start >= timelineTime - 0.001 ? { ...clip, start: Math.max(0, clip.start + delta) } : clip));
}

export function insertSpace(clips: StudioClip[], timelineTime: number, seconds: number, sourceDuration = 0): StudioClip[] {
  const split = splitClipsAt(clips, timelineTime, sourceDuration);
  return shiftClipsAfter(split, timelineTime, seconds, sourceDuration);
}

export function lastClipEnd(clips: StudioClip[], sourceDuration = 0): number {
  return clips.reduce((end, clip) => Math.max(end, clipEnd(clip, sourceDuration)), 0);
}

export function workspaceDuration(clipEnds: number, sourceDuration = 0, current = MIN_WORKSPACE_SECONDS): number {
  return Math.max(MIN_WORKSPACE_SECONDS, current, sourceDuration + 60, clipEnds + WORKSPACE_TAIL_SECONDS);
}

export function slicePeaks(peaks: number[] | undefined, clip: StudioClip, sourceDuration: number): number[] | undefined {
  if (!peaks?.length || sourceDuration <= 0) return peaks;
  const start = Math.max(0, Math.min(1, clip.source_in / sourceDuration));
  const end = Math.max(start + 0.002, Math.min(1, (clip.source_out ?? sourceDuration) / sourceDuration));
  const from = Math.floor(start * (peaks.length - 1));
  const to = Math.max(from + 1, Math.ceil(end * (peaks.length - 1)));
  return peaks.slice(from, to);
}

export function tickStep(pxPerSec: number): number {
  if (pxPerSec >= 90) return 1;
  if (pxPerSec >= 45) return 2;
  if (pxPerSec >= 22) return 5;
  if (pxPerSec >= 12) return 10;
  if (pxPerSec >= 6) return 15;
  return 30;
}

/** Assign overlapping region effects to vertical stack rows so chips do not hide each other. */
export function stackEffects<T extends { start: number; end: number }>(effects: T[]): (T & { stack: number })[] {
  const order = [...effects].sort((left, right) => left.start - right.start || left.end - right.end);
  const rows: number[] = [];
  return order.map((effect) => {
    let stack = rows.findIndex((end) => effect.start >= end - 0.02);
    if (stack < 0) { stack = rows.length; rows.push(effect.end); }
    else rows[stack] = effect.end;
    return { ...effect, stack };
  });
}

export function clockFine(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "0:00.00";
  const minutes = Math.floor(value / 60);
  const seconds = value - minutes * 60;
  return `${minutes}:${seconds.toFixed(2).padStart(5, "0")}`;
}
