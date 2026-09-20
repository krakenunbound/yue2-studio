import type { Song } from "./api";

export const EQ_BANDS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000] as const;
export const EQ_BAND_LABELS = ["32", "64", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"];
export const EQ_FLAT = EQ_BANDS.map(() => 0);

export const EQ_PRESETS: Record<string, number[]> = {
  Flat: EQ_FLAT,
  Bass: [7, 5, 3, 1, 0, 0, -1, -2, -2, -1],
  Treble: [-2, -2, -1, 0, 0, 1, 3, 5, 6, 6],
  Vocal: [-3, -2, 0, 2, 4, 3, 1, 0, -1, -2],
  Electronic: [5, 4, 1, -2, -2, 0, 2, 3, 4, 5],
  Rock: [4, 3, 1, 0, -2, 0, 2, 3, 4, 3],
  Jazz: [3, 2, 0, -2, -2, -1, 0, 2, 3, 4],
  Acoustic: [3, 2, 0, 1, 2, 1, 0, 2, 3, 2],
  Night: [4, 3, 1, -3, -4, -2, 0, 1, 3, 2],
  Loudness: [6, 4, 0, -3, -4, -2, 0, 2, 4, 5],
};

export function automaticPreset(song: Song | null) {
  if (!song) return "Flat";
  const genre = (song.genre || "").toLowerCase();
  const details = `${song.description || ""} ${song.title || ""}`.toLowerCase();
  const profileFor = (text: string) => {
    if (/edm|electronic|techno|house|trance|drum\s*(&|and)\s*bass|\bdnb\b/.test(text)) return "Electronic";
    if (/rock|metal|punk|grunge/.test(text)) return "Rock";
    if (/jazz/.test(text)) return "Jazz";
    if (/acoustic|folk|orchestra|classical|bluegrass|country/.test(text)) return "Acoustic";
    if (/reggae|hip[- ]?hop|rap|trap|phonk|afrobeat|funk/.test(text)) return "Bass";
    if (/ambient|lullaby|cinematic|soundtrack/.test(text)) return "Night";
    if (!song.instrumental && /pop|r&b|rnb|soul|vocal|gospel/.test(text)) return "Vocal";
    return "";
  };
  return profileFor(genre) || profileFor(details) || "Flat";
}
