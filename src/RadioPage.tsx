import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import { type Playlist, type Song, type Workspace } from "./api";
import EqPanel from "./EqPanel";
import KaraokeLyrics from "./KaraokeLyrics";
import { EQ_BANDS as BANDS } from "./eqProfiles";
import useAutoEq from "./useAutoEq";

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

// Keep word-by-word animation local so it does not rerender the whole station queue.
function RadioKaraoke({ audio, song }: { audio: RefObject<HTMLAudioElement | null>; song: Song }) {
  const [time, setTime] = useState(0);
  useEffect(() => {
    const element = audio.current;
    if (!element) return;
    const update = () => setTime(element.currentTime || 0);
    let frame = 0;
    const follow = () => {
      if (!element.paused) update();
      frame = requestAnimationFrame(follow);
    };
    update();
    element.addEventListener("timeupdate", update);
    element.addEventListener("seeking", update);
    element.addEventListener("loadedmetadata", update);
    frame = requestAnimationFrame(follow);
    return () => {
      cancelAnimationFrame(frame);
      element.removeEventListener("timeupdate", update);
      element.removeEventListener("seeking", update);
      element.removeEventListener("loadedmetadata", update);
    };
  }, [audio, song.id]);
  return <KaraokeLyrics lyrics={song.timed_lyrics} currentTime={time} />;
}

type Props = {
  songs: Song[];
  releasingSongIds?: string[];
  playlists: Playlist[];
  workspaces: Workspace[];
  coverSources: Record<string, string>;
  coverArtReady: boolean;
  lyricsSyncReady: boolean;
  lyricsSyncBusy: boolean;
  onSyncLyrics: (song: Song) => Promise<void>;
  onRateSong: (song: Song, rating: number) => Promise<void>;
  onLeaveLibraryPlay: () => void;
  onAddToPlaylist: (song: Song, playlist: Playlist) => Promise<void>;
  onNewPlaylistForSong: (song: Song) => void;
  onEditSong: (song: Song) => void;
  onGenerateCover: (song: Song) => void;
  onDeleteSong: (song: Song) => void;
};

