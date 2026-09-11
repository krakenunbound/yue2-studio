import { invoke } from "@tauri-apps/api/core";

let cachedBase: string | null = null;
async function base(): Promise<string> {
  if (cachedBase) return cachedBase;
  try { cachedBase = await invoke<string>("sidecar_url"); }
  catch { cachedBase = "http://127.0.0.1:7794"; }
  return cachedBase;
}

function headerValue(headers: HeadersInit | undefined, name: string): string | undefined {
  if (!headers) return undefined;
  const needle = name.toLowerCase();
  if (headers instanceof Headers) return headers.get(name) ?? undefined;
  if (Array.isArray(headers)) return headers.find(([key]) => key.toLowerCase() === needle)?.[1];
  const record = headers as Record<string, string>;
  const match = Object.keys(record).find((key) => key.toLowerCase() === needle);
  return match ? record[match] : undefined;
}

function errorDetail(status: number, raw: string): string {
  try {
    const parsed = JSON.parse(raw);
    const detail = parsed?.detail ?? parsed;
    return typeof detail === "string" ? detail : JSON.stringify(detail);
  } catch {
    return raw || `${status}`;
  }
}

type SidecarHttpResult = { status: number; body: string };

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  if ("__TAURI_INTERNALS__" in window) {
    const method = String(options?.method || "GET").toUpperCase();
    const rawBody = options?.body;
    const body = rawBody == null ? null : typeof rawBody === "string" ? rawBody : String(rawBody);
    const result = await invoke<SidecarHttpResult>("sidecar_http", {
      method,
      path,
      body,
      contentType: headerValue(options?.headers, "Content-Type") ?? undefined,
    });
    if (result.status < 200 || result.status >= 300) {
      throw new Error(errorDetail(result.status, result.body));
    }
    return JSON.parse(result.body) as T;
  }

  const url = (await base()) + path;
  let response: Response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(`Studio could not call ${url} (${message})`);
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try { detail = (await response.json()).detail ?? detail; } catch { /* retain status */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json() as T;
}

