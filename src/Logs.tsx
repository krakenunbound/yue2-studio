import { useEffect, useRef, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { clearLogs, getLogs, type LogEntry } from "./api";

// Rendering thousands of rows with no virtualization is what makes this panel
// crawl while a song generates. 600 is plenty of scrollback to debug with.
const MAX_ROWS = 600;

export default function Logs({ open, onClose, width, onResizeStart }: { open: boolean; onClose: () => void; width: number; onResizeStart: (event: React.PointerEvent) => void }) {
  const [items, setItems] = useState<LogEntry[]>([]);
  // lastId lives in a ref, not state. As a dependency it tore down and rebuilt
  // the poll interval on every batch that arrived -- and each rebuild fired an
  // immediate refresh, so during generation this polled far faster than 1.2s.
  const lastId = useRef(-1);
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    let disposed = false;
    let inFlight = false;
    const refresh = async () => {
      if (inFlight) return;   // never stack requests on a slow sidecar
      inFlight = true;
      try {
        const result = await getLogs(lastId.current < 0 ? undefined : lastId.current);
        if (!disposed && (result.items.length || result.reset)) {
          setItems((current) => (result.reset ? result.items : [...current, ...result.items]).slice(-MAX_ROWS));
          lastId.current = result.last_id;
        }
      } catch { /* sidecar may be restarting */ }
      finally { inFlight = false; }
    };
    void refresh(); const timer = window.setInterval(refresh, 1200);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [open]);
  useEffect(() => {
    if (!("__TAURI_INTERNALS__" in window)) return;
    const unlisten = listen("sidecar-restarted", () => { setItems([]); lastId.current = -1; });
    return () => { void unlisten.then((stop) => stop()); };
  }, []);
  useEffect(() => { if (list.current) list.current.scrollTop = list.current.scrollHeight; }, [items]);
  if (!open) return null;
  return <div className="logs-drawer left-drawer" style={{ width }}>
    <div className="drawer-resizer right" role="separator" aria-label="Resize log panel" onPointerDown={onResizeStart} />
    <div className="logs-bar"><strong>LOCAL GENERATION LOG</strong><span className="spacer" />
      <button onClick={() => navigator.clipboard.writeText(items.map((x) => x.message).join("\n"))}>Copy</button>
      <button onClick={() => { void clearLogs(); setItems([]); lastId.current = -1; }}>Clear</button><button onClick={onClose}>Close</button>
    </div>
    <div className="logs-list" ref={list}>{items.length === 0 && <div className="muted">No log entries yet.</div>}{items.map((item) => <div className={`log-row ${item.level.toLowerCase()}`} key={item.id}><span>{new Date(item.ts * 1000).toLocaleTimeString()}</span><b>{item.level}</b><code>{item.message}</code></div>)}</div>
  </div>;
}
