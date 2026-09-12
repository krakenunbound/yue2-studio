export type VoiceRole = "female" | "male" | "backing" | "any";

export type VoiceProfile = {
  id: string;
  name: string;
  role: VoiceRole;
  register: string;
  timbre: string;
  delivery: string;
  accent: string;
  vibrato: string;
  dynamics: string;
  harmony: string;
  effects: string;
  audition_notes: string;
  expanded: string;
  tag?: string;
  avatar?: string;
  built_in: boolean;
  archived: boolean;
  created_at?: string;
  updated_at?: string;
  slot?: string;
};

export const EMPTY_VOICE_PROFILE: VoiceProfile = {
  id: "",
  name: "",
  role: "any",
  register: "",
  timbre: "",
  delivery: "",
  accent: "",
  vibrato: "",
  dynamics: "",
  harmony: "",
  effects: "",
  audition_notes: "",
  expanded: "",
  tag: "",
  avatar: "",
  built_in: false,
  archived: false,
};

export function profilesForSlot(profiles: VoiceProfile[], slot: "female" | "male" | "backing"): VoiceProfile[] {
  return profiles.filter((profile) => {
    if (slot === "backing") return profile.role === "backing" || profile.role === "any";
    return profile.role === slot || profile.role === "any";
  });
}
