import { useEffect, useMemo, useRef, useState } from "react";
import { type Playlist, type Song, type Workspace } from "./api";

const BANDS = [32, 64, 125, 250, 500, 1000, 2000, 4000, 8000, 16000] as const;
const BAND_LABELS = ["32", "64", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"];
const FLAT = BANDS.map(() => 0);

const EQ_PRESETS: Record<string, number[]> = {
  Flat: FLAT,
  Bass: [7, 5, 3, 1, 0, 0, -1, -2, -2, -1],
  Treble: [-2, -2, -1, 0, 0, 1, 3, 5, 6, 6],
  Vocal: [-3, -2, 0, 2, 4, 3, 1, 0, -1, -2],
  Electronic: [5, 4, 1, -2, -2, 0, 2, 3, 4, 5],
  Rock: [4, 3, 1, 0, -2, 0, 2, 3, 4, 3],
  Jazz: [3, 2, 0, -2, -2, -1, 0, 2, 3, 4],
  Acoustic: [3, 2, 0, 1, 2, 1, 0, 2, 3, 2],
  Night: [4, 3, 1, -3, -4, -2, 0, 1, 3, 2],
  Loudness: [6, 4, 0, -3, -4, -2, 0, 2, 4, 5],
};

function radioSrc(song: Song) {
  const path = song.audio_url.split("?")[0];
  if ("__TAURI_INTERNALS__" in window) return `http://127.0.0.1:7794${path}`;
  return `${window.location.origin}${path}`;
}

function clock(value: number) {
  const seconds = Math.max(0, Math.floor(value || 0));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

type RepeatMode = "off" | "all" | "one";
type Props = { songs: Song[]; playlists: Playlist[]; workspaces: Workspace[]; coverSources: Record<string, string>; onLeaveLibraryPlay: () => void };

export default function RadioPage({ songs, playlists, workspaces, coverSources, onLeaveLibraryPlay }: Props) {
  const audio = useRef<HTMLAudioElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const graph = useRef<{ context: AudioContext; filters: BiquadFilterNode[]; analyser: AnalyserNode } | null>(null);
  const [sourceKey, setSourceKey] = useState(() => localStorage.getItem("yue2-radio-source") || "all");
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [shuffle, setShuffle] = useState(false);
  const [repeat, setRepeat] = useState<RepeatMode>("all");
  const [gains, setGains] = useState<number[]>(() => {
    try { return JSON.parse(localStorage.getItem("yue2-radio-eq") || "null") || FLAT.slice(); }
    catch { return FLAT.slice(); }
  });
  const [preset, setPreset] = useState("Flat");
  const [eqLive, setEqLive] = useState(false);
  const [error, setError] = useState("");
  const blobUrl = useRef<string | null>(null);
  const wantPlay = useRef(false);

  const queue = useMemo(() => {
    if (sourceKey.startsWith("playlist:")) {
      const list = playlists.find((item) => item.id === sourceKey.slice(9));
      const ids = new Set(list?.song_ids || []);
      return songs.filter((song) => ids.has(song.id));
    }
    if (sourceKey.startsWith("workspace:")) {
      const space = workspaces.find((item) => item.id === sourceKey.slice(10));
      const ids = new Set(space?.song_ids || []);
      return songs.filter((song) => ids.has(song.id));
    }
    return songs;
  }, [songs, playlists, workspaces, sourceKey]);

  const current = queue[Math.min(index, Math.max(0, queue.length - 1))] || null;

  useEffect(() => { localStorage.setItem("yue2-radio-source", sourceKey); }, [sourceKey]);
  useEffect(() => { localStorage.setItem("yue2-radio-eq", JSON.stringify(gains)); }, [gains]);
  useEffect(() => { if (index >= queue.length) setIndex(0); }, [queue.length, index]);

  useEffect(() => {
    onLeaveLibraryPlay();
    const element = audio.current;
    if (!element) return;
    graph.current?.context.close().catch(() => undefined);
    graph.current = null;
    if (blobUrl.current) { URL.revokeObjectURL(blobUrl.current); blobUrl.current = null; }
    setEqLive(false);
    if (!current) { element.removeAttribute("src"); element.load(); setPlaying(false); return; }
    const src = radioSrc(current);
    if (element.getAttribute("src") !== src) element.src = src;
    element.volume = volume;
    setError("");
  }, [current?.id, current?.audio_url]);

  useEffect(() => {
    graph.current?.filters.forEach((filter, band) => { filter.gain.value = gains[band] ?? 0; });
  }, [gains]);

  useEffect(() => {
    const element = audio.current; const surface = canvas.current;
    if (!element || !surface) return;
    const paint = surface.getContext("2d");
    const data = new Uint8Array(128);
    let frame = 0;
    const draw = () => {
      frame = requestAnimationFrame(draw);
      const analyser = graph.current?.analyser;
      if (analyser) analyser.getByteFrequencyData(data);
      const ratio = window.devicePixelRatio || 1;
      const width = surface.clientWidth; const height = surface.clientHeight;
      if (surface.width !== width * ratio || surface.height !== height * ratio) {
        surface.width = width * ratio; surface.height = height * ratio; paint?.setTransform(ratio, 0, 0, ratio, 0, 0);
      }
      if (!paint) return;
      paint.clearRect(0, 0, width, height);
      const bars = 48; const gap = 3; const barWidth = Math.max(2, (width - gap * (bars - 1)) / bars);
      const gradient = paint.createLinearGradient(0, height, width, 0);
      gradient.addColorStop(0, "#55e6ee"); gradient.addColorStop(0.55, "#7d65f4"); gradient.addColorStop(1, "#b654ff");
      paint.fillStyle = gradient;
      const t = element.currentTime || 0;
      for (let i = 0; i < bars; i += 1) {
        const sample = analyser ? data[Math.floor(i * data.length / bars)] / 255 : (element.paused ? 0.08 : Math.abs(Math.sin(t * 5.5 + i * 0.37)) * 0.7);
        paint.fillRect(i * (barWidth + gap), height - Math.max(2, sample * height), barWidth, Math.max(2, sample * height));
      }
    };
    draw();
    return () => cancelAnimationFrame(frame);
  }, [current?.id]);

  useEffect(() => {
    const element = audio.current; if (!element) return;
    const onTime = () => setCurrentTime(element.currentTime || 0);
    const onMeta = () => setDuration(Number.isFinite(element.duration) ? element.duration : 0);
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);
    const onEnded = () => {
      if (repeat === "one") { element.currentTime = 0; void element.play(); return; }
      go(1, true);
    };
    element.addEventListener("timeupdate", onTime);
    element.addEventListener("durationchange", onMeta);
    element.addEventListener("loadedmetadata", onMeta);
    element.addEventListener("play", onPlay);
    element.addEventListener("pause", onPause);
    element.addEventListener("ended", onEnded);
    return () => {
      element.removeEventListener("timeupdate", onTime);
      element.removeEventListener("durationchange", onMeta);
      element.removeEventListener("loadedmetadata", onMeta);
      element.removeEventListener("play", onPlay);
      element.removeEventListener("pause", onPause);
      element.removeEventListener("ended", onEnded);
    };
  }, [repeat, queue.length, shuffle, index]);

  function go(step: number, fromEnd = false) {
    if (!queue.length) return;
    let next = index + step;
    if (shuffle && queue.length > 1) {
      next = Math.floor(Math.random() * queue.length);
      if (next === index) next = (next + 1) % queue.length;
    } else {
      if (next >= queue.length) {
        if (repeat === "all" || fromEnd) next = 0;
        else { wantPlay.current = false; audio.current?.pause(); return; }
      }
      if (next < 0) next = repeat === "all" ? queue.length - 1 : 0;
    }
    if (wantPlay.current) startTrack(next);
    else setIndex(next);
  }

  function startTrack(songIndex: number) {
    const song = queue[songIndex];
    if (!song) return;
    wantPlay.current = true;
    setIndex(songIndex);
    const element = audio.current;
    if (!element) return;
    const src = radioSrc(song);
    if (element.getAttribute("src") !== src) element.src = src;
    element.volume = volume;
    void element.play().catch((reason) => setError(reason instanceof Error ? reason.message : "Could not start Radio playback."));
  }

  function toggle() {
    const element = audio.current; if (!element) return;
    if (element.paused) startTrack(index);
    else { wantPlay.current = false; element.pause(); }
  }

  function applyPreset(name: string) {
    setPreset(name);
    setGains((EQ_PRESETS[name] || FLAT).slice());
  }

  function setBand(band: number, value: number) {
    setPreset("Custom");
    setGains((current) => current.map((gain, index) => index === band ? value : gain));
  }

  return <section className="radio-station">
    <div className="library-head"><div><div className="eyebrow">RADIO</div><h2>Station</h2></div><span>{queue.length} tracks</span></div>
    <div className="radio-layout">
      <aside className="radio-queue card">
        <label>Source
          <select value={sourceKey} onChange={(event) => { setSourceKey(event.target.value); setIndex(0); }}>
            <option value="all">All songs</option>
            {workspaces.map((space) => <option key={space.id} value={`workspace:${space.id}`}>{space.name} (workspace)</option>)}
            {playlists.map((list) => <option key={list.id} value={`playlist:${list.id}`}>{list.name} (playlist)</option>)}
          </select>
        </label>
        <div className="radio-track-list">
          {queue.length === 0 && <p className="modal-note">No songs in this source yet. Generate some in Create, or add tracks to a playlist.</p>}
          {queue.map((song, songIndex) => <button key={song.id} type="button" className={`radio-track ${song.id === current?.id ? "active" : ""}`} onClick={() => startTrack(songIndex)}>
            <img src={coverSources[song.id] || ""} alt="" />
            <span><strong>{song.title}</strong><small>{clock(song.duration || 0)}</small></span>
          </button>)}
        </div>
      </aside>
      <div className="radio-stage card">
        {current ? <>
          <div className="radio-now">
            {coverSources[current.id] ? <img src={coverSources[current.id]} alt="" /> : <div className="radio-now-empty">♫</div>}
            <div><div className="eyebrow">NOW PLAYING</div><h3>{current.title}</h3><p>{current.instrumental ? "Instrumental" : "Vocal"}{current.genre ? ` · ${current.genre}` : ""}</p></div>
          </div>
          <canvas ref={canvas} className="radio-viz" />
          <audio key={current.id} ref={audio} preload="auto" />
          <div className="radio-transport">
            <button type="button" onClick={() => go(-1)} title="Previous">⏮</button>
            <button type="button" className="primary" onClick={toggle}>{playing ? "Pause" : "Play"}</button>
            <button type="button" onClick={() => go(1)} title="Next">⏭</button>
            <button type="button" className={shuffle ? "active" : ""} onClick={() => setShuffle((value) => !value)} title="Shuffle">Shuffle</button>
            <button type="button" className={repeat !== "off" ? "active" : ""} onClick={() => setRepeat((value) => value === "off" ? "all" : value === "all" ? "one" : "off")} title="Repeat">{repeat === "one" ? "Repeat one" : repeat === "all" ? "Repeat all" : "Repeat off"}</button>
          </div>
          <div className="radio-seek">
            <time>{clock(currentTime)}</time>
            <input type="range" min={0} max={Math.max(duration, 0.01)} step="0.01" value={Math.min(currentTime, duration || 0)} onChange={(event) => { const value = Number(event.target.value); if (audio.current) audio.current.currentTime = value; setCurrentTime(value); }} />
            <time>{clock(duration || current.duration || 0)}</time>
            <span>VOL</span>
            <input type="range" min={0} max={1} step="0.01" value={volume} onChange={(event) => { const value = Number(event.target.value); setVolume(value); if (audio.current) audio.current.volume = value; }} />
          </div>
        </> : <div className="empty"><strong>Station is empty</strong><p>Make a song or pick a playlist with tracks.</p></div>}
        {error && <div className="error">{error}</div>}
      </div>
      <aside className="radio-eq card">
        <div className="eyebrow">10-BAND EQ</div>
        <div className="radio-presets">{Object.keys(EQ_PRESETS).map((name) => <button key={name} type="button" className={preset === name ? "active" : ""} onClick={() => applyPreset(name)}>{name}</button>)}</div>
        <div className="radio-bands">
          {BAND_LABELS.map((label, band) => <label key={label} className="radio-band">
            <input type="range" min={-12} max={12} step={1} value={gains[band] ?? 0} onChange={(event) => setBand(band, Number(event.target.value))} />
            <b>{(gains[band] ?? 0) > 0 ? `+${gains[band]}` : gains[band]}</b>
            <span>{label}</span>
          </label>)}
        </div>
        <p className="modal-note">{eqLive ? "EQ is live on this track." : "EQ stays idle over the network so the first Play starts immediately. Sound uses the same stream as Library."} Custom sliders save on this machine.</p>
      </aside>
    </div>
  </section>;
}
