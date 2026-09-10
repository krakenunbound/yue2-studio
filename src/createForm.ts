/** Create-page defaults and dirty detection. Does not touch saved library items. */

export const SAMPLE_DESCRIPTION =
  "A cinematic alternative rock song with an intimate opening, expressive lead vocal, live drums, bass and electric guitars, building through a wide chorus into an evolving bridge and resolved outro.";

export const DEFAULT_LYRICS = "[Verse]\n\n[Chorus]\n\n[Bridge]\n\n[Outro]";

export type VoiceSlots = {
  female: string;
  male: string;
  backing: string;
};

export const EMPTY_VOICE_SLOTS: VoiceSlots = { female: "", male: "", backing: "" };

export type CreateFormSnapshot = {
  title: string;
  artist: string;
  album: string;
  genre: string;
  description: string;
  lyrics: string;
  englishTranslation: string;
  lyricsLanguage: string;
  instrumental: boolean;
  excludeStyles: string;
  vocalGender: "auto" | "female" | "male";
  cotMode: "full" | "melody" | "off";
  abcScore: string;
  cfg: number;
  steps: number;
  topK: number;
  temperature: number;
  lockedSeed: string;
  voiceSlots: VoiceSlots;
};

export function defaultCreateForm(artist = ""): CreateFormSnapshot {
  return {
    title: "",
    artist,
    album: "",
    genre: "",
    description: SAMPLE_DESCRIPTION,
    lyrics: DEFAULT_LYRICS,
    englishTranslation: "",
    lyricsLanguage: "en",
    instrumental: false,
    excludeStyles: "",
    vocalGender: "auto",
    cotMode: "full",
    abcScore: "",
    cfg: 1.0,
    steps: 32,
    topK: 100,
    temperature: 1.0,
    lockedSeed: "",
    voiceSlots: { ...EMPTY_VOICE_SLOTS },
  };
}

export function lyricsHaveWords(lyrics: string): boolean {
  return Boolean(lyrics.replace(/\[[^\]]+\]/g, "").trim());
}

export function needsAutoTitle(title: string): boolean {
  const value = title.trim();
  return !value || value.toLowerCase() === "untitled song" || value.toLowerCase() === "untitled";
}

export function voiceSlotsAssigned(slots: VoiceSlots): boolean {
  return Boolean(slots.female || slots.male || slots.backing);
}

/** True when the form has meaningful unsaved work worth confirming before reset. */
export function isCreateFormDirty(form: CreateFormSnapshot, defaultArtist = ""): boolean {
  if (form.title.trim() && form.title.trim() !== "Untitled Song") return true;
  if (form.artist.trim() !== defaultArtist.trim()) return true;
  if (form.album.trim() || form.genre.trim()) return true;
  if (form.description.trim() && form.description.trim() !== SAMPLE_DESCRIPTION) return true;
  if (lyricsHaveWords(form.lyrics)) return true;
  if (form.englishTranslation.trim() || form.excludeStyles.trim() || form.lockedSeed.trim()) return true;
  if (form.lyricsLanguage !== "en" || form.instrumental) return true;
  if (form.cotMode !== "full" || form.abcScore.trim() || form.cfg !== 1.0 || form.steps !== 32 || form.topK !== 100 || form.temperature !== 1.0) return true;
  if (form.vocalGender !== "auto") return true;
  if (voiceSlotsAssigned(form.voiceSlots)) return true;
  return false;
}
