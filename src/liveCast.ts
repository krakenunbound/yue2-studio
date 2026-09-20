import { EMPTY_VOICE_SLOTS, type VoiceSlots } from "./createForm";
import type { VoiceProfile } from "./voiceProfiles";

export type LiveCast = "instrumental" | "female" | "male" | "duet" | "female-duo" | "male-duo";

export const CASTS: LiveCast[] = ["instrumental", "female", "male", "duet", "female-duo", "male-duo"];

export const CAST_ROLL: { id: LiveCast; label: string; icon: "instrumental" | "female" | "male" | "duet" | "female-duo" | "male-duo" }[] = [
  { id: "instrumental", label: "Instrumental", icon: "instrumental" },
  { id: "female", label: "Female", icon: "female" },
  { id: "male", label: "Male", icon: "male" },
  { id: "duet", label: "Duet", icon: "duet" },
  { id: "female-duo", label: "Female duo", icon: "female-duo" },
  { id: "male-duo", label: "Male duo", icon: "male-duo" },
];

export function reelVoices(pick: { cast: LiveCast; female: string; male: string; instrumental: boolean }) {
  if (pick.instrumental || pick.cast === "instrumental") return { a: "", b: "" };
  if (pick.cast === "male") return { a: pick.male, b: "" };
  if (pick.cast === "female") return { a: pick.female, b: "" };
  return { a: pick.female, b: pick.male };
}

export function randomCast(): LiveCast {
  return CASTS[Math.floor(Math.random() * CASTS.length)];
}

function pool(profiles: VoiceProfile[], role: "female" | "male") {
  return profiles.filter((profile) => !profile.archived && profile.role !== "backing" && (profile.role === role || profile.role === "any"));
}

function pickId(list: VoiceProfile[], exclude: string[] = []) {
  const choices = list.filter((profile) => !exclude.includes(profile.id));
  if (!choices.length) return "";
  return choices[Math.floor(Math.random() * choices.length)].id;
}

export function randomSlots(cast: LiveCast, profiles: VoiceProfile[]): VoiceSlots {
  const females = pool(profiles, "female");
  const males = pool(profiles, "male");
  if (cast === "instrumental") return { ...EMPTY_VOICE_SLOTS };
  if (cast === "female") return { female: pickId(females), male: "", backing: "" };
  if (cast === "male") return { female: "", male: pickId(males), backing: "" };
  if (cast === "duet") return { female: pickId(females), male: pickId(males), backing: "" };
  if (cast === "female-duo") {
    const first = pickId(females);
    return { female: first, male: pickId(females, [first]), backing: "" };
  }
  const first = pickId(males);
  return { female: first, male: pickId(males, [first]), backing: "" };
}

export function castLabel(cast: LiveCast, slots: VoiceSlots, profiles: VoiceProfile[]) {
  const name = (id: string) => profiles.find((profile) => profile.id === id)?.name || "";
  const female = name(slots.female);
  const male = name(slots.male);
  if (cast === "instrumental") return "Instrumental";
  if (cast === "female") return female ? `Female · ${female}` : "Female";
  if (cast === "male") return male ? `Male · ${male}` : "Male";
  if (cast === "duet") return `Duet · ${[female, male].filter(Boolean).join(" + ")}`;
  if (cast === "female-duo") return `Female duo · ${[female, male].filter(Boolean).join(" + ")}`;
  return `Male duo · ${[female, male].filter(Boolean).join(" + ")}`;
}

export function castHint(cast: LiveCast) {
  if (cast === "duet") return "Write a male-female duet. Tag lines [Singer A] and [Singer B].";
  if (cast === "female-duo") return "Write a two-woman duet with two different female voices. Tag lines [Singer A] and [Singer B].";
  if (cast === "male-duo") return "Write a two-man duet with two different male voices. Tag lines [Singer A] and [Singer B].";
  if (cast === "female") return "One female lead.";
  if (cast === "male") return "One male lead.";
  return "Instrumental, no sung lyrics.";
}

export function vocalGenderFor(cast: LiveCast): "auto" | "female" | "male" {
  if (cast === "female" || cast === "female-duo") return "female";
  if (cast === "male" || cast === "male-duo") return "male";
  return "auto";
}
