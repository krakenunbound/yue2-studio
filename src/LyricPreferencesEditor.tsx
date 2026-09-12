import { useEffect, useState } from "react";
import { getLyricPreferences, saveLyricPreferences } from "./api";

export default function LyricPreferencesEditor({ onDirtyChange, expanded = false }: { onDirtyChange?: (dirty: boolean) => void; expanded?: boolean }) {
  const [text, setText] = useState("");
  const [saved, setSaved] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => { let active = true; void getLyricPreferences().then((value) => { if (active) { setText(value.avoid); setSaved(value.avoid); setLoaded(true); } }).catch((error) => { if (active) setMessage(error.message); }); return () => { active = false; }; }, []);
  const dirty = text !== saved;
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  const save = async () => {
    setBusy(true); setMessage("");
    try { const value = await saveLyricPreferences(text); setText(value.avoid); setSaved(value.avoid); setMessage("Saved for future lyric writing with every provider."); }
    catch (error: any) { setMessage(error.message); }
    finally { setBusy(false); }
  };
  return <details className="keys-category" open={expanded || undefined}><summary>Avoid in lyrics</summary>
    <p>Your personal words, phrases and writing habits to avoid. Use one entry per line. Applies to new lyrics and rewrites, including Easy mode; existing songs are not changed.</p>
    <label>Words, phrases and habits<textarea rows={7} maxLength={12000} disabled={!loaded || busy} value={text} onChange={(event) => setText(event.target.value)} placeholder={'Example entries (not active unless you add them):\nneon\nechoes of the past\nDo not start every chorus with "we rise".'} /></label>
    <button type="button" disabled={!loaded || busy || !dirty} onClick={() => void save()}>{busy ? "Saving..." : "Save avoid list"}</button>
    {dirty && <small>Save this list before asking the helper to write.</small>}
    <small>Clear and save to disable. The list is sent with lyric prompts; review the result because AI can still miss a rule.</small>
    {message && <p role="status">{message}</p>}
  </details>;
}
