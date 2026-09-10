import { useEffect, useState } from "react";
import { getAiKeys, saveAiKeys, type AiKeysView } from "./api";

const ORDER = ["writing", "images", "video"] as const;

function providerLabel(view: AiKeysView, id: string) {
  if (id === "local") return "Local (no cloud)";
  return view.catalog.providers[id]?.label ?? view.providers[id]?.label ?? id;
}

export default function KeysDrawer({
  open, onClose, width, onResizeStart,
}: { open: boolean; onClose: () => void; width: number; onResizeStart: (event: React.PointerEvent) => void }) {
  const [view, setView] = useState<AiKeysView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [drafts, setDrafts] = useState<Record<string, { enabled: boolean; provider: string; model: string; key: string }>>({});

  const load = async () => {
    try {
      const next = await getAiKeys();
      setView(next);
      setDrafts(Object.fromEntries(ORDER.map((id) => {
        const cap = next.capabilities[id];
        return [id, { enabled: cap?.enabled ?? false, provider: cap?.provider ?? "local", model: cap?.model ?? "", key: "" }];
      })));
      setError("");
    } catch (reason: any) {
      setError(reason?.message ?? String(reason));
    }
  };

  useEffect(() => { if (open) void load(); }, [open]);

  if (!open) return null;

  const saveCategory = async (id: string) => {
    const draft = drafts[id]; if (!draft || !view) return;
    setBusy(id); setError("");
    try {
      const providers: Record<string, { key?: string; clear?: boolean }> = {};
      if (draft.provider !== "local" && draft.key.trim()) providers[draft.provider] = { key: draft.key.trim() };
      const next = await saveAiKeys({
        providers,
        capabilities: { [id]: { enabled: draft.enabled, provider: draft.provider, model: draft.model.trim() } },
      });
      setView(next);
      setDrafts((current) => ({ ...current, [id]: { ...draft, key: "", enabled: next.capabilities[id]?.enabled ?? draft.enabled } }));
    } catch (reason: any) {
      setError(reason?.message ?? String(reason));
    } finally { setBusy(""); }
  };

  const clearKey = async (provider: string) => {
    setBusy(provider); setError("");
    try {
      const next = await saveAiKeys({ providers: { [provider]: { clear: true } } });
      setView(next);
      await load();
    } catch (reason: any) {
      setError(reason?.message ?? String(reason));
    } finally { setBusy(""); }
  };

  return <aside className="keys-drawer left-drawer" style={{ width }}>
    <div className="drawer-resizer right" role="separator" aria-label="Resize API Keys panel" onPointerDown={onResizeStart} />
    <div className="drawer-head"><div><div className="eyebrow">API KEYS</div><h2>Cloud helpers</h2></div><button aria-label="Close API Keys" onClick={onClose}>✕</button></div>
    <p className="drawer-note">Saving a key does nothing by itself. Check <b>Enable</b> on a category only when you want to spend that provider’s credits. Uncheck it any time. Local YuE2, covers, and Video Studio stay the default.</p>
    {error && <div className="error">{error}</div>}
    {!view && !error && <p className="drawer-note">Loading saved keys…</p>}
    {view && ORDER.map((id) => {
      const spec = view.catalog.capabilities[id];
      const draft = drafts[id]; if (!spec || !draft) return null;
      const selected = view.providers[draft.provider];
      const hasKey = draft.provider === "local" ? false : Boolean(selected?.configured);
      const canEnable = draft.provider !== "local" && (hasKey || Boolean(draft.key.trim()));
      return <section className="keys-category" key={id}>
        <div className="keys-category-head">
          <strong>{spec.label}</strong>
          <span>{draft.enabled ? "Enabled — cloud actions can spend credits" : hasKey ? "Key saved · still off" : "Local / manual only"}</span>
        </div>
        <p>{spec.blurb}</p>
        {spec.how && <ul className="keys-how">{spec.how.rules.slice(0, 4).map((rule) => <li key={rule}>{rule}</li>)}</ul>}
        <label className="switch keys-enable" title={canEnable ? "Allow this category to call the cloud" : "Save a cloud key first"}>
          <input type="checkbox" checked={draft.enabled} disabled={!canEnable && !draft.enabled} onChange={(event) => setDrafts((current) => ({ ...current, [id]: { ...draft, enabled: event.target.checked } }))} />
          <span />Enable cloud for {spec.label.toLowerCase()}
        </label>
        <small>Off = current tools only. On = you may spend this provider’s credits when you press a button.</small>
        <label>Provider
          <select value={draft.provider} onChange={(event) => {
            const provider = event.target.value;
            setDrafts((current) => ({ ...current, [id]: { ...draft, provider, enabled: provider === "local" ? false : draft.enabled, key: "" } }));
          }}>
            {spec.providers.map((provider) => <option value={provider} key={provider}>{providerLabel(view, provider)}{provider !== "local" && view.providers[provider]?.configured ? " · saved" : ""}</option>)}
          </select>
        </label>
        {draft.provider !== "local" && <>
          <label>API key
            <input type="password" autoComplete="off" spellCheck={false} value={draft.key} placeholder={selected?.configured ? `Saved ·••••${selected.last4}` : "Paste key — it is never shown again"} onChange={(event) => setDrafts((current) => ({ ...current, [id]: { ...draft, key: event.target.value } }))} />
          </label>
          <label>Model<input value={draft.model} onChange={(event) => setDrafts((current) => ({ ...current, [id]: { ...draft, model: event.target.value } }))} placeholder={draft.provider === "gemini" ? "gemini-3.5-flash" : "Default model"} /></label>
          {selected?.configured && <button type="button" className="keys-clear" disabled={Boolean(busy)} onClick={() => void clearKey(draft.provider)}>Remove saved {providerLabel(view, draft.provider)} key</button>}
        </>}
        <button type="button" className="system-action" disabled={busy === id} onClick={() => void saveCategory(id)}>{busy === id ? "Saving…" : "Save this category"}</button>
      </section>;
    })}
  </aside>;
}
