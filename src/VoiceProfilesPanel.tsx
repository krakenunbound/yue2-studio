import { useMemo, useRef, useState } from "react";
import {
  archiveVoiceProfile,
  compileVoices,
  createVoiceProfile,
  duplicateVoiceProfile,
  importVoiceProfiles,
  updateVoiceProfile,
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
  onSlotsChange: (slots: VoiceSlots) => void;
  onReload: () => Promise<void>;
};

const TRAIT_FIELDS: Array<[keyof VoiceProfile, string, string]> = [
  ["register", "Register", "alto, tenor, mezzo…"],
  ["timbre", "Timbre", "close, smoky, weathered…"],
  ["delivery", "Delivery", "intimate verses, open chorus…"],
  ["accent", "Accent / dialect", "optional local color, not a celebrity name"],
  ["vibrato", "Vibrato", "minimal, controlled…"],
  ["dynamics", "Dynamics", "how loud and close it sits"],
  ["harmony", "Harmony behavior", "when support enters"],
  ["effects", "Vocal FX", "dry, room, no choir stack…"],
];

export default function VoiceProfilesPanel({ profiles, slots, lyrics, description, instrumental, onSlotsChange, onReload }: Props) {
  const [managerOpen, setManagerOpen] = useState(false);
  const [editing, setEditing] = useState<VoiceProfile | null>(null);
  const [compiled, setCompiled] = useState<VoiceCompileResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const importInput = useRef<HTMLInputElement>(null);
  const active = profiles.filter((item) => !item.archived);

  const assignedNames = useMemo(() => {
    const find = (id: string) => active.find((item) => item.id === id)?.name;
    return {
      female: find(slots.female) || "None",
      male: find(slots.male) || "None",
      backing: find(slots.backing) || "None",
    };
  }, [active, slots]);

  async function showCompiled() {
    setError("");
    try {
      const result = await compileVoices({ slots, lyrics, description });
      setCompiled(result);
    } catch (reason: any) {
      setError(reason?.message ?? String(reason));
    }
  }

  async function saveEditor() {
    if (!editing?.name.trim()) {
      setError("Give this prompt voice a private name.");
      return;
    }
    setBusy(true); setError("");
    try {
      if (editing.id) await updateVoiceProfile(editing.id, editing);
      else await createVoiceProfile(editing);
      setEditing(null);
      await onReload();
    } catch (reason: any) {
      setError(reason?.message ?? String(reason));
    } finally { setBusy(false); }
  }

  async function copyProfile(id: string) {
    setBusy(true); setError("");
    try {
      await duplicateVoiceProfile(id);
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
      await onReload();
    } catch (reason: any) {
      setError(reason?.message ?? String(reason));
    } finally { setBusy(false); }
  }

  async function importFile(file: File) {
    setBusy(true); setError("");
    try {
      const parsed = JSON.parse(await file.text());
      const items = Array.isArray(parsed) ? parsed : parsed.profiles;
      if (!Array.isArray(items)) throw new Error("That file is not a prompt-voice export.");
      await importVoiceProfiles(items);
      await onReload();
    } catch (reason: any) {
      setError(reason?.message ?? String(reason));
    } finally { setBusy(false); }
  }

  function exportFile() {
    const blob = new Blob([JSON.stringify({ version: 1, profiles }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "yue2-prompt-voices.json";
    link.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section className="voice-panel">
      <div className="voice-panel-head">
        <div>
          <div className="eyebrow">PROMPT VOICES</div>
          <strong>Reusable singers, compiled off-screen</strong>
          <p>Names stay private. YuE2 only receives Singer A / Singer B traits. Vocal gender can stay Auto.</p>
        </div>
        <button type="button" onClick={() => { setManagerOpen(true); setError(""); }}>Manage voices</button>
      </div>
      {instrumental
        ? <p className="voice-disabled">Instrumental songs skip prompt voices.</p>
        : <div className="voice-slots">
            {(["female", "male", "backing"] as const).map((slot) => (
              <label key={slot}>{slot === "backing" ? "Backing" : slot === "female" ? "Female" : "Male"}
                <select value={slots[slot]} onChange={(event) => onSlotsChange({ ...slots, [slot]: event.target.value })}>
                  <option value="">None</option>
                  {profilesForSlot(active, slot).map((profile) => <option value={profile.id} key={profile.id}>{profile.name}</option>)}
                </select>
              </label>
            ))}
          </div>}
      <div className="voice-preview-actions">
        <button type="button" className="ghost-link" onClick={() => void showCompiled()}>View compiled prompt</button>
        <small>{assignedNames.female} · {assignedNames.male} · {assignedNames.backing}</small>
      </div>
      {compiled && <div className="compiled-prompt"><header><strong>{compiled.applied ? "What YuE2 will receive for vocals" : "No prompt voices assigned"}</strong><button type="button" onClick={() => setCompiled(null)}>✕</button></header><pre>{compiled.preview}</pre></div>}
      {error && !managerOpen && <div className="error">{error}</div>}

      {managerOpen && <div className="modal-backdrop" role="presentation" onPointerDown={(event) => { if (event.target === event.currentTarget && !busy) { setManagerOpen(false); setEditing(null); } }}>
        <section className="modal-card voice-manager" role="dialog" aria-modal="true" aria-labelledby="voice-manager-title">
          <div className="modal-head"><div><div className="eyebrow">PROMPT VOICES</div><h2 id="voice-manager-title">Saved vocal recipes</h2></div><button type="button" aria-label="Close" onClick={() => { setManagerOpen(false); setEditing(null); }}>✕</button></div>
          <p className="modal-note">The name is only a local label. Never put a real-person identity in the traits you send to YuE2.</p>
          <div className="voice-manager-actions">
            <button type="button" className="primary" onClick={() => setEditing({ ...EMPTY_VOICE_PROFILE, role: "female" })}>New voice</button>
            <button type="button" onClick={exportFile}>Export JSON</button>
            <button type="button" onClick={() => importInput.current?.click()}>Import JSON</button>
            <input ref={importInput} type="file" accept="application/json" hidden onChange={(event) => { const file = event.target.files?.[0]; if (file) void importFile(file); event.target.value = ""; }} />
          </div>
          <div className="voice-list">
            {profiles.map((profile) => (
              <article key={profile.id} className={profile.archived ? "archived" : ""}>
                <div><strong>{profile.name}</strong><small>{profile.role}{profile.built_in ? " · built-in" : ""}{profile.archived ? " · archived" : ""}</small><span>{profile.expanded || profile.timbre || "No traits yet"}</span></div>
                <div className="voice-list-actions">
                  <button type="button" onClick={() => setEditing({ ...profile })}>Edit</button>
                  <button type="button" onClick={() => void copyProfile(profile.id)}>Duplicate</button>
                  {!profile.archived && <button type="button" className="danger" onClick={() => void removeProfile(profile.id)}>{profile.built_in ? "Archive" : "Delete"}</button>}
                </div>
              </article>
            ))}
          </div>
          {editing && <div className="voice-editor">
            <label>Private name<input value={editing.name} maxLength={80} onChange={(event) => setEditing({ ...editing, name: event.target.value })} placeholder="Stevie, Chris — local only" /></label>
            <label>Role<select value={editing.role} onChange={(event) => setEditing({ ...editing, role: event.target.value as VoiceRole })}>
              <option value="female">Female lead slot</option>
              <option value="male">Male lead slot</option>
              <option value="backing">Backing</option>
              <option value="any">Any slot</option>
            </select></label>
            {TRAIT_FIELDS.map(([key, label, placeholder]) => (
              <label key={key}>{label}<input value={String(editing[key] || "")} onChange={(event) => setEditing({ ...editing, [key]: event.target.value })} placeholder={placeholder} /></label>
            ))}
            <label>Expanded trait sentence<textarea rows={3} value={editing.expanded} onChange={(event) => setEditing({ ...editing, expanded: event.target.value })} placeholder="Sent to YuE2. Do not include the private name." /></label>
            <label>Audition notes<textarea rows={2} value={editing.audition_notes} onChange={(event) => setEditing({ ...editing, audition_notes: event.target.value })} placeholder="Remind yourself when to use this voice" /></label>
            <div className="modal-actions"><button type="button" disabled={busy} onClick={() => setEditing(null)}>Cancel</button><button type="button" className="primary" disabled={busy} onClick={() => void saveEditor()}>{busy ? "Saving…" : "Save voice"}</button></div>
          </div>}
          {error && <div className="error">{error}</div>}
        </section>
      </div>}
    </section>
  );
}