export default function RadioPage({ songs, releasingSongIds, playlists, workspaces, coverSources, coverArtReady, lyricsSyncReady, lyricsSyncBusy, onSyncLyrics, onRateSong, onLeaveLibraryPlay, onAddToPlaylist, onNewPlaylistForSong, onEditSong, onGenerateCover, onDeleteSong }: Props) {
  const audio = useRef<HTMLAudioElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const graph = useRef<{ context: AudioContext; source: MediaElementAudioSourceNode; filters: BiquadFilterNode[]; analyser: AnalyserNode } | null>(null);
  const [sourceKey, setSourceKey] = useState(() => localStorage.getItem("yue2-radio-source") || "all");
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(1);
  const [shuffle, setShuffle] = useState(false);
  const [repeat, setRepeat] = useState<RepeatMode>("all");
  const [eqLive, setEqLive] = useState(false);
  const [error, setError] = useState("");
  const [actionSongId, setActionSongId] = useState<string | null>(null);
  const [lyricsVisible, setLyricsVisible] = useState(true);
  const [syncSubmitting, setSyncSubmitting] = useState(false);
  const [ratingSaving, setRatingSaving] = useState(false);
  const ratingPending = useRef(false);
  const blobUrl = useRef<string | null>(null);
  const wantPlay = useRef(false);
  const pendingPlayId = useRef<string | null>(null);

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
  const releasing = Boolean(current && releasingSongIds?.includes(current.id));
  const { autoEq, setAutoEq, autoPreset, preset, displayGains, displayGainsRef, applyPreset, setBand } = useAutoEq(current);

  useEffect(() => { localStorage.setItem("yue2-radio-source", sourceKey); }, [sourceKey]);
  useEffect(() => { if (index >= queue.length) setIndex(0); }, [queue.length, index]);

  useEffect(() => {
    onLeaveLibraryPlay();
    const element = audio.current;
    if (!element) return;
    const closeGraph = () => {
      const oldGraph = graph.current;
      graph.current = null;
      try { oldGraph?.source.disconnect(); oldGraph?.analyser.disconnect(); } catch { /* already disconnected */ }
      oldGraph?.context.close().catch(() => undefined);
    };
    closeGraph();
    if (blobUrl.current) { URL.revokeObjectURL(blobUrl.current); blobUrl.current = null; }
    setEqLive(false);
    setCurrentTime(0);
    setDuration(0);
    setPlaying(false);
    if (!current || releasing) {
      wantPlay.current = false;
      pendingPlayId.current = null;
      element.pause(); element.removeAttribute("src"); element.load();
      setPlaying(false); return closeGraph;
    }
    const src = radioSrc(current);
    element.crossOrigin = "anonymous";
    if (element.getAttribute("src") !== src) element.src = src;
    element.volume = volume;
    setError("");
    return () => { element.pause(); element.removeAttribute("src"); element.load(); closeGraph(); };
  }, [current?.id, current?.audio_url, releasing]);

  useEffect(() => {
    const element = audio.current;
    if (!element) return;
    const connectGraph = () => {
      const existing = graph.current;
      if (existing) {
        if (existing.context.state === "suspended") void existing.context.resume();
        return;
      }
      try {
        const context = new AudioContext();
        const source = context.createMediaElementSource(element);
        const filters = BANDS.map((frequency, band) => {
          const filter = context.createBiquadFilter();
          filter.type = band === 0 ? "lowshelf" : band === BANDS.length - 1 ? "highshelf" : "peaking";
          filter.frequency.value = frequency;
          filter.Q.value = band === 0 || band === BANDS.length - 1 ? 0.7 : 1;
          filter.gain.value = displayGainsRef.current[band] ?? 0;
          return filter;
        });
        const analyser = context.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.82;
        source.connect(filters[0]);
        filters.forEach((filter, band) => filter.connect(filters[band + 1] || analyser));
        analyser.connect(context.destination);
        graph.current = { context, source, filters, analyser };
        setEqLive(true);
        void context.resume();
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Radio visualizer could not connect to this track.");
      }
    };
    element.addEventListener("play", connectGraph);
    return () => element.removeEventListener("play", connectGraph);
  }, [current?.id]);

  useEffect(() => {
    if (!current || pendingPlayId.current !== current.id) return;
    pendingPlayId.current = null;
    const element = audio.current;
    if (!element) return;
    void element.play().catch((reason) => {
      if ((reason as { name?: string })?.name === "AbortError") return;
      setError(reason instanceof Error ? reason.message : "Could not start Radio playback.");
    });
  }, [current?.id]);

  useEffect(() => {
    graph.current?.filters.forEach((filter, band) => { filter.gain.value = displayGains[band] ?? 0; });
  }, [displayGains]);

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
      for (let i = 0; i < bars; i += 1) {
        const sample = analyser ? data[Math.floor(i * data.length / bars)] / 255 : 0.08;
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
    if (!song || releasingSongIds?.includes(song.id)) return;
    wantPlay.current = true;
    const element = audio.current;
    if (!element) return;
    if (current?.id !== song.id) {
      pendingPlayId.current = song.id;
      setIndex(songIndex);
      return;
    }
    void element.play().catch((reason) => {
      if ((reason as { name?: string })?.name === "AbortError") return;
      setError(reason instanceof Error ? reason.message : "Could not start Radio playback.");
    });
  }

  function toggle() {
    const element = audio.current; if (!element) return;
    if (element.paused) startTrack(index);
    else { wantPlay.current = false; element.pause(); }
  }

  async function rateCurrent(rating: number) {
    if (!current || ratingPending.current) return;
    ratingPending.current = true;
    setRatingSaving(true);
    setError("");
    try { await onRateSong(current, rating); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save your rating. Please try again."); }
    finally { ratingPending.current = false; setRatingSaving(false); }
  }

  async function syncCurrentLyrics() {
    if (!current || syncSubmitting || lyricsSyncBusy) return;
    setSyncSubmitting(true);
    setLyricsVisible(true);
    try { await onSyncLyrics(current); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not start lyric synchronization."); }
    finally { setSyncSubmitting(false); }
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
          {queue.map((song, songIndex) => <div className="radio-track-row" key={song.id}>
            <button type="button" className={`radio-track ${song.id === current?.id ? "active" : ""}`} onClick={() => { setActionSongId(null); startTrack(songIndex); }}>
              <img src={coverSources[song.id] || ""} alt="" />
              <span><strong>{song.title}</strong><small>{clock(song.duration || 0)}{Boolean(song.rating) && <span className="radio-queue-rating" aria-label={`${song.rating} out of 5 stars`}> · {"★".repeat(Math.max(0, Math.min(5, song.rating || 0)))}</span>}</small></span>
            </button>
            <button type="button" className="dots radio-track-dots" aria-label={`Curate ${song.title}`} aria-expanded={actionSongId === song.id} onClick={(event) => { event.stopPropagation(); setActionSongId((open) => open === song.id ? null : song.id); }}>•••</button>
            {actionSongId === song.id && <div className="radio-track-actions" role="menu">
              <div className="radio-action-label">PLAYLISTS</div>
              {playlists.map((playlist) => <button key={playlist.id} type="button" disabled={playlist.song_ids.includes(song.id)} onClick={() => { setActionSongId(null); void onAddToPlaylist(song, playlist); }}><span>♫</span>{playlist.name}{playlist.song_ids.includes(song.id) && <small>Added</small>}</button>)}
              <button type="button" onClick={() => { setActionSongId(null); onNewPlaylistForSong(song); }}><span>＋</span>New playlist</button>
              <div className="radio-action-divider" />
              <button type="button" onClick={() => { setActionSongId(null); onEditSong(song); }}><span>✎</span>Edit details / rename</button>
              {coverArtReady && <button type="button" onClick={() => { setActionSongId(null); onGenerateCover(song); }}><span>✦</span>Generate cover art</button>}
              <button type="button" className="menu-danger" onClick={() => { setActionSongId(null); onDeleteSong(song); }}><span>⌫</span>Delete song</button>
            </div>}
          </div>)}
        </div>
      </aside>
      <div className="radio-stage card">
        {current ? <>
          <div className="radio-now">
            {coverSources[current.id] ? <img src={coverSources[current.id]} alt="" /> : <div className="radio-now-empty">♫</div>}
            <div><div className="eyebrow">NOW PLAYING</div><h3>{current.title}</h3><p>{current.instrumental ? "Instrumental" : "Vocal"}{current.genre ? ` · ${current.genre}` : ""}</p>
              <div className="radio-rating" role="group" aria-label={`Rate ${current.title}`} aria-busy={ratingSaving}>
                {[1, 2, 3, 4, 5].map((star) => <button key={star} type="button" className={(current.rating || 0) >= star ? "rated" : ""} aria-label={`Rate ${star} out of 5 stars`} aria-pressed={current.rating === star} title={`${star} out of 5 stars`} disabled={ratingSaving} onClick={() => void rateCurrent(star)}>★</button>)}
                <span aria-live="polite">{ratingSaving ? "Saving…" : current.rating ? `${current.rating}/5` : "Not rated"}</span>
                {Boolean(current.rating) && <button type="button" className="radio-rating-clear" disabled={ratingSaving} onClick={() => void rateCurrent(0)} aria-label="Clear rating">Clear</button>}
              </div>
            </div>
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
            <input aria-label="Song position" type="range" min={0} max={Math.max(duration, 0.01)} step="0.01" value={Math.min(currentTime, duration || 0)} onChange={(event) => { const value = Number(event.target.value); if (audio.current) audio.current.currentTime = value; setCurrentTime(value); }} />
            <time>{clock(duration || current.duration || 0)}</time>
            <span>VOL</span>
            <input aria-label="Volume" type="range" min={0} max={1} step="0.01" value={volume} onChange={(event) => { const value = Number(event.target.value); setVolume(value); if (audio.current) audio.current.volume = value; }} />
          </div>
          {!current.instrumental && <section className="radio-lyrics" aria-label="Radio karaoke">
            <div className="radio-lyrics-tools">
              <div className="eyebrow">KARAOKE LYRICS</div>
              <button type="button" aria-pressed={lyricsVisible} disabled={!current.timed_lyrics?.lines?.length} onClick={() => setLyricsVisible((visible) => !visible)}>{lyricsVisible ? "Hide lyrics" : "Show lyrics"}</button>
              <button type="button" disabled={!lyricsSyncReady || !current.lyrics?.trim() || lyricsSyncBusy || syncSubmitting} onClick={() => void syncCurrentLyrics()}>{syncSubmitting || lyricsSyncBusy ? "Sync in progress…" : current.timed_lyrics?.lines?.length ? "Re-sync lyrics" : "Sync lyrics"}</button>
            </div>
            {lyricsVisible && (current.timed_lyrics?.lines?.length
              ? <RadioKaraoke key={current.id} audio={audio} song={current} />
              : <p className="modal-note">{current.lyrics?.trim() ? "Sync this song to see its lyrics highlighted during playback." : "This song has no saved lyrics. Add them in Edit details to enable synchronization."}</p>)}
            {!lyricsSyncReady && <p className="modal-note">Install Whisper lyrics and karaoke in Models to synchronize this song.</p>}
          </section>}
        </> : <div className="empty"><strong>Station is empty</strong><p>Make a song or pick a playlist with tracks.</p></div>}
        {error && <div className="error">{error}</div>}
      </div>
      <aside className="radio-eq card">
        <div className="eyebrow">10-BAND EQ</div>
        <EqPanel autoEq={autoEq} setAutoEq={setAutoEq} autoPreset={autoPreset} preset={preset} displayGains={displayGains} applyPreset={applyPreset} setBand={setBand} note={eqLive ? autoEq ? `Auto EQ is live · ${autoPreset}; sliders glide on track changes. Custom sliders save on this machine.` : "Manual EQ is live on this track. Custom sliders save on this machine." : "EQ stays idle over the network so the first Play starts immediately. Sound uses the same stream as Library. Custom sliders save on this machine."} />
      </aside>
    </div>
  </section>;
}
