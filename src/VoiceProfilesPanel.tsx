import { useMemo, useRef, useState } from "react";
import {
  archiveVoiceProfile,
  compileVoices,
  createVoiceProfile,
  generateVoiceAvatar,
  updateVoiceProfile,
  uploadVoiceAvatar,
  voiceAvatarUrl,
  type VoiceCompileResult,
} from "./api";
import type { VoiceSlots } from "./createForm";
import { EMPTY_VOICE_PROFILE, profilesForSlot, type VoiceProfile, type VoiceRole } from "./voiceProfiles";

type Props = {
  profiles: VoiceProfile[];
  slots: VoiceSlots;
  lyrics: string;
  description: string;
  instrumental: boolean;
  coverArtReady?: boolean;
  onSlotsChange: (slots: VoiceSlots) => void;
  onReload: () => Promise<void>;
};

const bundledAvatars = import.meta.glob("./assets/voices/*.webp", { eager: true, import: "default" }) as Record<string, string>;

function avatarSrc(profile: VoiceProfile) {
  if (profile.avatar === "custom") return voiceAvatarUrl(profile.id, profile.updated_at || "");
  return bundledAvatars[`./assets/voices/${profile.id}.webp`] || "";
}

const ROLE_LABEL: Record<VoiceRole, string> = {
  female: "Female",
  male: "Male",
  backing: "Backing",
  any: "Any",
};

