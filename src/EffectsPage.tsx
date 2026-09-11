import { useEffect, useMemo, useRef, useState } from "react";
import stableAudioLogo from "./assets/stable-audio-3-small-sfx.png";
import { addEffectToStudio, assistWriting, audioUrl, cancelJob, deleteEffect, generateEffect, getEffects, getJob, getStatus, type Job, type Song, type SoundEffect, type SoundEffectsEngineStatus } from "./api";

const PRESETS = [
  ["Doorbell", "A clean two-tone residential doorbell chime, close and dry, one complete ding-dong"],
  ["Car pass", "A high-performance sports car races past from left to right, rapid Doppler shift, tire and engine detail"],
  ["Thunder", "A close thunder crack followed by a long rolling storm rumble across a wide open valley"],
  ["Footsteps", "Heavy leather boots walking slowly across an old wooden floor, individual creaks, close perspective"],
  ["Ocean", "Cold ocean waves breaking against dark rocks, foamy retreat, distant wind, natural field recording"],
  ["Impact", "A deep cinematic metal impact with a short sub-bass tail, no music, clean production sound effect"],
] as const;

function clock(value: number) {
  const seconds = Math.max(0, Math.floor(value || 0));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function songFolder(song: Song) {
  return song.folder_name || song.folder.split(/[\\/]/).filter(Boolean).at(-1) || "";
}

type Props = { ready: boolean; detail: string; songs: Song[]; onOpenStudio?: (folder: string) => void; onOpenModels?: () => void };

export default function EffectsPage({ ready, detail, songs, onOpenStudio, onOpenModels }: Props) {
  const [items, setItems] = useState<SoundEffect[]>([]);
  const [sources, setSources] = useState<Record<string, string>>({});
  const [name, setName] = useState("");
  const [prompt, setPrompt] = useState("");
  const [enhancing, setEnhancing] = useState(false);
  const [suggestion, setSuggestion] = useState("");
  const [duration, setDuration] = useState(5);
  const [steps, setSteps] = useState(8);
  const [cfg, setCfg] = useState(4.5);
  const [sampler, setSampler] = useState("pingpong");
  const [chunkedDecode, setChunkedDecode] = useState(true);
  const [engine, setEngine] = useState<"stable" | "woosh">("stable");
  const [engineStatus, setEngineStatus] = useState<Partial<Record<"stable" | "woosh", SoundEffectsEngineStatus>>>({});
  const [negativePrompt, setNegativePrompt] = useState("");
  const [seed, setSeed] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [targetSong, setTargetSong] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [playing, setPlaying] = useState<string | null>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [addedFolder, setAddedFolder] = useState("");
  const audio = useRef<HTMLAudioElement | null>(null);

  const refresh = async () => {
    const response = await getEffects();
    setItems(response.items);
  };

  useEffect(() => {
    void refresh().catch((reason) => setError(reason.message));
    void getStatus().then((status) => setEngineStatus(status.sound_effects.models ?? {})).catch((reason) => setError(reason.message));
  }, []);
  useEffect(() => {
    if (!targetSong && songs[0]) setTargetSong(songFolder(songs[0]));
  }, [songs, targetSong]);
  useEffect(() => {
    void Promise.all(items.map(async (item) => [item.id, await audioUrl(item.url)] as const)).then((pairs) => setSources(Object.fromEntries(pairs)));
  }, [items]);
  useEffect(() => {
    if (!job || ["succeeded", "failed", "cancelled"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const result = await getJob(job.id);
        setJob(result.job);
        if (result.job.status === "succeeded") {
          await refresh();
          setMessage("Sound effect saved to the Effects library.");
        }
      } catch (reason: any) { setError(reason?.message ?? String(reason)); }
    }, 800);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status]);
  useEffect(() => () => { audio.current?.pause(); }, []);

  const active = Boolean(job && ["queued", "running"].includes(job.status));
  const selected = engineStatus[engine];
  const selectedReady = selected?.ready ?? (engine === "stable" && ready);
  const selectedDetail = selected?.detail ?? detail;
  const isWoosh = engine === "woosh";
  const activeEffect = useMemo(() => items.find((item) => item.id === playing) ?? null, [items, playing]);

  function choosePreset(label: string, value: string) {
    setName(label); setPrompt(value); setMessage(""); setError("");
  }

  async function start() {
    if (!prompt.trim()) return;
    setMessage(""); setError("");
    try {
      const response = await generateEffect({ prompt: prompt.trim(), name: name.trim(), negative_prompt: negativePrompt.trim(), duration, steps, sampler, chunked_decode: chunkedDecode, engine, cfg, seed: seed ? Number(seed) : null });
      setJob(response.job);
    } catch (reason: any) { setError(reason?.message ?? String(reason)); }
  }

  async function enhance() {
    setEnhancing(true); setError(""); setSuggestion("");
    try {
      const result = await assistWriting({ action: "effect", description: prompt.trim(), effect_engine: engine });
      setSuggestion(result.description || "");
    } catch (reason: any) { setError(reason?.message ?? String(reason)); }
    finally { setEnhancing(false); }
  }

  function stopPreview() {
    if (audio.current) { audio.current.pause(); audio.current.currentTime = 0; }
    setPlaying(null); setCurrentTime(0);
  }

  function togglePreview(item: SoundEffect) {
    if (playing === item.id) { stopPreview(); return; }
    stopPreview();
    const player = new Audio(sources[item.id]);
    audio.current = player;
    player.ontimeupdate = () => setCurrentTime(player.currentTime);
    player.onended = stopPreview;
    setPlaying(item.id); setCurrentTime(0);
    void player.play().catch((reason) => { setError(reason.message); stopPreview(); });
  }

  async function addToStudio(item: SoundEffect) {
    if (!targetSong) return;
    setMessage(""); setError("");
    try {
      await addEffectToStudio(item.id, targetSong);
      const song = songs.find((candidate) => songFolder(candidate) === targetSong);
      setAddedFolder(targetSong);
      setMessage(`“${item.name}” added as a new Studio track${song ? ` in “${song.title}”` : ""}. Open Studio to place the ${item.duration.toFixed(1)}s clip.`);
    } catch (reason: any) { setError(reason?.message ?? String(reason)); }
  }

  async function remove(item: SoundEffect) {
    try {
      if (playing === item.id) stopPreview();
      await deleteEffect(item.id); setConfirmDelete(null); await refresh();
      setMessage(`“${item.name}” removed from the Effects library.`);
    } catch (reason: any) { setError(reason?.message ?? String(reason)); }
  }

  return <section className="effects-page main-view active">
    <header className="effects-hero">
      <img src={stableAudioLogo} alt={isWoosh ? "Woosh-Flow" : "Stable Audio 3"} />
      <div><div className="eyebrow">LOCAL SOUND-EFFECT STUDIO</div><h1>Effects</h1><p>Generate production sounds locally with Stable Audio 3 Small SFX or Sony Woosh-Flow. Effects stay separate from your songs until you add one to a Studio session.</p></div>
      <span className={`effects-engine ${selectedReady ? "ready" : "blocked"}`}><i />{selectedReady ? `${selected?.model ?? (isWoosh ? "Woosh-Flow" : "Stable Audio 3 SFX")} ready` : "Selected sound model unavailable"}</span>
    </header>

    <div className="effects-layout">
      <section className="effects-generator">
        <div className="eyebrow">CREATE AN EFFECT</div><h2>Describe the sound</h2>
        <label>Sound engine<select value={engine} onChange={(event) => {
          const next = event.target.value as "stable" | "woosh";
          setEngine(next); setSuggestion("");
          if (next === "woosh") { setDuration((value) => Math.min(5, value)); setSteps(32); setCfg(4.5); setSampler("dopri5"); }
          else { setSteps(8); setSampler("pingpong"); }
        }}><option value="stable">Stable Audio 3 Small SFX · CPU</option><option value="woosh">Woosh-Flow · GPU</option></select></label>
        {isWoosh && <p className="truth-note">Woosh-Flow uses the GPU and unloads YuE2 first. It produces up to 5 seconds per generation and supports a negative prompt.</p>}
        <div className="effect-presets">{PRESETS.map(([label, value]) => <button type="button" key={label} onClick={() => choosePreset(label, value)}>{label}</button>)}</div>
        <label>Name <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Optional library name" /></label>
        <label>Sound description <textarea rows={7} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="A heavy oak door slams in a stone hallway, close perspective, natural reverberation…" /></label>
        <button type="button" disabled={!prompt.trim() || enhancing} onClick={() => void enhance()}>{enhancing ? "Enhancing prompt…" : "✦ Enhance prompt"}</button>
        <p className="truth-note">Uses your enabled Writing helper in Keys (including Gemini). Only runs when clicked; review the suggestion before using it.</p>
        {suggestion && <div className="truth-note"><label>Suggested sound description<textarea rows={5} value={suggestion} onChange={(event) => setSuggestion(event.target.value)} /></label><button type="button" onClick={() => { setPrompt(suggestion); setSuggestion(""); }}>Use this prompt</button><button type="button" onClick={() => setSuggestion("")}>Dismiss</button></div>}
        {isWoosh ? <label>Avoid (negative prompt)<input value={negativePrompt} onChange={(event) => setNegativePrompt(event.target.value)} placeholder="music, speech, distortion, hiss" /><small>Woosh uses this to steer away from unwanted sounds.</small></label> : <p className="truth-note">Stable Audio 3 Small SFX does not support negative prompts. Describe the sound and background you want in the main description. Quiet effects keep their natural level.</p>}
        <label>Length <div className="range-row"><input type="range" min="0.5" max={isWoosh ? "5" : "30"} step="0.5" value={Math.min(duration, isWoosh ? 5 : 30)} onChange={(event) => setDuration(Number(event.target.value))} /><b>{duration.toFixed(1)}s</b></div></label>
        <details><summary>Generation settings</summary>
          <label>Steps <div className="range-row"><input aria-label="Sampling steps" type="range" min="1" max="100" step="1" value={steps} disabled={isWoosh && sampler === "dopri5"} onChange={(event) => setSteps(Number(event.target.value))} /><b>{isWoosh && sampler === "dopri5" ? "auto" : steps}</b></div><small>{isWoosh ? (sampler === "dopri5" ? "DOPRI5 selects integration steps automatically." : "Euler uses this fixed count. More steps take longer; use the same seed to compare.") : "Default 8. More steps take longer and may not improve this model. Keep the same seed to compare."}</small></label>
          {isWoosh ? <><label>CFG <div className="range-row"><input aria-label="Classifier-free guidance" type="range" min="0" max="10" step="0.1" value={cfg} onChange={(event) => setCfg(Number(event.target.value))} /><b>{cfg.toFixed(1)}</b></div><small>Default 4.5. Higher guidance follows the prompt more strongly.</small></label><label>Sampler<select value={sampler} onChange={(event) => setSampler(event.target.value)}><option value="dopri5">DOPRI5 (recommended, adaptive)</option><option value="euler">Euler (fixed steps)</option></select><small>{sampler === "dopri5" ? "Recommended by Woosh. It chooses the integration steps automatically." : "Uses the fixed Steps setting above."}</small></label></> : <><label>Sampler<select value={sampler} onChange={(event) => setSampler(event.target.value)}><option value="pingpong">Ping-pong (default)</option><option value="euler">Euler (experimental)</option><option value="rk4">RK4 (experimental, slower)</option><option value="dpmpp">DPM++ (experimental)</option></select></label><label>CFG <input aria-label="CFG unavailable" type="range" min="1" max="15" value="1" disabled /><small>Fixed at 1: this post-trained checkpoint does not support CFG adjustments.</small></label><label><input type="checkbox" checked={chunkedDecode} onChange={(event) => setChunkedDecode(event.target.checked)} /> Decode in chunks</label><small>Uses less memory. Turn off to compare against a full decode.</small></>}
          <button type="button" onClick={() => { if (isWoosh) { setSteps(32); setCfg(4.5); setSampler("dopri5"); } else { setSteps(8); setSampler("pingpong"); setChunkedDecode(true); } }}>Reset generation settings</button>
        </details>
        <label>Seed <input inputMode="numeric" value={seed} onChange={(event) => setSeed(event.target.value.replace(/\D/g, ""))} placeholder="Random each time" /></label>
        {job && <div className={`job-banner effect-job ${job.status}`}><div><strong>{job.phase}</strong><span>{job.error || `${Math.round(job.progress * 100)}%`}</span></div><div className="progress"><i style={{ width: `${Math.round(job.progress * 100)}%` }} /></div></div>}
        <div className="effect-create-actions"><button className="primary" disabled={!selectedReady || !prompt.trim() || active} onClick={() => void start()}>{active ? "Generating sound…" : "Generate effect"}</button>{active && <button className="danger" onClick={() => void cancelJob(job!.id)}>Cancel</button>}</div>
        {!selectedReady && <div className="truth-note">{selectedDetail}{onOpenModels && <button type="button" className="models-link-button" onClick={onOpenModels}>Open Models to install it</button>}</div>}
      </section>

      <section className="effects-library">
        <div className="effects-library-head"><div><div className="eyebrow">EFFECT LIBRARY</div><h2>Your sounds</h2></div><label>Send effects to<select value={targetSong} onChange={(event) => setTargetSong(event.target.value)}><option value="">Choose a song…</option>{songs.map((song) => <option value={songFolder(song)} key={song.id}>{song.title}</option>)}</select></label></div>
        {message && <div className="effect-message">{message}{addedFolder && onOpenStudio && <button type="button" className="open-studio-button" onClick={() => onOpenStudio(addedFolder)}>Open Studio</button>}</div>}{error && <div className="error">{error}</div>}
        {!items.length && <div className="empty"><strong>No sound effects yet</strong><span>Generate a sound on the left. It will be saved here—not in Songs.</span></div>}
        <div className="effect-grid">{items.map((item) => <article className={`effect-card ${playing === item.id ? "playing" : ""}`} key={item.id}>
          <button className="effect-play" onClick={() => togglePreview(item)} aria-label={`${playing === item.id ? "Stop" : "Play"} ${item.name}`}>{playing === item.id ? "■" : "▶"}</button>
          <div className="effect-copy"><strong>{item.name}</strong><p>{item.prompt}</p><span>{item.duration.toFixed(1)} sec · {item.seed == null ? "validation preview" : `seed ${item.seed}`} · {item.created_at}</span>{playing === item.id && <div className="effect-playback"><i style={{ width: `${Math.min(100, currentTime / item.duration * 100)}%` }} /><b>{clock(currentTime)} / {clock(item.duration)}</b></div>}</div>
          <div className="effect-actions"><button disabled={!targetSong} onClick={() => void addToStudio(item)}>Add to Studio</button><a href={sources[item.id]} download={`${item.name}.wav`}>WAV</a><button className="effect-delete" onClick={() => setConfirmDelete(item.id)}>Delete</button></div>
          {confirmDelete === item.id && <div className="effect-confirm"><span>Remove this effect?</span><button onClick={() => setConfirmDelete(null)}>Keep</button><button className="danger" onClick={() => void remove(item)}>Delete</button></div>}
        </article>)}</div>
      </section>
    </div>
  </section>;
}
