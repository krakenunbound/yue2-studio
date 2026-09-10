import { useEffect, useMemo, useState } from "react";
import { openUrl } from "@tauri-apps/plugin-opener";
import { cancelModelInstall, getModels, installModel, type DownloadableModel } from "./api";

type Props = { onChanged?: () => void };

function bytes(value: number) {
  if (value === 0) return "0 B";
  if (!Number.isFinite(value) || value < 0) return "Size will be checked before download";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value; let unit = 0;
  while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
  return `${size >= 10 || unit === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unit]}`;
}

function modelState(item: DownloadableModel) {
  if (item.ready) return "Ready";
  if (!item.runtime_ready) return "Setup needed";
  if (item.model_ready) return "Almost ready";
  return "Not installed";
}

export default function ModelsPage({ onChanged }: Props) {
  const [items, setItems] = useState<DownloadableModel[]>([]);
  const [error, setError] = useState("");
  const [tokens, setTokens] = useState<Record<string, string>>({});
  const [checking, setChecking] = useState(false);
  const running = useMemo(() => items.some((item) => item.install.status === "running"), [items]);

  const refresh = async () => {
    const response = await getModels();
    setItems(response.items);
  };

  useEffect(() => { void refresh().catch((reason) => setError(reason?.message ?? String(reason))); }, []);
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      void refresh().then(() => onChanged?.()).catch((reason) => setError(reason?.message ?? String(reason)));
    }, 900);
    return () => window.clearInterval(timer);
  }, [running]);

  async function install(item: DownloadableModel) {
    setError("");
    try {
      await installModel(item.id, tokens[item.id]?.trim() || undefined);
      setTokens((current) => ({ ...current, [item.id]: "" }));
      await refresh();
    } catch (reason: any) { setError(reason?.message ?? String(reason)); }
  }

  async function checkSpace() {
    setError(""); setChecking(true);
    try { await refresh(); }
    catch (reason: any) { setError(reason?.message ?? String(reason)); }
    finally { setChecking(false); }
  }

  async function cancel(item: DownloadableModel) {
    setError("");
    try {
      await cancelModelInstall(item.id);
      await refresh();
    } catch (reason: any) { setError(reason?.message ?? String(reason)); }
  }

  async function openTerms(url: string) {
    try { await openUrl(url); }
    catch (reason: any) { setError(reason?.message ?? String(reason)); }
  }

  const visible = items.filter((item) => !item.ready || item.install.status === "running");
  const required = visible.filter((item) => !item.optional);
  const extras = visible.filter((item) => item.optional);
  const list = (title: string, copy: string, models: DownloadableModel[]) => <section className="models-group">
    <header><div><div className="eyebrow">{title}</div><h2>{title === "REQUIRED" ? "Make music locally" : "Add optional tools"}</h2></div><p>{copy}</p></header>
    <div className="models-grid">{models.map((item) => {
      const active = item.install.status === "running";
      const insufficient = item.required_free_bytes > item.free_bytes;
      const action = item.ready ? "Repair or check" : "Download and install";
      return <article className={`model-card ${item.ready ? "ready" : ""}`} key={item.id}>
        <div className="model-card-head"><div><h3>{item.name}</h3><span className={`model-state ${item.ready ? "ready" : ""}`}>{modelState(item)}</span></div><span className={`model-kind ${item.optional ? "optional" : "required"}`}>{item.optional ? "Optional" : "Required"}</span></div>
        <p>{item.description}</p>
        <div className="model-does"><b>What it does</b><span>{item.does}</span></div>
        <dl className="model-facts"><div><dt>Estimated download</dt><dd>{bytes(item.download_bytes)}</dd></div><div><dt>Free space</dt><dd className={insufficient ? "not-enough" : ""}>{bytes(item.free_bytes)} available</dd></div><div><dt>Needed</dt><dd>{bytes(item.required_free_bytes)}</dd></div></dl>
        <p className="model-detail">{item.detail}</p>
        {active && <div className="model-progress"><div><b>{item.install.phase || "Downloading"}</b><span>{Math.round(Math.max(0, Math.min(1, item.install.progress)) * 100)}%</span></div><i><em style={{ width: `${Math.round(Math.max(0, Math.min(1, item.install.progress)) * 100)}%` }} /></i></div>}
        {item.install.status === "failed" && <div className="error">{item.install.error || "The install did not finish. You can try again."}</div>}
        {item.install.status === "succeeded" && <div className="model-result succeeded">{item.install.phase || "Install finished. This tool is ready to use."}</div>}
        {item.install.status === "cancelled" && <div className="model-result cancelled">{item.install.phase || "Download cancelled. You can resume it whenever you are ready."}</div>}
        {insufficient && <div className="truth-note">Not enough free space yet. Free up {bytes(item.required_free_bytes - item.free_bytes)}, then try again.</div>}
        {item.gated && !item.ready && <div className="model-gated"><p>This publisher requires you to accept its model terms on Hugging Face.</p>{item.source_url && <button type="button" className="model-terms-button" onClick={() => void openTerms(item.source_url!)}>Open model terms</button>}<label>Hugging Face read token <input type="password" autoComplete="off" value={tokens[item.id] ?? ""} onChange={(event) => setTokens((current) => ({ ...current, [item.id]: event.target.value }))} placeholder="Used only for this installation; not saved" /><small>Only needed if this computer does not already have a Hugging Face token.</small></label></div>}
        <p className="model-path">Installs to {item.folder}</p>
        <div className="model-actions">{active ? <button className="danger" onClick={() => void cancel(item)}>Cancel download</button> : <button className="primary" disabled={insufficient || running} onClick={() => void install(item)}>{action}</button>}</div>
      </article>;
    })}</div>
  </section>;

  return <section className="models-page main-view active">
    <header className="models-hero"><div><div className="eyebrow">LOCAL MODEL LIBRARY</div><h1>Downloads you control</h1><p>Choose which local tools to install. Each install checks free disk space first and puts its files in the folder shown below. Whisper includes English alignment; using another language may download its alignment model on first sync.</p></div><button type="button" className="models-refresh" disabled={checking || running} onClick={() => void checkSpace()}>{checking ? "Checking space…" : "Refresh and check space"}</button></header>
    {error && <div className="error">{error}</div>}
    {!items.length && !error && <div className="empty"><strong>Checking local models…</strong><span>This takes a moment the first time.</span></div>}
    {items.length > 0 && visible.length === 0 && <div className="empty"><strong>All models are installed</strong><span>There is nothing left to download.</span></div>}
    {required.length > 0 && list("REQUIRED", "YuE2 is needed to create songs. The rest are optional extras.", required)}
    {extras.length > 0 && list("OPTIONAL TOOLS", "Install these only if you want their features. Installed models are hidden.", extras)}
  </section>;
}