export default function VoiceProfilesPanel({ profiles, slots, lyrics, description, instrumental, coverArtReady, onSlotsChange, onReload }: Props) {
  const [pickerSlot, setPickerSlot] = useState<"female" | "male" | "backing" | null>(null);
  const [tab, setTab] = useState<"official" | "mine">("official");
  const [editing, setEditing] = useState<VoiceProfile | null>(null);
  const [compiled, setCompiled] = useState<VoiceCompileResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const active = profiles.filter((item) => !item.archived);
  const official = active.filter((item) => item.built_in);
  const mine = active.filter((item) => !item.built_in);
  const shown = tab === "official" ? official : mine;

  const assigned = useMemo(() => {
    const find = (id: string) => active.find((item) => item.id === id);
    return { female: find(slots.female), male: find(slots.male), backing: find(slots.backing) };
  }, [active, slots]);

  async function showCompiled() {
    setError("");
    try {
      setCompiled(await compileVoices({ slots, lyrics, description }));
    } catch (reason: any) {
      setError(reason?.message ?? String(reason));
    }
  }

  function pick(profile: VoiceProfile) {
    if (!pickerSlot) return;
    onSlotsChange({ ...slots, [pickerSlot]: profile.id });
    setPickerSlot(null);
  }

  function clearSlot(slot: "female" | "male" | "backing") {
    onSlotsChange({ ...slots, [slot]: "" });
  }

  async function saveEditor() {
    if (!editing?.name.trim()) {
      setError("Give this persona a private name.");
      return;
    }
    if (!editing.expanded.trim()) {
      setError("Describe how it sounds — husky contralto, warbling vibrato, analog warmth…");
      return;
    }
    setBusy(true); setError("");
    try {
      const payload = {
        ...editing,
        register: editing.register || editing.tag,
        expanded: editing.expanded,
      };
      const saved = editing.id
        ? (await updateVoiceProfile(editing.id, payload)).profile
        : (await createVoiceProfile(payload)).profile;
      setEditing(saved);
      await onReload();
    } catch (reason: any) {
      setError(reason?.message ?? String(reason));
    } finally { setBusy(false); }
  }

  async function onUpload(file: File) {
    if (!editing?.id) {
      setError("Save the persona first, then add a portrait.");
      return;
    }
    setBusy(true); setError("");
    try {
      const result = await uploadVoiceAvatar(editing.id, file);
      setEditing(result.profile);
      await onReload();
    } catch (reason: any) {
      setError(reason?.message ?? String(reason));
    } finally { setBusy(false); }
  }

  async function onGenerate() {
    if (!editing?.id) {
      setError("Save the persona first, then generate a portrait.");
      return;
    }
    setBusy(true); setError("");
    try {
      const result = await generateVoiceAvatar(editing.id, editing.tag || editing.expanded);
      setEditing(result.profile);
      await onReload();
    } catch (reason: any) {
      setError(reason?.message ?? String(reason));
    } finally { setBusy(false); }
  }

  async function removeProfile(id: string) {
    setBusy(true); setError("");
    try {
      await archiveVoiceProfile(id);
      const next = { ...slots };
      (["female", "male", "backing"] as const).forEach((slot) => { if (next[slot] === id) next[slot] = ""; });
      onSlotsChange(next);
      if (editing?.id === id) setEditing(null);
      await onReload();
    } catch (reason: any) {
      setError(reason?.message ?? String(reason));
    } finally { setBusy(false); }
  }

  function SlotCard({ slot, label }: { slot: "female" | "male" | "backing"; label: string }) {
    const profile = assigned[slot];
    const src = profile ? avatarSrc(profile) : "";
    return (
      <button type="button" className={`voice-slot-card ${profile ? "filled" : ""}`} onClick={() => { setPickerSlot(slot); setTab("official"); setEditing(null); setError(""); }}>
        {src ? <img src={src} alt="" /> : <span className="voice-slot-empty">+</span>}
        <strong>{label}</strong>
        <small>{profile?.name || "Choose"}</small>
        {profile && <em onClick={(event) => { event.stopPropagation(); clearSlot(slot); }}>Clear</em>}
      </button>
    );
  }

  return (
    <section className="voice-panel">
      <div className="voice-panel-head">
        <div>
          <div className="eyebrow">CHARACTERS</div>
          <strong>Choose who sings</strong>
          <p>The name stays local. YuE2 only gets the sound description — husky contralto, warbling vibrato, analog warmth.</p>
        </div>
        <button type="button" onClick={() => { setPickerSlot("female"); setTab("official"); setError(""); }}>Browse</button>
      </div>
      {instrumental
        ? <p className="voice-disabled">Instrumental songs skip characters.</p>
        : <div className="voice-slot-cards">
            <SlotCard slot="female" label="Female" />
            <SlotCard slot="male" label="Male" />
            <SlotCard slot="backing" label="Backing" />
          </div>}
      <div className="voice-preview-actions">
        <button type="button" className="ghost-link" onClick={() => void showCompiled()}>View compiled prompt</button>
        <small>{assigned.female?.name || "None"} · {assigned.male?.name || "None"} · {assigned.backing?.name || "None"}</small>
      </div>
      {compiled && <div className="compiled-prompt"><header><strong>{compiled.applied ? "What YuE2 will receive for vocals" : "No characters assigned"}</strong><button type="button" onClick={() => setCompiled(null)}>✕</button></header><pre>{compiled.preview}</pre></div>}
      {error && !pickerSlot && <div className="error">{error}</div>}

      {pickerSlot && <div className="modal-backdrop" role="presentation" onPointerDown={(event) => { if (event.target === event.currentTarget && !busy) { setPickerSlot(null); setEditing(null); } }}>
        <section className="modal-card voice-manager character-picker" role="dialog" aria-modal="true" aria-labelledby="character-title">
          <div className="modal-head"><div><div className="eyebrow">CHARACTERS</div><h2 id="character-title">Choose a character to perform your song</h2></div><button type="button" aria-label="Close" onClick={() => { setPickerSlot(null); setEditing(null); }}>✕</button></div>
          <button type="button" className="character-create-banner" onClick={() => setEditing({ ...EMPTY_VOICE_PROFILE, role: pickerSlot === "backing" ? "backing" : pickerSlot })}>
            <span>+</span> Create new character
          </button>
          <div className="character-tabs">
            <button type="button" className={tab === "official" ? "on" : ""} onClick={() => setTab("official")}>Official</button>
            <button type="button" className={tab === "mine" ? "on" : ""} onClick={() => setTab("mine")}>Mine</button>
          </div>
          <div className="character-grid">
            {shown.map((profile) => {
              const src = avatarSrc(profile);
              const selected = slots[pickerSlot] === profile.id;
              const allowed = profilesForSlot(active, pickerSlot).some((item) => item.id === profile.id);
              return (
                <button type="button" className={`character-card ${selected ? "selected" : ""}`} key={profile.id} disabled={!allowed} onClick={() => pick(profile)}>
                  {src ? <img src={src} alt="" /> : <div className="character-fallback">{profile.name.slice(0, 1)}</div>}
                  <span><strong>{profile.name}</strong><small>{profile.tag || ROLE_LABEL[profile.role]}</small></span>
                </button>
              );
            })}
            {!shown.length && <p className="modal-note">No characters in this list yet.</p>}
          </div>
          {editing && <div className="voice-editor character-editor">
            <div className="character-avatar-tools">
              <div className="character-avatar-preview">
                {avatarSrc(editing) ? <img src={avatarSrc(editing)} alt="" /> : <span>Portrait</span>}
              </div>
              <div>
                <button type="button" onClick={() => fileInput.current?.click()}>Upload image</button>
                <button type="button" disabled={busy || !coverArtReady} onClick={() => void onGenerate()}>{busy ? "Working…" : "AI generate"}</button>
                {!coverArtReady && <small>Install Cover art in Models to generate portraits, or upload one.</small>}
                <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void onUpload(file); event.target.value = ""; }} />
              </div>
            </div>
            <label>Name<input value={editing.name} maxLength={80} onChange={(event) => setEditing({ ...editing, name: event.target.value })} placeholder="Stevie — local label only" /></label>
            <label>Gender / slot<select value={editing.role} onChange={(event) => setEditing({ ...editing, role: event.target.value as VoiceRole })}>
              <option value="female">Female</option>
              <option value="male">Male</option>
              <option value="backing">Backing</option>
              <option value="any">Any</option>
            </select></label>
            <label>Vibe<input value={editing.tag || ""} maxLength={80} onChange={(event) => setEditing({ ...editing, tag: event.target.value })} placeholder="70s folk-rock · husky" /></label>
            <label>How it sounds<textarea rows={5} value={editing.expanded} onChange={(event) => setEditing({ ...editing, expanded: event.target.value })} placeholder="70s rock, folk-rock, husky raspy female vocals, smoky contralto, gravelly chest voice, distinctive warbling vibrato, raw emotional power mixed with vulnerability, dark warm tone, analog warmth" /></label>
            <p className="modal-note">YuE2 receives only this sound description — never the persona name.</p>
            <div className="modal-actions">
              {editing.id && !editing.built_in && <button type="button" className="danger" disabled={busy} onClick={() => void removeProfile(editing.id)}>Delete</button>}
              <button type="button" disabled={busy} onClick={() => setEditing(null)}>Cancel</button>
              <button type="button" className="primary" disabled={busy} onClick={() => void saveEditor()}>{busy ? "Saving…" : "Save character"}</button>
            </div>
          </div>}
          {error && <div className="error">{error}</div>}
        </section>
      </div>}
    </section>
  );
}