export type ModelStatus = { root: string; exists: boolean; ready: boolean; missing: string[]; present: number; required: number; size_bytes: number; source: string };
export type ServiceStatus = { online: boolean; url: string; detail: string; standalone?: boolean; worker_loaded?: boolean };
export type GpuPolicy = { available?: boolean; measured?: boolean; total_gb?: number; reserved_gb?: number; budget_gb?: number; memory_fraction?: number; drives_display?: boolean; overridden?: boolean; override_env?: string; reason?: string };
export type GpuStatus = { detected: boolean; name: string | null; vram_total_mb: number | null; vram_free_mb: number | null; usage: number | null; temperature: number | null; driver: string | null; policy?: GpuPolicy };
export type CoverArtStatus = { ready: boolean; model: string; filename: string; size_bytes: number; source: string; detail: string };
export type UtilityStatus = { ready: boolean; model?: string; root?: string; detail?: string };
export type Job = { id: string; kind: string; status: string; phase: string; progress: number; stage_progress?: number | null; eta_seconds?: number | null; result?: any; error?: string | null; created_at: number };
export type TimedWord = { text: string; start: number; end: number };
export type TimedLyricLine = { index: number; text: string; translation?: string; start: number; end: number; matchScore?: number; words?: TimedWord[] };
export type TimedLyrics = { language: string; translation_language?: string; alignment_method?: string; line_count?: number; word_count?: number; lines: TimedLyricLine[] };
export type StudioRange = { start: number; end: number };
export type StudioEffectKind = "gain_up" | "gain_down" | "echo" | "reverb" | "auto_level" | "normalize" | "clarity" | "compressor" | "auto_pan" | "low_pass" | "high_pass" | "telephone" | "saturation" | "tremolo" | "stereo_widen" | "limiter";
export type StudioEffectRegion = StudioRange & {
  id: string;
  kind: StudioEffectKind;
  amount: number;
  instance?: number | null;
  fade_in?: number;
  fade_out?: number;
};
export type StudioClip = { id: string; start: number; source_in: number; source_out: number | null; fade_in: number; fade_out: number; gain?: number; gain_left?: number; gain_right?: number };
export type StudioTrackState = { name: string; gain: number; muted: boolean; solo: boolean; offset?: number; trim_start?: number; trim_end?: number | null; fade_in?: number; fade_out?: number; cuts?: StudioRange[]; effects?: StudioEffectRegion[]; clips?: StudioClip[]; use_clips?: boolean };
export type StudioSession = { tracks: StudioTrackState[]; updated_at?: string };
export type StudioImport = { file: string; name: string; original?: string; duration?: number; effect_id?: string; combined_sources?: StudioImport[] };
export type SoundEffect = { id: string; name: string; prompt: string; negative_prompt?: string; duration: number; seed: number | null; created_at: string; url: string };
export type Playlist = { id: string; name: string; song_ids: string[]; created_at: string };
export type Workspace = { id: string; name: string; song_ids: string[]; created_at: string };
export type VoiceSlots = { female?: string; male?: string; backing?: string };
export type VoiceProfile = {
  id: string; name: string; role: "female" | "male" | "backing" | "any";
  register: string; timbre: string; delivery: string; accent: string; vibrato: string;
  dynamics: string; harmony: string; effects: string; audition_notes: string; expanded: string;
  built_in: boolean; archived: boolean; created_at?: string; updated_at?: string; slot?: string;
};
export type VoiceCompileResult = { applied: boolean; description: string; preview: string; slots: VoiceSlots; snapshots: VoiceProfile[]; assignments?: string[] };
export type Song = { id: string; title: string; artist?: string; album?: string; genre?: string; year?: string; track_number?: string; description: string; lyrics: string; english_translation?: string; lyrics_language?: string; timed_lyrics?: TimedLyrics | null; instrumental: boolean; seed: number | null; duration?: number; steps?: number; cfg?: number; top_k?: number; temperature?: number; cot_mode?: "full" | "melody" | "off"; abc_score?: string; exclude_styles?: string; vocal_gender?: "auto" | "female" | "male"; prompt_tokens?: number; voice_slots?: VoiceSlots; voice_snapshots?: VoiceProfile[]; audio_url: string; original_audio_url?: string | null; cover_url?: string | null; cover_error?: string | null; stems?: string[]; studio?: StudioSession; studio_imports?: StudioImport[]; studio_mixes?: { file: string; variant: string; created_at: string }[]; created_at: string; folder: string; folder_name: string };
export type AiCapabilityStatus = { configured: boolean; enabled: boolean; provider: string };
export type AiProviderPublic = { label: string; configured: boolean; last4: string | null; updated_at: string | null };
export type AiCapabilityState = { enabled: boolean; provider: string; model: string };
export type AiKeysView = {
  version: number;
  catalog: {
    providers: Record<string, { label: string; jobs: string[] }>;
    capabilities: Record<string, { label: string; blurb: string; providers: string[]; local_ok: boolean; how?: { summary: string; rules: string[]; constraints?: Record<string, unknown> } }>;
  };
  providers: Record<string, AiProviderPublic>;
  capabilities: Record<string, AiCapabilityState>;
};
export type SoundEffectsEngineStatus = UtilityStatus & { runtime_ready?: boolean; processor?: string; size_bytes?: number; present?: number; required?: number; max_duration?: number };
export type Status = { model: ModelStatus; cover_art: CoverArtStatus; stems: UtilityStatus; sound_effects: SoundEffectsEngineStatus & { models?: { stable: SoundEffectsEngineStatus; woosh: SoundEffectsEngineStatus } }; lyrics_sync: UtilityStatus; exports: UtilityStatus; service: ServiceStatus; gpu: GpuStatus; ai?: Record<string, AiCapabilityStatus>; jobs: Job[] };
export type LogEntry = { id: number; ts: number; level: string; logger: string; message: string };
export type ModelInstallStatus = { status: "idle" | "running" | "succeeded" | "failed" | "cancelled"; phase: string; progress: number; error?: string | null };
export type DownloadableModel = {
  id: "yue2" | "whisper" | "cover_art" | "stems" | "sound_effects";
  name: string; description: string; does: string; optional: boolean;
  gated?: boolean; source_url?: string;
  ready: boolean; model_ready: boolean; runtime_ready: boolean;
  download_bytes: number; required_free_bytes: number; free_bytes: number;
  folder: string; detail: string; install: ModelInstallStatus;
};

