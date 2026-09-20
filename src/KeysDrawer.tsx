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
  const [drafts, setDrafts] = useState<Record<string, { enabled: boolean; provider: string; model: string; key: string; base_url: string }>>({});

  const load = async () => {
    try {
      const next = await getAiKeys();
      setView(next);
      setDrafts(Object.fromEntries(ORDER.map((id) => {
        const cap = next.capabilities[id];
        const provider = cap?.provider ?? "local";
        return [id, {
          enabled: cap?.enabled ?? false,
          provider,
          model: cap?.model ?? (provider === "ollama" ? "gemma3:4b" : ""),
          key: "",
          base_url: next.providers.ollama?.base_url || "http://127.0.0.1:11434/v1",
        }];
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
      const providers: Record<string, { key?: string; base_url?: string; clear?: boolean }> = {};
      if (draft.provider === "ollama") {
        providers.ollama = { base_url: draft.base_url.trim(), key: draft.key.trim() || "ollama" };
      } else if (draft.provider !== "local" && draft.key.trim()) {
        providers[draft.provider] = { key: draft.key.trim() };
      }
      const next = await saveAiKeys({
        providers,
        capabilities: { [id]: { enabled: draft.enabled, provider: draft.provider, model: draft.model.trim() } },
      });
      setView(next);
      setDrafts((current) => ({ ...current, [id]: {
        ...draft,
        key: "",
        enabled: next.capabilities[id]?.enabled ?? draft.enabled,
        provider: next.capabilities[id]?.provider ?? draft.provider,
        model: next.capabilities[id]?.model ?? draft.model,
        base_url: next.providers.ollama?.base_url || draft.base_url,
      } }));
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
    <div className="drawer-head"><div><div className="eyebrow">API KEYS</div><h2>Helpers</h2></div><button aria-label="Close API Keys" onClick={onClose}>✕</button></div>
    <p className="drawer-note">Saving a key does nothing by itself. Check <b>Enable</b> on a category only when you want that helper. Uncheck it any time. Local YuE2, covers, and Video Studio stay the default.</p>
    {error && <div className="error">{error}</div>}
    {!view && !error && <p className="drawer-note">Loading saved keys…</p>}
    {view && ORDER.map((id) => {
      const spec = view.catalog.capabilities[id];
      const draft = drafts[id]; if (!spec || !draft) return null;
      const selected = view.providers[draft.provider];
      const isLocalLlm = draft.provider === "ollama";
      const hasKey = draft.provider === "local" ? false : Boolean(selected?.configured);
      const canEnable = draft.provider !== "local" && (isLocalLlm ? Boolean(draft.base_url.trim() || selected?.base_url) : (hasKey || Boolean(draft.key.trim())));
      return <section className="keys-category" key={id}>
        <div className="keys-category-head">
          <strong>{spec.label}</strong>
          <span>{draft.enabled ? (isLocalLlm ? "Enabled — Local LLM" : "Enabled — cloud actions can spend credits") : hasKey ? (isLocalLlm ? "Server saved · still off" : "Key saved · still off") : "Local / manual only"}</span>
        </div>
        <p>{spec.blurb}</p>
        {spec.how && <ul className="keys-how">{spec.how.rules.slice(0, 4).map((rule) => <li key={rule}>{rule}</li>)}</ul>}
        <label>Provider
          <select value={draft.provider} onChange={(event) => {
            const provider = event.target.value;
            const switchingToLocal = provider === "ollama";
            setDrafts((current) => ({ ...current, [id]: {
              ...draft,
              provider,
              enabled: provider === "local" ? false : draft.enabled,
              key: "",
              model: switchingToLocal ? (view.capabilities[id]?.provider === "ollama" ? draft.model : "gemma3:4b") : (provider === "gemini" ? "gemini-3.6-flash" : draft.model),
              base_url: switchingToLocal ? (view.providers.ollama?.base_url || draft.base_url || "http://127.0.0.1:11434/v1") : draft.base_url,
            } }));
          }}>
            {spec.providers.map((provider) => <option value={provider} key={provider}>{providerLabel(view, provider)}{provider !== "local" && view.providers[provider]?.configured ? " · saved" : ""}</option>)}
          </select>
        </label>
        <label className="switch keys-enable" title={canEnable ? (isLocalLlm ? "Allow writing via the Local LLM server" : "Allow this category to call the cloud") : (isLocalLlm ? "Save the server URL first" : "Save a cloud key first")}>
          <input type="checkbox" checked={draft.enabled} disabled={!canEnable && !draft.enabled} onChange={(event) => setDrafts((current) => ({ ...current, [id]: { ...draft, enabled: event.target.checked } }))} />
          <span />{isLocalLlm ? "Enable Local LLM writing" : `Enable cloud for ${spec.label.toLowerCase()}`}
        </label>
        <small>{isLocalLlm ? "Off = current tools only. On = one request at a time to this server. No cloud credits." : "Off = current tools only. On = you may spend this provider’s credits when you press a button."}</small>
        {isLocalLlm && <>
          <label>Server URL (Ollama IP and port)
            <input type="url" autoComplete="off" spellCheck={false} value={draft.base_url} placeholder="http://127.0.0.1:11434/v1" onChange={(event) => setDrafts((current) => ({ ...current, [id]: { ...draft, base_url: event.target.value } }))} />
          </label>
          <small>Use this computer or a private-network address, for example <code>http://192.168.x.x:11434/v1</code>. OpenAI-compatible <code>/v1</code> endpoint.</small>
          <label>Model
            <input list="ollama-lyric-models" value={draft.model} onChange={(event) => setDrafts((current) => ({ ...current, [id]: { ...draft, model: event.target.value } }))} placeholder="gemma3:4b" />
          </label>
          <datalist id="ollama-lyric-models">
            <option value="gemma3:4b">Gemma 3 4B — recommended local writer</option>
            <option value="ministral-3:8b-instruct-2512-q4_K_M">Ministral 3 8B — richer lyrics</option>
            <option value="aya-expanse:8b">Aya Expanse 8B — multilingual (non-commercial)</option>
            <option value="qwen3.5:9b">Qwen 3.5 9B — keep as fallback</option>
          </datalist>
          <small>Gemma 3 4B is the recommended Live default. Aya Expanse is CC BY-NC — personal use only.</small>
          <label>API key (optional)
            <input type="password" autoComplete="off" spellCheck={false} value={draft.key} placeholder={selected?.configured ? `Saved ·••••${selected.last4}` : "ollama"} onChange={(event) => setDrafts((current) => ({ ...current, [id]: { ...draft, key: event.target.value } }))} />
          </label>
          {selected?.configured && <button type="button" className="keys-clear" disabled={Boolean(busy)} onClick={() => void clearKey("ollama")}>Remove saved Local LLM server</button>}
        </>}
        {draft.provider !== "local" && !isLocalLlm && <>
          <label>API key
            <input type="password" autoComplete="off" spellCheck={false} value={draft.key} placeholder={selected?.configured ? `Saved ·••••${selected.last4}` : "Paste key — it is never shown again"} onChange={(event) => setDrafts((current) => ({ ...current, [id]: { ...draft, key: event.target.value } }))} />
          </label>
          <label>Model<input value={draft.model} onChange={(event) => setDrafts((current) => ({ ...current, [id]: { ...draft, model: event.target.value } }))} placeholder={draft.provider === "gemini" ? "gemini-3.6-flash" : "Default model"} /></label>
          {selected?.configured && <button type="button" className="keys-clear" disabled={Boolean(busy)} onClick={() => void clearKey(draft.provider)}>Remove saved {providerLabel(view, draft.provider)} key</button>}
        </>}
        <button type="button" className="system-action" disabled={busy === id} onClick={() => void saveCategory(id)}>{busy === id ? "Saving…" : "Save this category"}</button>
      </section>;
    })}
  </aside>;
}
