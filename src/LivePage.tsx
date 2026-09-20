import { useEffect, useMemo, useRef, useState } from "react";
import { abortWriting, assistWriting, generate, getJob, getLibrary, getVoiceProfiles, voiceAvatarUrl, type Job, type Song } from "./api";
import { EMPTY_VOICE_SLOTS } from "./createForm";
import type { StylePreset } from "./styleTypes";
import type { VoiceProfile } from "./voiceProfiles";
import { CAST_ROLL, castHint, randomCast, randomSlots, reelVoices, vocalGenderFor, type LiveCast } from "./liveCast";
import SongVisualizer from "./SongVisualizer";
import EqPanel from "./EqPanel";
import useAutoEq from "./useAutoEq";
import "./LivePage.css";
import castInstrumental from "./assets/live/instrumental.png";
import castFemale from "./assets/live/female.png";
import castMale from "./assets/live/male.png";
import castDuet from "./assets/live/duet.png";
import castFemaleDuo from "./assets/live/female-duo.png";
import castMaleDuo from "./assets/live/male-duo.png";

const CAST_ART: Record<LiveCast, string> = {
  instrumental: castInstrumental,
  female: castFemale,
  male: castMale,
  duet: castDuet,
  "female-duo": castFemaleDuo,
  "male-duo": castMaleDuo,
};

const bundledVoices = import.meta.glob("./assets/voices/*.webp", { eager: true, import: "default" }) as Record<string, string>;

function voiceArt(id: string, voices: VoiceProfile[]) {
  if (!id) return "";
  const profile = voices.find((item) => item.id === id);
  if (profile?.avatar === "custom") return voiceAvatarUrl(profile.id, profile.updated_at || "");
  return bundledVoices[`./assets/voices/${id}.webp`] || "";
}

function voiceName(id: string, voices: VoiceProfile[]) {
  return voices.find((item) => item.id === id)?.name || "—";
}

const MIN_BUFFER_SIZE = 3;
const DEFAULT_BUFFER_SIZE = 5;
const INSTRUMENTAL_LOCK = "instrumental, no vocals, no humming, no vocables, no oohs, no aahs, no choir, no rap, no vocal chops, lead instrument only";

type Pick = { id: string; template: string; instrumental: boolean; cast: LiveCast; female: string; male: string; title?: string };
type Props = {
  ready: boolean;
  presets: Record<string, StylePreset>;
  art: Record<string, string>;
  songs: Song[];
  coverSources: Record<string, string>;
  onLeaveLibraryPlay: () => void;
  onRefresh: () => Promise<void>;
  onAnalyserChange: (analyser: AnalyserNode | null) => void;
  onPlaybackChange: (playing: boolean) => void;
  onCurrentChange: (songId: string | null) => void;
};

function liveSrc(song: Song) {
  const path = song.audio_url.split("?")[0];
  if ("__TAURI_INTERNALS__" in window) return `http://127.0.0.1:7794${path}`;
  return `${window.location.origin}${path}`;
}

function liveDescription(preset: StylePreset, instrumental: boolean, slots?: { female: string; male: string }) {
  const parts = [preset.genre];
  if (instrumental) parts.push(INSTRUMENTAL_LOCK);
  else {
    if (!(slots?.female || slots?.male)) parts.push(preset.voice);
    if (preset.delivery) parts.push(preset.delivery);
  }
  parts.push(preset.arrangement, preset.mood, preset.tempo, preset.production);
  return parts.filter(Boolean).join(", ");
}

function shuffle<T>(items: T[]): T[] {
  const next = [...items];
  for (let i = next.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [next[i], next[j]] = [next[j], next[i]];
  }
  return next;
}

function randomPick(names: string[], profiles: VoiceProfile[], avoid: string[] = []): Pick {
  const blocked = new Set(avoid);
  const pool = names.filter((name) => !blocked.has(name));
  const choices = pool.length ? pool : names;
  const cast = randomCast();
  const slots = randomSlots(cast, profiles);
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    template: choices[Math.floor(Math.random() * choices.length)],
    instrumental: cast === "instrumental",
    cast,
    female: slots.female,
    male: slots.male,
  };
}