export const getStatus = () => request<Status>("/api/status");
export const getModels = () => request<{ items: DownloadableModel[] }>("/api/models");
export const installModel = (id: DownloadableModel["id"], token?: string) => request<{ item?: DownloadableModel }>(`/api/models/${encodeURIComponent(id)}/install`, { method: "POST", headers: token ? { "Content-Type": "application/json" } : undefined, body: token ? JSON.stringify({ token }) : undefined });
export const cancelModelInstall = (id: DownloadableModel["id"]) => request<{ item?: DownloadableModel }>(`/api/models/${encodeURIComponent(id)}/cancel`, { method: "POST" });
export const getAiKeys = () => request<AiKeysView>("/api/settings/ai-keys");
export const saveAiKeys = (body: { providers?: Record<string, { key?: string; clear?: boolean }>; capabilities?: Record<string, { enabled?: boolean; provider?: string; model?: string }> }) => request<AiKeysView>("/api/settings/ai-keys", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export type ChatMessage = { role: "user" | "assistant"; content: string };
export const assistChat = (body: { messages: ChatMessage[]; language?: string; instrumental?: boolean }) => request<{ reply: string; brief: string; ready: boolean }>("/api/assist/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const assistWriting = (body: { action: "generate" | "optimize" | "title" | "describe" | "compose" | "effect"; idea?: string; random?: boolean; title?: string; description?: string; lyrics?: string; language?: string; instrumental?: boolean; effect_engine?: "stable" | "woosh" }) => request<{ lyrics?: string; title?: string; description?: string; references?: string }>("/api/assist/writing", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const getVoiceProfiles = (archived = true) => request<{ items: VoiceProfile[] }>(`/api/voices?archived=${archived ? "true" : "false"}`);
export const createVoiceProfile = (body: Partial<VoiceProfile>) => request<{ profile: VoiceProfile }>("/api/voices", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const updateVoiceProfile = (id: string, body: Partial<VoiceProfile>) => request<{ profile: VoiceProfile }>(`/api/voices/${encodeURIComponent(id)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const duplicateVoiceProfile = (id: string) => request<{ profile: VoiceProfile }>(`/api/voices/${encodeURIComponent(id)}/duplicate`, { method: "POST" });
export const archiveVoiceProfile = (id: string) => request<{ id: string; archived: boolean; deleted: boolean }>(`/api/voices/${encodeURIComponent(id)}`, { method: "DELETE" });
export const importVoiceProfiles = (profiles: Partial<VoiceProfile>[]) => request<{ items: VoiceProfile[] }>("/api/voices/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profiles }) });
export const compileVoices = (body: { slots: VoiceSlots; lyrics?: string; description?: string; snapshots?: VoiceProfile[] }) => request<VoiceCompileResult>("/api/voices/compile", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const refreshModels = () => request<ModelStatus>("/api/models/refresh", { method: "POST" });
export const clearMemory = () => request<{ cleared: boolean; had_worker: boolean }>("/api/clear-memory", { method: "POST" });
export const getLibrary = () => request<{ items: Song[] }>("/api/library");
export const getPlaylists = () => request<{ items: Playlist[] }>("/api/playlists");
export const createPlaylist = (name: string) => request<{ playlist: Playlist }>("/api/playlists", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
export const deletePlaylist = (id: string) => request<{ deleted: boolean }>(`/api/playlists/${encodeURIComponent(id)}`, { method: "DELETE" });
export const addSongToPlaylist = (playlistId: string, songId: string) => request<{ added: boolean }>(`/api/playlists/${encodeURIComponent(playlistId)}/songs/${encodeURIComponent(songId)}`, { method: "POST" });
export const removeSongFromPlaylist = (playlistId: string, songId: string) => request<{ removed: boolean }>(`/api/playlists/${encodeURIComponent(playlistId)}/songs/${encodeURIComponent(songId)}`, { method: "DELETE" });
export const getWorkspaces = () => request<{ items: Workspace[] }>("/api/workspaces");
export const createWorkspace = (name: string) => request<{ workspace: Workspace }>("/api/workspaces", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
export const deleteWorkspace = (id: string) => request<{ deleted: boolean }>(`/api/workspaces/${encodeURIComponent(id)}`, { method: "DELETE" });
export const moveSongToWorkspace = (workspaceId: string, songId: string) => request<{ moved: boolean }>(`/api/workspaces/${encodeURIComponent(workspaceId)}/songs/${encodeURIComponent(songId)}`, { method: "POST" });
export const updateSong = (folder: string, body: Pick<Song, "title" | "artist" | "album" | "genre" | "year" | "track_number" | "description" | "lyrics" | "english_translation" | "lyrics_language">) => request<{ updated: boolean }>(`/api/library/${encodeURIComponent(folder)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const openSongFolder = (folder: string) => request<{ path: string }>(`/api/library/${encodeURIComponent(folder)}/open`, { method: "POST" });
export const deleteSong = (folder: string) => request<{ deleted: boolean }>(`/api/library/${encodeURIComponent(folder)}`, { method: "DELETE" });
export const regenerateCover = (folder: string, direction: string) => request<{ job: Job }>(`/api/library/${encodeURIComponent(folder)}/cover`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ direction }) });
export const uploadSongCover = (folder: string, file: File) => request<{ uploaded: boolean; cover_url: string }>(`/api/library/${encodeURIComponent(folder)}/cover/upload?filename=${encodeURIComponent(file.name)}`, { method: "POST", headers: { "Content-Type": file.type || "application/octet-stream" }, body: file });
export const convertAudio = (folder: string, format: "mp3" | "flac") => request<{ download_url: string; filename: string }>(`/api/library/${encodeURIComponent(folder)}/export/${format}`, { method: "POST" });
export const extractStems = (folder: string, mode: "2" | "4") => request<{ job: Job }>(`/api/library/${encodeURIComponent(folder)}/stems`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode }) });
export const saveStudioSession = (folder: string, tracks: StudioTrackState[]) => request<{ saved: boolean }>(`/api/library/${encodeURIComponent(folder)}/studio`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tracks }) });
export const bounceStudioMix = (folder: string, tracks: StudioTrackState[], variant: "custom" | "instrumental" | "acapella", selection?: StudioRange | null, contentEnd?: number) => request<{ download_url: string; filename: string; promoted?: boolean; exported?: boolean; exported_folder?: string; exported_title?: string; audio_url?: string; original_audio_url?: string }>(`/api/library/${encodeURIComponent(folder)}/studio/bounce`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tracks, variant, selection, content_end: contentEnd ?? null }) });
export const importStudioTrack = async (folder: string, file: File) => request<{ file: string; name: string; url: string }>(`/api/library/${encodeURIComponent(folder)}/studio/import?filename=${encodeURIComponent(file.name)}`, { method: "POST", headers: { "Content-Type": file.type || "application/octet-stream" }, body: file });
export const generateStudioSound = (folder: string, body: { prompt: string; name?: string; negative_prompt?: string; duration: number; steps?: number; sampler?: string; chunked_decode?: boolean; engine?: "stable" | "woosh"; cfg?: number; seed?: number | null }) => request<{ job: Job }>(`/api/library/${encodeURIComponent(folder)}/studio/generate-sfx`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const getEffects = () => request<{ items: SoundEffect[] }>("/api/effects");
export const generateEffect = (body: { prompt: string; name?: string; negative_prompt?: string; duration: number; steps?: number; sampler?: string; chunked_decode?: boolean; engine?: "stable" | "woosh"; cfg?: number; seed?: number | null }) => request<{ job: Job }>("/api/effects/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const addEffectToStudio = (effectId: string, folder: string) => request<{ file: string; name: string; url: string; duration?: number }>(`/api/effects/${encodeURIComponent(effectId)}/add-to-studio/${encodeURIComponent(folder)}`, { method: "POST" });
export const deleteEffect = (effectId: string) => request<{ deleted: boolean }>(`/api/effects/${encodeURIComponent(effectId)}`, { method: "DELETE" });
export const removeStudioTrack = (folder: string, filename: string) => request<{ removed: boolean }>(`/api/library/${encodeURIComponent(folder)}/studio/tracks/${encodeURIComponent(filename)}`, { method: "DELETE" });
export const synchronizeLyrics = (folder: string) => request<{ job: Job }>(`/api/library/${encodeURIComponent(folder)}/lyrics-sync`, { method: "POST" });
export const generate = (body: object) => request<{ job: Job }>("/api/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
export const getJob = (id: string) => request<{ job: Job }>(`/api/jobs/${id}`);
export const cancelJob = (id: string) => request<{ status: string }>(`/api/jobs/${id}/cancel`, { method: "POST" });
export const getLogs = (since?: number) => request<{ items: LogEntry[]; last_id: number; reset?: boolean }>(`/api/logs?limit=800${since == null ? "" : `&since_id=${since}`}`);
export const clearLogs = () => request<{ cleared: boolean }>("/api/logs/clear", { method: "POST" });
export const openOutputs = () => request<{ path: string }>("/api/open-outputs", { method: "POST" });
export async function audioUrl(path: string): Promise<string> { return (await base()) + path; }
export async function downloadUrl(path: string): Promise<string> { return (await base()) + path; }
export async function videoStudioUrl(song: Song, workspace: string): Promise<string> {
  const origin = await base();
  const totalSeconds = Math.max(0, Math.round(song.duration || 0));
  const query = new URLSearchParams({
    embedded: "1",
    songId: song.folder_name,
    title: song.title || "Untitled Song",
    workspace,
    durationLabel: totalSeconds ? `${Math.floor(totalSeconds / 60)}:${String(totalSeconds % 60).padStart(2, "0")}` : "",
    vocalLanguage: song.instrumental ? "Instrumental" : (song.lyrics_language || ""),
    audioUrl: `${origin}${song.audio_url}`,
    coverUrl: song.cover_url ? `${origin}${song.cover_url}` : "",
    lyricsUrl: song.timed_lyrics?.lines?.length ? `${origin}/api/library/${encodeURIComponent(song.folder_name)}/timed-lyrics` : "",
  });
  return `${origin}/video-studio?${query.toString()}`;
}

export type StudioCombineResult = { imports: StudioImport[]; tracks: StudioTrackState[]; removed: string[] };
export const combineStudioTracks = (folder: string, tracks: StudioTrackState[], files: string[], name: string) => request<StudioCombineResult>(`/api/library/${encodeURIComponent(folder)}/studio/combine`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tracks, files, name }) });
export const uncombineStudioTracks = (folder: string, filename: string, tracks: StudioTrackState[]) => request<StudioCombineResult>(`/api/library/${encodeURIComponent(folder)}/studio/uncombine/${encodeURIComponent(filename)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ tracks }) });
