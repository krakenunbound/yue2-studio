import { useEffect, useRef, useState, type CSSProperties } from "react";
import type { TimedLyrics } from "./api";
import KaraokeLyrics from "./KaraokeLyrics";
import { EQ_BANDS } from "./eqProfiles";

function playbackTime(value: number) {
  if (!Number.isFinite(value) || value < 0) return "0:00";
  const seconds = Math.floor(value);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

type SongVisualizerProps = { src: string; timedLyrics?: TimedLyrics | null; onEnded: () => void; eqGains?: number[]; compact?: boolean; onAnalyser?: (analyser: AnalyserNode | null) => void; onPlayingChange?: (playing: boolean) => void };

export default function SongVisualizer({ src, timedLyrics, onEnded, eqGains, compact, onAnalyser, onPlayingChange }: SongVisualizerProps) {
  const audio = useRef<HTMLAudioElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const filters = useRef<BiquadFilterNode[]>([]);
  const eqGainsRef = useRef(eqGains);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [totalTime, setTotalTime] = useState(0);
  const [volume, setVolume] = useState(1);
  const [lyricsVisible, setLyricsVisible] = useState(() => localStorage.getItem("yue2-lyrics-visible") !== "false");
  const hasTimedLyrics = Boolean(timedLyrics?.lines?.length);

  useEffect(() => {
    eqGainsRef.current = eqGains;
    filters.current.forEach((filter, band) => { filter.gain.value = eqGains?.[band] ?? 0; });
  }, [eqGains]);

  useEffect(() => {
    const element = audio.current; const surface = canvas.current;
    if (!element || !surface || !src) return;
    let context: AudioContext | null = null;
    let analyser: AnalyserNode | null = null;
    let source: MediaElementAudioSourceNode | null = null;
    let eqFilters: BiquadFilterNode[] = [];
    let data = new Uint8Array(64);
    const paint = surface.getContext("2d");
    let frame = 0;
    let blobUrl: string | null = null;
    let cancelled = false;
    const request = new AbortController();
    const beginAnalysis = async () => {
      if (context) { if (context.state === "suspended") await context.resume(); return; }
      context = new AudioContext();
      analyser = context.createAnalyser();
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.55;
      source = context.createMediaElementSource(element);
      eqFilters = eqGainsRef.current ? EQ_BANDS.map((frequency, band) => {
        const filter = context!.createBiquadFilter();
        filter.type = band === 0 ? "lowshelf" : band === EQ_BANDS.length - 1 ? "highshelf" : "peaking";
        filter.frequency.value = frequency;
        filter.Q.value = band === 0 || band === EQ_BANDS.length - 1 ? 0.7 : 1;
        filter.gain.value = eqGainsRef.current?.[band] ?? 0;
        return filter;
      }) : [];
      if (eqFilters.length) {
        source.connect(eqFilters[0]);
        eqFilters.forEach((filter, band) => filter.connect(eqFilters[band + 1] || analyser));
      } else source.connect(analyser);
      filters.current = eqFilters;
      analyser.connect(context.destination);
      data = new Uint8Array(analyser.frequencyBinCount);
      onAnalyser?.(analyser);
      await context.resume();
    };
    const draw = () => {
      frame = requestAnimationFrame(draw);
      analyser?.getByteFrequencyData(data);
      const ratio = window.devicePixelRatio || 1; const width = surface.clientWidth; const height = surface.clientHeight;
      if (surface.width !== width * ratio || surface.height !== height * ratio) { surface.width = width * ratio; surface.height = height * ratio; paint?.setTransform(ratio, 0, 0, ratio, 0, 0); }
      if (!paint) return; paint.clearRect(0, 0, width, height);
      const bars = 42; const gap = 3; const barWidth = Math.max(2, (width - gap * (bars - 1)) / bars);
      const gradient = paint.createLinearGradient(0, height, width, 0); gradient.addColorStop(0, "#55e6ee"); gradient.addColorStop(.58, "#7d65f4"); gradient.addColorStop(1, "#b654ff"); paint.fillStyle = gradient;
      for (let index = 0; index < bars; index += 1) {
        const sample = data[Math.floor(index * data.length / bars)] / 255;
        const barHeight = Math.max(2, sample * height);
        paint.fillRect(index * (barWidth + gap), height - barHeight, barWidth, barHeight);
      }
    };
    const start = async () => {
      try {
        const response = await fetch(src, { signal: request.signal });
        const blob = await response.blob();
        if (cancelled) return;
        blobUrl = URL.createObjectURL(blob);
        element.src = blobUrl;
      } catch {
        if (cancelled) return;
        element.src = src;
      }
      try { await element.play(); } catch { /* autoplay can wait for the transport button */ }
    };
    element.crossOrigin = "anonymous";
    element.addEventListener("play", beginAnalysis);
    draw();
    void start();
    return () => {
      cancelled = true;
      request.abort();
      element.pause();
      element.removeAttribute("src");
      element.load();
      element.removeEventListener("play", beginAnalysis);
      cancelAnimationFrame(frame);
      filters.current = [];
      onAnalyser?.(null);
      onPlayingChange?.(false);
      try { source?.disconnect(); eqFilters.forEach((filter) => filter.disconnect()); analyser?.disconnect(); } catch { /* already disconnected */ }
      if (context) void context.close();
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [src]);

  useEffect(() => {
    const element = audio.current; if (!element) return;
    const updateTime = () => setCurrentTime(element.currentTime || 0);
    const updateDuration = () => setTotalTime(Number.isFinite(element.duration) ? element.duration : 0);
    const playingNow = () => { setIsPlaying(true); onPlayingChange?.(true); }; const pausedNow = () => { setIsPlaying(false); onPlayingChange?.(false); };
    let animationFrame = 0;
    const followPlayback = () => { if (!element.paused) setCurrentTime(element.currentTime || 0); animationFrame = requestAnimationFrame(followPlayback); };
    element.addEventListener("timeupdate", updateTime); element.addEventListener("durationchange", updateDuration); element.addEventListener("loadedmetadata", updateDuration); element.addEventListener("play", playingNow); element.addEventListener("pause", pausedNow);
    animationFrame = requestAnimationFrame(followPlayback);
    return () => { cancelAnimationFrame(animationFrame); element.removeEventListener("timeupdate", updateTime); element.removeEventListener("durationchange", updateDuration); element.removeEventListener("loadedmetadata", updateDuration); element.removeEventListener("play", playingNow); element.removeEventListener("pause", pausedNow); };
  }, [src]);

  const togglePlayback = () => { const element = audio.current; if (!element) return; if (element.paused) void element.play(); else element.pause(); };
  const stopPlayback = () => { const element = audio.current; if (!element) return; element.pause(); element.currentTime = 0; setCurrentTime(0); setIsPlaying(false); };
  const seek = (value: number) => { const element = audio.current; if (!element) return; element.currentTime = value; setCurrentTime(value); };
  const changeVolume = (value: number) => { const element = audio.current; if (!element) return; element.volume = value; setVolume(value); };
  const toggleLyrics = () => setLyricsVisible((visible) => { const next = !visible; localStorage.setItem("yue2-lyrics-visible", String(next)); return next; });

  return <div className={`song-visualizer ${lyricsVisible && hasTimedLyrics ? "lyrics-visible" : "lyrics-hidden"}`}>
    {lyricsVisible && <KaraokeLyrics lyrics={timedLyrics} currentTime={currentTime} compact={compact} />}
    <canvas ref={canvas} />
    <div className="song-transport">
      <button className="transport-play" aria-label={isPlaying ? "Pause" : "Play"} title={isPlaying ? "Pause" : "Play"} onClick={togglePlayback}>{isPlaying ? "Ⅱ" : "▶"}</button>
      <button className="transport-stop" aria-label="Stop and return to the beginning" title="Stop and return to 0:00" onClick={stopPlayback}>■</button>
      <button className={`transport-lyrics ${lyricsVisible && hasTimedLyrics ? "active" : ""}`} disabled={!hasTimedLyrics} aria-label={`${lyricsVisible ? "Hide" : "Show"} synchronized lyrics`} aria-pressed={lyricsVisible && hasTimedLyrics} title={hasTimedLyrics ? `${lyricsVisible ? "Hide" : "Show"} synchronized lyrics` : "This song has no synchronized lyrics"} onClick={toggleLyrics}>Lyrics</button>
      <time>{playbackTime(currentTime)}</time>
      <input className="transport-seek" aria-label="Song position" type="range" min="0" max={Math.max(totalTime, 0.01)} step="0.01" value={Math.min(currentTime, Math.max(totalTime, 0.01))} onChange={(event) => seek(Number(event.target.value))} style={{ "--seek": `${totalTime ? (currentTime / totalTime) * 100 : 0}%` } as CSSProperties} />
      <time>{playbackTime(totalTime)}</time>
      <span className="transport-volume-icon" aria-hidden="true">VOL</span>
      <input className="transport-volume" aria-label="Volume" type="range" min="0" max="1" step="0.01" value={volume} onChange={(event) => changeVolume(Number(event.target.value))} style={{ "--volume": `${volume * 100}%` } as CSSProperties} />
    </div>
    <audio ref={audio} preload="auto" crossOrigin="anonymous" onEnded={() => { setIsPlaying(false); setCurrentTime(0); onPlayingChange?.(false); onEnded(); }} />
  </div>;
}
