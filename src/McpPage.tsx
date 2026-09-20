import { useEffect, useState } from "react";
import { getMcpActivity, type McpActivity } from "./api";

export default function McpPage() {
  const [items, setItems] = useState<McpActivity[]>([]);
  const [error, setError] = useState("");
  const refresh = async () => { try { setItems((await getMcpActivity()).items); setError(""); } catch (reason: any) { setError(reason?.message ?? String(reason)); } };
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 1800); return () => window.clearInterval(timer); }, []);
  return <section className="main-view mcp-page active"><div className="eyebrow">CONNECTED LOCAL CONTROL</div><h1>Model Context Protocol</h1><p className="mcp-intro">Agents can work with YuE2 directly through its local service. This screen is the visible audit trail—no desktop-window automation is used.</p><div className="mcp-status"><span><i />Connected when YuE2 Studio is open</span><button onClick={() => void refresh()}>Refresh</button></div>{error && <p className="caption-ai-error">{error}</p>}<section className="mcp-activity"><header><strong>Live activity</strong><span>{items.length ? `${items.length} recent actions` : "Waiting for an agent"}</span></header>{items.length === 0 ? <div className="empty"><strong>No MCP actions yet</strong><span>Connected agents will appear here as they work.</span></div> : items.map((item) => <article key={item.id} className={item.status}><i /><div><strong>{item.tool}</strong><span>{item.summary}</span></div><time>{new Date(item.at * 1000).toLocaleTimeString()}</time></article>)}</section><section className="mcp-tools"><strong>Available control</strong><span>Status · Library · Generation · Jobs · Song editing · Ratings · Playlists · Voices · AI writing · Sound effects</span></section></section>;
}