function randomCatalogIds(songs: Song[], count: number) {
  const shuffled = shuffle(songs);
  const titles = new Set<string>();
  const genres = new Set<string>();
  const ids: string[] = [];
  for (const song of shuffled) {
    const title = song.title.trim().toLowerCase();
    const genre = (song.genre || "").trim().toLowerCase();
    if (!title || titles.has(title) || (genre && genres.has(genre))) continue;
    titles.add(title);
    if (genre) genres.add(genre);
    ids.push(song.id);
    if (ids.length >= count) break;
  }
  if (ids.length < count) {
    for (const song of shuffled) {
      if (ids.includes(song.id)) continue;
      const title = song.title.trim().toLowerCase();
      if (!title || titles.has(title)) continue;
      titles.add(title);
      ids.push(song.id);
      if (ids.length >= count) break;
    }
  }
  return ids;
}

export default function LivePage({ ready, presets, art, songs, coverSources, onLeaveLibraryPlay, onRefresh, onAnalyserChange, onPlaybackChange, onCurrentChange }: Props) {
  // Parent refresh changes identity on every render, including the render caused
  // by completing a song. It must not tear down the in-flight job poll.
  const refreshRef = useRef(onRefresh);
  refreshRef.current = onRefresh;
  const names = useMemo(() => Object.keys(presets), [presets]);
  const [voices, setVoices] = useState<VoiceProfile[]>([]);
  const [on, setOn] = useState(false);
  const [flash, setFlash] = useState<Pick | null>(null);
  const [locked, setLocked] = useState<Pick | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [queue, setQueue] = useState<string[]>([]);
  const [generatedIds, setGeneratedIds] = useState<Set<string>>(() => new Set());
  const [bufferSize, setBufferSize] = useState(DEFAULT_BUFFER_SIZE);
  const [pending, setPending] = useState<Pick[]>([]);
  const [activePick, setActivePick] = useState<Pick | null>(null);
  const [index, setIndex] = useState(0);
  const [primed, setPrimed] = useState(false);
  const [waitingForNext, setWaitingForNext] = useState(false);
  const [error, setError] = useState("");
  const [writingPhase, setWritingPhase] = useState("");
  const picking = useRef(false);
  const recentTemplates = useRef<string[]>([]);
  const queueRef = useRef<string[]>([]);
  const indexRef = useRef(0);
  const pendingRef = useRef<Pick[]>([]);
  const submitting = useRef(false);
  const preparedRef = useRef<{ pick: Pick; title: string; lyrics: string } | null>(null);
  const prefetching = useRef(false);
  const catalogBufferRef = useRef<Song[]>([]);
  const liveEpochRef = useRef(0);
  const drawTimerRef = useRef<number | null>(null);

  useEffect(() => () => {
    liveEpochRef.current += 1;
    if (drawTimerRef.current !== null) window.clearInterval(drawTimerRef.current);
    drawTimerRef.current = null;
    picking.current = false;
    if (submitting.current || prefetching.current) void abortWriting().catch(() => undefined);
  }, []);

  useEffect(() => { queueRef.current = queue; }, [queue]);
  useEffect(() => { indexRef.current = index; }, [index]);

  const catalog = useMemo(() => Object.fromEntries(songs.map((song) => [song.id, song])), [songs]);
  const catalogBuffer = useMemo(() => songs.filter((song) => song.instrumental || Boolean(song.timed_lyrics?.lines?.length)), [songs]);
  const catalogBufferIds = useMemo(() => new Set(catalogBuffer.map((song) => song.id)), [catalogBuffer]);
  const current = catalog[queue[index]] || null;
  const { autoEq, setAutoEq, autoPreset, preset, displayGains, applyPreset, setBand } = useAutoEq(current);
  const upcoming = queue.slice(index + 1).map((id) => catalog[id]).filter(Boolean);
  const ahead = upcoming.length;
  const generating = Boolean(job && ["queued", "running"].includes(job.status));
  const readySongs = current ? 1 + ahead : 0;
  const catalogReady = queue.filter((id) => catalogBufferIds.has(id)).length;
  const startupTarget = catalogReady >= MIN_BUFFER_SIZE ? catalogReady : bufferSize;
  const buffering = on && !primed && readySongs < startupTarget;

  useEffect(() => { catalogBufferRef.current = catalogBuffer; }, [catalogBuffer]);

  useEffect(() => { onCurrentChange(current?.id ?? null); }, [current?.id, onCurrentChange]);

  useEffect(() => {
    if (on && !primed && readySongs >= startupTarget) setPrimed(true);
  }, [on, primed, readySongs, startupTarget]);

  useEffect(() => {
    if (waitingForNext && index + 1 < queue.length) {
      setWaitingForNext(false);
      setIndex((value) => value + 1);
    }
  }, [index, queue.length, waitingForNext]);

  function replacePending(next: Pick[]) {
    pendingRef.current = next;
    setPending(next);
  }

  useEffect(() => { onLeaveLibraryPlay(); }, []);
  useEffect(() => { void getVoiceProfiles(false).then((result) => setVoices(result.items)).catch(() => setVoices([])); }, []);

  useEffect(() => {
    if (!on || !job || job.kind !== "yue2" || ["succeeded", "failed", "cancelled"].includes(job.status)) return;
    const epoch = liveEpochRef.current;
    let active = true;
    let polling = false;
    const currentTurn = () => active && epoch === liveEpochRef.current;
    const timer = window.setInterval(async () => {
      if (polling || !currentTurn()) return;
      polling = true;
      try {
        const next = (await getJob(job.id)).job;
        if (!currentTurn()) return;
        if (next.status === "succeeded") {
          const folder = String(next.result?.folder_name || "");
          await refreshRef.current();
          if (!currentTurn()) return;
          let library = await getLibrary();
          if (!currentTurn()) return;
          let song = library.items.find((item) => item.folder_name === folder);
          if (song) {
            setGeneratedIds((ids) => new Set(ids).add(song!.id));
            setQueue((ids) => {
              if (ids.includes(song!.id)) return ids;
              const taken = new Set(
                ids.map((id) => library.items.find((item) => item.id === id)?.title.trim().toLowerCase()).filter(Boolean),
              );
              if (taken.has(song.title.trim().toLowerCase())) return ids;
              return [...ids, song!.id];
            });
          }
        }
        setJob(next);
        if (["succeeded", "failed", "cancelled"].includes(next.status)) {
          setActivePick(null);
          submitting.current = false;
        }
      } catch (reason: any) {
        if (!currentTurn()) return;
        setError(reason?.message ?? String(reason));
        setActivePick(null);
        submitting.current = false;
      } finally { polling = false; }
    }, 1500);
    return () => { active = false; window.clearInterval(timer); };
  }, [on, job?.id, job?.status]);

  async function writeSong(preset: StylePreset, pick: Pick, announce = true) {
    const note = (phase: string) => { if (announce) setWritingPhase(phase); };
    const description = liveDescription(preset, pick.instrumental, pick);
    try {
      if (pick.instrumental) {
        note("Requesting title");
        const result = await assistWriting({
          action: "title", idea: `${pick.template}. ${preset.mood}. Instrumental, no vocals.`,
          description, language: preset.language || "en", instrumental: true,
        });
        const title = (result.title || "").trim() || pick.template;
        note(`Title ready: ${title}`);
        return { title, lyrics: "" };
      }
      note("Writing title and lyrics");
      const idea = `${pick.template}. ${preset.mood}. ${castHint(pick.cast)} Write a distinctive song title and full tagged lyrics.`;
      const result = await assistWriting({
        action: "generate", idea, description, language: preset.language || "en", instrumental: false,
      });
      const title = (result.title || "").trim();
      const lyrics = (result.lyrics || "").trim();
      if (!title || !lyrics) throw new Error("Writing returned an empty title or lyrics");
      note(`Title ready: ${title}`);
      return { title, lyrics };
    } catch (reason) {
      if (announce) setWritingPhase("");
      throw reason;
    }
  }

  async function submit(pick: Pick) {
    const preset = presets[pick.template];
    if (!preset) return;
    const epoch = liveEpochRef.current;
    setError("");
    setLocked(pick);
    try {
      const ready = preparedRef.current?.pick.id === pick.id ? preparedRef.current : null;
      preparedRef.current = null;
      setWritingPhase(ready ? `Title ready: ${ready.title}` : "Writing title and lyrics");
      const written = ready || await writeSong(preset, pick, true);
      if (epoch !== liveEpochRef.current) return;
      const named = { ...pick, title: written.title };
      setLocked(named);
      setFlash(named);
      setWritingPhase("Ready — starting YuE2");
      const result = await generate({
        title: written.title,
        genre: pick.template,
        description: liveDescription(preset, pick.instrumental, pick),
        lyrics: written.lyrics,
        lyrics_language: preset.language || "en",
        instrumental: pick.instrumental,
        seed: null,
        cot_mode: "melody",
        cfg: 1.0,
        steps: 32,
        top_k: 100,
        temperature: 1.0,
        exclude_styles: "",
        vocal_gender: vocalGenderFor(pick.cast),
        voice_slots: pick.instrumental ? EMPTY_VOICE_SLOTS : { female: pick.female, male: pick.male, backing: "" },
      });
      if (epoch !== liveEpochRef.current) return;
      setJob(result.job);
      setWritingPhase("");
    } catch (reason: any) {
      if (epoch !== liveEpochRef.current) return;
      setError(reason?.message ?? String(reason));
      setWritingPhase("");
      setJob(null);
      setActivePick(null);
      submitting.current = false;
    }
  }

  function catalogFiller(count: number) {
    const currentId = queueRef.current[indexRef.current];
    const upcoming = new Set(queueRef.current.slice(indexRef.current));
    const unused = catalogBufferRef.current.filter((song) => !upcoming.has(song.id));
    let extra = randomCatalogIds(unused, count);
    if (extra.length < count) {
      const reuse = catalogBufferRef.current.filter((song) => song.id !== currentId && !extra.includes(song.id));
      extra = [...extra, ...randomCatalogIds(reuse, count - extra.length)];
    }
    return extra;
  }

  function refillIfStarving() {
    const remaining = queueRef.current.length - indexRef.current;
    if (remaining >= 2) return [];
    const extra = catalogFiller(Math.max(3, 3 - remaining));
    if (!extra.length) return [];
    queueRef.current = [...queueRef.current, ...extra];
    setQueue(queueRef.current);
    return extra;
  }

  function drawAndSubmit(lockedPick: Pick) {
    if (picking.current || !names.length) return;
    const epoch = liveEpochRef.current;
    picking.current = true;
    let ticks = 0;
    const timer = window.setInterval(() => {
      if (epoch !== liveEpochRef.current) {
        window.clearInterval(timer);
        drawTimerRef.current = null;
        picking.current = false;
        return;
      }
      setFlash(randomPick(names, voices));
      ticks += 1;
      if (ticks < 16) return;
      window.clearInterval(timer);
      drawTimerRef.current = null;
      setFlash(lockedPick);
      picking.current = false;
      void submit(lockedPick);
    }, 70);
    drawTimerRef.current = timer;
  }

  useEffect(() => {
    if (!on) return;
    const desiredAhead = queue.length ? bufferSize - 1 : bufferSize;
    const reserved = ahead + (activePick ? 1 : 0) + pending.length;
    const missing = desiredAhead - reserved;
    const avoid = [
      ...recentTemplates.current,
      ...pendingRef.current.map((item) => item.template),
      ...queue.slice(index).map((id) => catalog[id]?.genre || "").filter(Boolean),
    ];
    if (missing > 0) {
      const extra: Pick[] = [];
      const blocked = [...avoid];
      for (let i = 0; i < missing; i += 1) {
        const pick = randomPick(names, voices, blocked);
        extra.push(pick);
        blocked.push(pick.template);
      }
      replacePending([...pendingRef.current, ...extra]);
    } else if (!activePick && pending.length === 0) replacePending([randomPick(names, voices, avoid)]);
  }, [on, names, voices, queue.length, ahead, activePick, pending.length, bufferSize, catalog, index]);

  useEffect(() => {
    if (!on) return;
    refillIfStarving();
  }, [on, index, queue.length]);

  useEffect(() => {
    if (!on) return;
    const next = pending[0];
    if (!next || prefetching.current || preparedRef.current?.pick.id === next.id) return;
    if (activePick && next.id === activePick.id) return;
    if (!job || !["queued", "running"].includes(job.status)) return;
    const preset = presets[next.template];
    if (!preset) return;
    const epoch = liveEpochRef.current;
    prefetching.current = true;
    void writeSong(preset, next, false)
      .then((written) => {
        if (epoch !== liveEpochRef.current) return;
        preparedRef.current = { pick: next, title: written.title, lyrics: written.lyrics };
      })
      .catch((reason: any) => {
        if (epoch !== liveEpochRef.current) return;
        preparedRef.current = null;
        setError(reason?.message ?? String(reason));
      })
      .finally(() => {
        prefetching.current = false;
      });
  }, [on, pending, job?.id, job?.status, activePick, presets, voices]);

  useEffect(() => {
    if (!on || activePick || picking.current || submitting.current) return;
    const next = pendingRef.current[0];
    if (!next) return;
    replacePending(pendingRef.current.slice(1));
    setActivePick(next);
    setJob(null);
    submitting.current = true;
    recentTemplates.current = [...recentTemplates.current.filter((name) => name !== next.template), next.template].slice(-8);
    drawAndSubmit(next);
  }, [on, activePick, pending.length]);

  function startLive() {
    setError("");
    if (!voices.length) void getVoiceProfiles(false).then((result) => setVoices(result.items)).catch(() => undefined);
    setGeneratedIds(new Set());
    recentTemplates.current = [];
    preparedRef.current = null;
    const catalogCount = Math.min(catalogBuffer.length, Math.max(MIN_BUFFER_SIZE, bufferSize));
    setQueue(randomCatalogIds(catalogBuffer, catalogCount));
    setIndex(0);
    setOn(true);
  }

  function stopLive() {
    liveEpochRef.current += 1;
    if (drawTimerRef.current !== null) window.clearInterval(drawTimerRef.current);
    drawTimerRef.current = null;
    picking.current = false;
    setOn(false);
    setPrimed(false);
    setWaitingForNext(false);
    setGeneratedIds(new Set());
    replacePending([]);
    submitting.current = false;
    setActivePick(null);
    preparedRef.current = null;
    setWritingPhase("");
    void abortWriting().catch(() => undefined);
  }

  function skip() {
    if (index + 1 < queue.length) setIndex((value) => value + 1);
  }

  const shown = flash || locked;
  const shownVoices = shown ? reelVoices(shown) : { a: "", b: "" };
  const pendingCount = pending.length;
  const activeLabel = activePick ? (job?.kind === "lyrics_sync" ? "syncing lyrics" : generating ? (job?.status === "queued" ? "queued to be made" : "generating") : writingPhase || "preparing") : "";
  const stageEyebrow = picking.current ? "DRAWING" : writingPhase.startsWith("Ready") ? "READY" : writingPhase.startsWith("Title ready") ? "TITLE READY" : writingPhase ? "WRITING" : activeLabel === "syncing lyrics" ? "SYNCING LYRICS" : activeLabel === "queued to be made" ? "QUEUED TO MAKE" : generating ? "GENERATING" : activePick ? "PREPARING" : locked ? "SELECTED" : "LIVE";
  const femalePool = voices.filter((profile) => !profile.archived && (profile.role === "female" || profile.role === "any"));
  const malePool = voices.filter((profile) => !profile.archived && (profile.role === "male" || profile.role === "any"));

  return <section className="live-page">
    <aside className="live-wing live-wing-cast" aria-label="Cast reel">
      {CAST_ROLL.map((item) => <div className={`live-wing-chip ${shown?.cast === item.id ? "on" : ""}`} key={item.id} title={item.label}><img src={CAST_ART[item.id]} alt={item.label} /></div>)}
    </aside>
    <div className="live-main">
    {!on && <div className="live-settings card"><label className="live-buffer-size">Keep ready<select value={bufferSize} onChange={(event) => setBufferSize(Math.max(MIN_BUFFER_SIZE, Number(event.target.value)))}><option value="3">3 songs · short</option><option value="5">5 songs · balanced</option><option value="8">8 songs · long</option><option value="12">12 songs · overnight</option></select></label><small>{catalogBuffer.length ? "Starts from the catalog, keeps generating ahead, and pulls a random catalog song if the queue would go empty. OBS can end the stream on its own clock." : "No playback-ready catalog songs found; Live will generate the starting buffer."}</small></div>}
    <div className="live-layout">
      <div className="live-stage card">
        <div className="live-stage-head">
          <div className="eyebrow">{stageEyebrow}</div>
          <strong>{shown?.title || "Song generator"}</strong>
          <span>{ahead} ready ahead{pendingCount ? ` · ${pendingCount} queued` : ""}{activeLabel ? ` · ${activeLabel}` : ""}</span>
        </div>
        {shown ? <div className="live-reels">
          <div className={`live-reel ${picking.current ? "spinning" : "on"}`}>
            <small>Template</small>
            <img src={art[shown.template] || ""} alt="" />
            <b>{shown.template}</b>
          </div>
          <div className={`live-reel ${picking.current ? "spinning" : "on"}`}>
            <small>Cast</small>
            <img className="live-cast-art" src={CAST_ART[shown.cast]} alt={CAST_ROLL.find((item) => item.id === shown.cast)?.label || "Cast"} />
          </div>
          <div className={`live-reel ${picking.current ? "spinning" : shownVoices.a ? "on" : ""}`}>
            <small>Voice A</small>
            {shownVoices.a && voiceArt(shownVoices.a, voices) ? <img src={voiceArt(shownVoices.a, voices)} alt="" /> : <div className="live-reel-empty">—</div>}
            <b>{shownVoices.a ? voiceName(shownVoices.a, voices) : "None"}</b>
          </div>
          <div className={`live-reel ${picking.current ? "spinning" : shownVoices.b ? "on" : ""}`}>
            <small>Voice B</small>
            {shownVoices.b && voiceArt(shownVoices.b, voices) ? <img src={voiceArt(shownVoices.b, voices)} alt="" /> : <div className="live-reel-empty">—</div>}
            <b>{shownVoices.b ? voiceName(shownVoices.b, voices) : "None"}</b>
          </div>
        </div> : <div className="empty"><strong>Not live yet</strong><p>Start to draw template, cast, and voices, then generate.</p></div>}
        {locked && presets[locked.template] && <small className="live-mood">{writingPhase || presets[locked.template].mood}</small>}
        {job && <div className={`job-banner ${job.status}`}><div><strong>{shown?.title ? `${shown.title} · ${job.phase}` : job.phase}</strong><span>{job.error || `${Math.round(job.progress * 100)}%`}</span></div><div className="progress"><i style={{ width: `${Math.round(job.progress * 100)}%` }} /></div></div>}
        <div className="live-actions">
          {!on && <button type="button" className="primary" disabled={!ready} onClick={startLive}>Start live</button>}
          {on && <button type="button" className="danger" onClick={stopLive}>Stop</button>}
          <button type="button" disabled={!current || index + 1 >= queue.length} onClick={skip}>Skip</button>
        </div>
        {error && <div className="error">{error}</div>}
      </div>
      <div className="live-now card">
        {current ? <>
          <div className="radio-now">
            {coverSources[current.id] ? <img src={coverSources[current.id]} alt="" /> : <div className="radio-now-empty">♫</div>}
            <div><div className="eyebrow">{buffering ? "BUFFERING" : "NOW PLAYING"}</div><h3>{current.title}</h3><p>{current.instrumental ? "Instrumental" : "Vocal"}{current.genre ? ` · ${current.genre}` : ""}</p></div>
          </div>
          <aside className="live-eq">
            <div className="eyebrow">10-BAND EQ</div>
            <EqPanel autoEq={autoEq} setAutoEq={setAutoEq} autoPreset={autoPreset} preset={preset} displayGains={displayGains} applyPreset={applyPreset} setBand={setBand} note={autoEq ? `Auto EQ follows ${autoPreset}; sliders glide before each song. Custom sliders save on this machine.` : "Manual EQ is live on this station. Custom sliders save on this machine."} />
          </aside>
          {!on ? <div className="live-buffering">Station stopped</div> : buffering ? <div className="live-buffering">Buffering playback: {readySongs}/{startupTarget} songs ready</div> : waitingForNext ? <div className="live-buffering">Current song finished — waiting for the next buffered song</div> : <SongVisualizer key={current.id} src={liveSrc(current)} timedLyrics={current.timed_lyrics} eqGains={displayGains} compact onAnalyser={onAnalyserChange} onPlayingChange={onPlaybackChange} onEnded={() => { refillIfStarving(); if (indexRef.current + 1 < queueRef.current.length) { setWaitingForNext(false); setIndex(indexRef.current + 1); } else setWaitingForNext(true); }} />}
        </> : <div className="empty"><strong>Waiting on the first song</strong><p>The station plays as soon as a draw finishes generating.</p></div>}
        {on && queue.length > 0 && <div className="live-queue">
          <div className="live-queue-head"><div className="eyebrow">PLAYBACK QUEUE</div><small>{index + 1}/{queue.length} · position</small></div>
          <div className="live-queue-list">
            {queue.slice(index).map((id, offset) => {
              const song = catalog[id];
              if (!song) return null;
              const position = index + offset + 1;
              const state = offset === 0 ? "ON AIR" : offset === 1 ? "UP NEXT" : "QUEUED";
              return <div className={`live-queue-row ${offset === 0 ? "current on-air" : ""}`} aria-current={offset === 0 ? "true" : undefined} key={id}>
                <b>{String(position).padStart(2, "0")}</b>
                <img src={coverSources[id] || art[song.genre || ""] || ""} alt="" />
                <span><strong>{song.title}</strong><small>{generatedIds.has(id) ? "GENERATED · " : ""}{state}</small></span>
              </div>;
            })}
          </div>
        </div>}
      </div>
    </div>
    <div className="live-grid">
      {names.map((name) => <button type="button" key={name} className={`live-card ${shown?.template === name ? "picked" : ""}`} disabled>
        <img src={art[name] || ""} alt="" />
        <span>{name}</span>
      </button>)}
    </div>
    </div>
    <aside className="live-wing live-wing-voices" aria-label="Voice reel">
      {[...femalePool, ...malePool.filter((profile) => !femalePool.some((item) => item.id === profile.id))].map((profile) => {
        const selected = shown?.female === profile.id || shown?.male === profile.id;
        return <div className={`live-wing-voice ${selected ? "on" : ""}`} key={profile.id}>
          {voiceArt(profile.id, voices) ? <img src={voiceArt(profile.id, voices)} alt="" /> : <span>{profile.name.slice(0, 1)}</span>}
          <b>{profile.name}</b>
        </div>;
      })}
    </aside>
  </section>;
}
