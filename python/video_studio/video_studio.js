const params = new URLSearchParams(window.location.search);
const audioUrl = params.get("audioUrl") || "";
const songTitle = params.get("title") || "Untitled Song";
const songSummary = params.get("summary") || "";
const coverUrl = params.get("coverUrl") || "";
const styleText = params.get("style") || "";
const songId = params.get("songId") || "";
const initialLyricsUrl = params.get("lyricsUrl") || "";
const workspaceTitle = params.get("workspace") || "";
const durationLabel = params.get("durationLabel") || "";
const bpmValue = params.get("bpm") || "";
const keyScale = params.get("keyScale") || "";
const vocalLanguage = params.get("vocalLanguage") || "";
const embedded = params.get("embedded") === "1";
const noSpaceLanguages = new Set(["ja", "zh", "ko"]);
const ASPECT_MODES = {
    landscape: {
        label: "Landscape",
        ratioLabel: "16:9",
        previewCopy: "16:9 framing for YouTube, Rumble, and X.",
        statusCopy: "Landscape works for YouTube, Rumble, and X. Portrait works for TikTok, Reels, and Shorts.",
        width: 1920,
        height: 1080,
        coverAspect: "landscape",
        frameSuffix: "16x9",
    },
    portrait: {
        label: "Portrait",
        ratioLabel: "9:16",
        previewCopy: "9:16 framing for TikTok, Reels, and Shorts.",
        statusCopy: "Portrait keeps titles, lyrics, and cover art centered for short-form vertical posts.",
        width: 1080,
        height: 1920,
        coverAspect: "portrait",
        frameSuffix: "9x16",
    },
};

const elements = {
    title: document.getElementById("track-title"),
    trackWorkspace: document.getElementById("track-workspace"),
    trackLength: document.getElementById("track-length"),
    trackFormatPill: document.getElementById("track-format-pill"),
    loadStatus: document.getElementById("load-status"),
    particleStatus: document.getElementById("particle-status"),
    formatStatus: document.getElementById("format-status"),
    formatLabel: document.getElementById("format-label"),
    formatResolution: document.getElementById("format-resolution"),
    previewFormatTitle: document.getElementById("preview-format-title"),
    previewFormatCopy: document.getElementById("preview-format-copy"),
    ratioLandscape: document.getElementById("ratio-landscape"),
    ratioPortrait: document.getElementById("ratio-portrait"),
    renderStatus: document.getElementById("render-status"),
    previewStage: document.getElementById("preview-stage"),
    canvas: document.getElementById("visualizer-canvas"),
    audio: document.getElementById("source-audio"),
    playToggle: document.getElementById("play-toggle"),
    seek: document.getElementById("seek"),
    timeCurrent: document.getElementById("time-current"),
    timeTotal: document.getElementById("time-total"),
    volume: document.getElementById("volume"),
    bgRandom: document.getElementById("bg-random"),
    bgImage: document.getElementById("bg-image"),
    bgVideo: document.getElementById("bg-video"),
    uploadImage: document.getElementById("upload-image"),
    uploadVideo: document.getElementById("upload-video"),
    imageInput: document.getElementById("image-input"),
    videoInput: document.getElementById("video-input"),
    bgDim: document.getElementById("bg-dim"),
    particleCount: document.getElementById("particle-count"),
    lyricsOn: document.getElementById("lyrics-on"),
    lyricsOff: document.getElementById("lyrics-off"),
    dualLyricsRow: document.getElementById("dual-lyrics-row"),
    dualOn: document.getElementById("dual-on"),
    dualOff: document.getElementById("dual-off"),
    lyricsStatus: document.getElementById("lyrics-status"),
    syncLyrics: document.getElementById("sync-lyrics"),
    coverStatus: document.getElementById("cover-status"),
    generateCover: document.getElementById("generate-cover"),
    useCoverBackground: document.getElementById("use-cover-background"),
    centerImageOn: document.getElementById("center-image-on"),
    centerImageOff: document.getElementById("center-image-off"),
    renderVideo: document.getElementById("render-video"),
    renderCancel: document.getElementById("render-cancel"),
    downloadFrame: document.getElementById("download-frame"),
};

const ctx = elements.canvas.getContext("2d", { alpha: false, desynchronized: true });
const state = {
    preset: "orbit",
    aspectMode: "landscape",
    backgroundMode: "random",
    backgroundDim: Number(elements.bgDim.value) / 100,
    sceneA: "#000000",
    sceneB: "#000000",
    sceneKind: "solid",
    particleStyle: "dust",
    particleCount: Number(elements.particleCount.value),
    lyricsEnabled: Boolean(initialLyricsUrl),
    dualLyrics: true,
    lyricLines: [],
    lyricsLanguage: "en",
    currentLyricsUrl: initialLyricsUrl,
    lyricsSyncJobId: "",
    lyricsPollTimer: null,
    lyricsSyncBusy: false,
    lyricsPollFailures: 0,
    lyricsSyncNotified: "",
    audioSrcBackup: "",
    songHasAlignableLyrics: false,
    imageUrl: "",
    videoUrl: "",
    isRendering: false,
    coverArt: { status: "missing", imageUrl: "", downloadUrl: "", workflowName: "" },
    coverArtJobId: "",
    centerImage: true,
};

let audioContext = null;
let analyser = null;
let sourceNode = null;
let frequencyData = new Uint8Array(256);
let waveformData = new Uint8Array(256);
let coverImage = null;
let backgroundImage = null;
let backgroundVideo = null;
let renderFrame = 0;
let previewResizeObserver = null;

function notifyMainStudioPlayback() {
    const message = { type: "kraken-audio:video-studio-playback" };
    const targetOrigin = "*";
    if (window.parent && window.parent !== window) {
        window.parent.postMessage(message, targetOrigin);
    }
    if (window.opener && !window.opener.closed) {
        window.opener.postMessage(message, targetOrigin);
    }
}

const PARTICLE_STYLES = {
    dust: "Floating dust motes drifting across the frame.",
    rain: "A rain sheet: thin vertical streaks, nearer drops longer and faster.",
    stars: "Twinkling starfield with occasional falling shooting stars.",
    embers: "Rising embers that climb the full frame and fade near the top.",
    warp: "A star-tunnel rush out from the cover art.",
    notes: "Music notes drifting up around the cover.",
    bokeh: "Soft out-of-focus orbs drifting with the beat.",
    snow: "Slow flakes falling with a gentle wobble.",
    bubbles: "Soap bubbles rising and popping at the top.",
};

function visualCenter(width, height) {
    const portrait = state.aspectMode === "portrait";
    const lyricsNeedCenterStage = state.lyricsEnabled && lyricsAreCentered();
    return {
        x: width / 2,
        // Split, Skyline, and Peak reserve the middle of the frame for
        // karaoke. Keep the cover above that lane instead of painting it
        // underneath the sung and translated lines.
        y: portrait
            ? (lyricsNeedCenterStage ? height * 0.16 : height * 0.39)
            : (lyricsNeedCenterStage ? height * 0.21 : (height / 2) - 40),
        radius: Math.min(width, height) * (portrait ? 0.19 : 0.14),
    };
}

function vizFocus(width, height) {
    if (state.centerImage) {
        return visualCenter(width, height);
    }
    const portrait = state.aspectMode === "portrait";
    return {
        x: width / 2,
        y: portrait ? height * 0.4 : height * 0.45,
        radius: 0,
    };
}

let fxParticles = [];
let shootingStars = [];
let lastFxTimestamp = 0;
let particleCache = { style: "", count: -1, width: 0, height: 0 };

function formatDuration(seconds) {
    if (!Number.isFinite(seconds) || seconds <= 0) {
        return "0:00";
    }
    const whole = Math.floor(seconds);
    const minutes = Math.floor(whole / 60);
    const remainder = whole % 60;
    return `${minutes}:${String(remainder).padStart(2, "0")}`;
}

function setStatus(target, message) {
    target.textContent = message;
}

async function fetchJson(url, options = {}, timeoutMs = 8000) {
    const abort = new AbortController();
    const timer = window.setTimeout(() => abort.abort(), timeoutMs);
    try {
        const response = await fetch(url, { cache: "no-store", ...options, signal: abort.signal });
        let payload = {};
        try {
            payload = await response.json();
        } catch {
            payload = {};
        }
        return { response, payload };
    } finally {
        window.clearTimeout(timer);
    }
}

function jobErrorDetail(payload, fallback) {
    const detail = payload?.detail;
    if (typeof detail === "string" && detail) {
        return detail;
    }
    return fallback;
}

function jobKindLabel(kind) {
    return {
        yue2: "song generation",
        music3: "song generation",
        cover_art: "cover art",
        stems: "stem extraction",
        audio_export: "audio export",
        lyrics_sync: "another lyric sync",
        stable_sfx: "sound-effect generation",
    }[kind] || "another studio job";
}

function queuedLyricsStatus(blocker) {
    if (blocker?.kind) {
        return `Queued behind ${jobKindLabel(blocker.kind)}. Lyric sync starts when that job finishes.`;
    }
    return "Queued. Lyric sync starts when the studio is free.";
}

async function findBlockingJob(lyricsJobId) {
    try {
        const { response, payload } = await fetchJson("/api/status", {}, 5000);
        if (!response.ok) {
            return null;
        }
        return (payload.jobs || []).find((item) => item.status === "running" && item.id !== lyricsJobId) || null;
    } catch {
        return null;
    }
}

function releaseAudioForSync() {
    if (state.audioSrcBackup) {
        return;
    }
    state.audioSrcBackup = elements.audio.currentSrc || elements.audio.src || audioUrl;
    elements.audio.pause();
    elements.audio.removeAttribute("src");
    elements.audio.load();
}

function restoreAudioAfterSync() {
    const src = state.audioSrcBackup;
    if (!src) {
        return;
    }
    state.audioSrcBackup = "";
    if (elements.audio.src !== src) {
        elements.audio.src = src;
    }
}

function clearLyricsPoll() {
    if (state.lyricsPollTimer) {
        window.clearTimeout(state.lyricsPollTimer);
        state.lyricsPollTimer = null;
    }
}

function scheduleLyricsPoll(jobId, delayMs) {
    clearLyricsPoll();
    if (!jobId) {
        return;
    }
    state.lyricsPollTimer = window.setTimeout(() => pollLyricsSyncJob(jobId), delayMs);
}

function setButtonBusy(button, busy, busyLabel, idleLabel) {
    button.disabled = busy;
    button.textContent = busy ? busyLabel : idleLabel;
}

function currentAspectConfig() {
    return ASPECT_MODES[state.aspectMode] || ASPECT_MODES.landscape;
}

function updateCanvasDisplaySize() {
    const stage = elements.previewStage;
    if (!stage) {
        return;
    }
    const stageWidth = Math.max(260, stage.clientWidth - 48);
    const stageHeight = Math.max(260, stage.clientHeight - 48);
    const aspect = elements.canvas.width / Math.max(1, elements.canvas.height);
    let drawWidth = stageWidth;
    let drawHeight = drawWidth / aspect;
    if (drawHeight > stageHeight) {
        drawHeight = stageHeight;
        drawWidth = drawHeight * aspect;
    }
    elements.canvas.style.width = `${Math.max(220, Math.floor(drawWidth))}px`;
    elements.canvas.style.height = `${Math.max(220, Math.floor(drawHeight))}px`;
}

function setAspectMode(mode) {
    const config = ASPECT_MODES[mode] || ASPECT_MODES.landscape;
    state.aspectMode = mode in ASPECT_MODES ? mode : "landscape";
    elements.ratioLandscape.classList.toggle("active", state.aspectMode === "landscape");
    elements.ratioPortrait.classList.toggle("active", state.aspectMode === "portrait");
    elements.previewStage.dataset.aspect = state.aspectMode;
    elements.canvas.width = config.width;
    elements.canvas.height = config.height;
    elements.trackFormatPill.textContent = config.ratioLabel;
    elements.formatLabel.textContent = config.label;
    elements.formatResolution.textContent = `${config.width} x ${config.height} render canvas`;
    elements.previewFormatTitle.textContent = `${config.label} Preview`;
    elements.previewFormatCopy.textContent = config.previewCopy;
    elements.formatStatus.textContent = config.statusCopy;
    window.requestAnimationFrame(updateCanvasDisplaySize);
}

function setBackgroundMode(mode) {
    state.backgroundMode = mode;
    elements.bgRandom.classList.toggle("active", mode === "random");
    elements.bgImage.classList.toggle("active", mode === "image");
    elements.bgVideo.classList.toggle("active", mode === "video");
}

function updatePresetButtons() {
    document.querySelectorAll("[data-preset]").forEach((button) => {
        button.classList.toggle("active", button.dataset.preset === state.preset);
    });
}

function setLyricsEnabled(enabled) {
    state.lyricsEnabled = Boolean(enabled) && state.lyricLines.length > 0;
    elements.lyricsOn.classList.toggle("active", state.lyricsEnabled);
    elements.lyricsOff.classList.toggle("active", !state.lyricsEnabled);
}

function hasLyricTranslations() {
    return state.lyricLines.some((line) => line.translation);
}

function setDualLyrics(enabled) {
    state.dualLyrics = Boolean(enabled) && hasLyricTranslations();
    if (elements.dualLyricsRow) {
        elements.dualLyricsRow.hidden = !hasLyricTranslations();
    }
    if (elements.dualOn) {
        elements.dualOn.classList.toggle("active", state.dualLyrics);
        elements.dualOff.classList.toggle("active", !state.dualLyrics);
    }
}

function canAlignLyrics(song) {
    return Boolean((song?.lyrics || "").trim())
        && !song?.instrumental
        && Boolean(song?.audio_url);
}

function setLyricsSyncButton(visible, disabled, label = "Sync Lyrics") {
    elements.syncLyrics.style.display = visible ? "" : "none";
    elements.syncLyrics.disabled = disabled;
    elements.syncLyrics.textContent = label;
}

function escapeAssText(text) {
    return String(text || "")
        .replaceAll("\\", "\\\\")
        .replaceAll("{", "(")
        .replaceAll("}", ")");
}

async function ensureAudioGraph() {
    if (audioContext && analyser && sourceNode) {
        if (audioContext.state === "suspended") {
            await audioContext.resume();
        }
        return;
    }

    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    audioContext = new AudioContextCtor();
    analyser = audioContext.createAnalyser();
    analyser.fftSize = 512;
    analyser.smoothingTimeConstant = 0.84;
    sourceNode = audioContext.createMediaElementSource(elements.audio);
    sourceNode.connect(analyser);
    analyser.connect(audioContext.destination);
    frequencyData = new Uint8Array(analyser.frequencyBinCount);
    waveformData = new Uint8Array(analyser.frequencyBinCount);
}

function loadImage(url) {
    return new Promise((resolve, reject) => {
        const image = new Image();
        image.crossOrigin = "anonymous";
        image.onload = () => resolve(image);
        image.onerror = reject;
        image.src = url;
    });
}

function loadVideo(url) {
    return new Promise((resolve, reject) => {
        const video = document.createElement("video");
        video.crossOrigin = "anonymous";
        video.src = url;
        video.loop = true;
        video.muted = true;
        video.playsInline = true;
        video.preload = "auto";
        video.onloadeddata = () => resolve(video);
        video.onerror = reject;
    });
}

function blendColor(alpha, color) {
    if (typeof color === "string" && color.trim().toLowerCase().startsWith("hsl")) {
        const open = color.indexOf("(");
        const close = color.lastIndexOf(")");
        const channels = color.slice(open + 1, close).split(",").slice(0, 3).join(",").trim();
        return `hsla(${channels}, ${alpha})`;
    }
    const hex = color.replace("#", "");
    const normalized = hex.length === 3 ? hex.split("").map((value) => value + value).join("") : hex;
    const red = Number.parseInt(normalized.slice(0, 2), 16);
    const green = Number.parseInt(normalized.slice(2, 4), 16);
    const blue = Number.parseInt(normalized.slice(4, 6), 16);
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function colorToHsl(color) {
    const hex = color.replace("#", "");
    const normalized = hex.length === 3 ? hex.split("").map((value) => value + value).join("") : hex;
    const red = Number.parseInt(normalized.slice(0, 2), 16) / 255;
    const green = Number.parseInt(normalized.slice(2, 4), 16) / 255;
    const blue = Number.parseInt(normalized.slice(4, 6), 16) / 255;
    const max = Math.max(red, green, blue);
    const min = Math.min(red, green, blue);
    const lightness = (max + min) / 2;
    const delta = max - min;
    if (!delta) {
        return { h: 0, s: 0, l: lightness * 100 };
    }
    const saturation = delta / (1 - Math.abs(2 * lightness - 1));
    let hue;
    if (max === red) {
        hue = ((green - blue) / delta) % 6;
    } else if (max === green) {
        hue = (blue - red) / delta + 2;
    } else {
        hue = (red - green) / delta + 4;
    }
    return {
        h: (hue * 60 + 360) % 360,
        s: saturation * 100,
        l: lightness * 100,
    };
}

function interpolateHue(start, end, amount) {
    const delta = ((end - start + 540) % 360) - 180;
    return (start + delta * amount + 360) % 360;
}

const NEON_STOPS = [[188, 96, 56], [268, 88, 58], [328, 92, 58], [38, 96, 56]];
const RAINBOW_STOPS = [[280, 95, 54], [0, 96, 54], [28, 98, 54], [52, 96, 54], [118, 90, 50], [178, 96, 52], [222, 96, 55]];
const WARM_COOL_STOPS = [[24, 98, 56], [340, 88, 60], [300, 20, 94], [188, 92, 60], [214, 96, 54]];
const EQ_HEX = ["#9b22ff", "#e018a8", "#ff1f2a", "#ff6a00", "#ffd000", "#6ee000", "#00e0ff", "#2458ff"];

function mixHsl(t, stops, alpha = 0.92) {
    const n = ((t % 1) + 1) % 1;
    const scaled = n * (stops.length - 1);
    const index = Math.min(stops.length - 2, Math.floor(scaled));
    const f = scaled - index;
    const a = stops[index];
    const b = stops[index + 1];
    return `hsla(${interpolateHue(a[0], b[0], f)}, ${a[1] + (b[1] - a[1]) * f}%, ${a[2] + (b[2] - a[2]) * f}%, ${alpha})`;
}

function hueColor(t, alpha = 0.92) {
    return mixHsl(t, NEON_STOPS, alpha);
}

function rainbowColor(t, alpha = 0.92) {
    return mixHsl(t, RAINBOW_STOPS, alpha);
}

function fullSpectrumColor(t, alpha = 0.92) {
    return rainbowColor(t, alpha);
}

function eqBandColor(t, alpha = 1) {
    const n = ((t % 1) + 1) % 1;
    const index = Math.min(EQ_HEX.length - 1, Math.floor(n * EQ_HEX.length));
    return blendColor(alpha, EQ_HEX[index]);
}

function averageLevel(data) {
    let total = 0;
    for (const value of data) {
        total += value;
    }
    return data.length ? total / data.length : 0;
}

function drawBackground(width, height, energy) {
    if (state.backgroundMode === "video" && backgroundVideo) {
        if (backgroundVideo.paused) {
            backgroundVideo.play().catch(() => {});
        }
        ctx.drawImage(backgroundVideo, 0, 0, width, height);
    } else if (state.backgroundMode === "image" && backgroundImage) {
        ctx.drawImage(backgroundImage, 0, 0, width, height);
    } else {
        const gradient = ctx.createLinearGradient(0, 0, width, height);
        gradient.addColorStop(0, state.sceneA);
        gradient.addColorStop(1, state.sceneB);
        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, width, height);
    }

    if (state.sceneKind !== "key") {
        ctx.fillStyle = `rgba(5, 7, 12, ${state.backgroundDim})`;
        ctx.fillRect(0, 0, width, height);
        const highlight = ctx.createRadialGradient(
            width * 0.72,
            height * 0.18,
            0,
            width * 0.72,
            height * 0.18,
            width * 0.48,
        );
        highlight.addColorStop(0, hueColor(0.72, 0.16 + energy * 0.0005));
        highlight.addColorStop(1, "rgba(0, 0, 0, 0)");
        ctx.fillStyle = highlight;
        ctx.fillRect(0, 0, width, height);
    }
}

function drawCinematicAtmosphere(width, height, energy) {
    const clock = vizClock();
    const beat = energy / 255;
    const span = Math.min(width, height);
    const drift = clock * 0.16;

    ctx.save();
    ctx.globalCompositeOperation = "screen";
    const blooms = [
        {
            x: width * (0.22 + Math.sin(drift) * 0.08),
            y: height * (0.26 + Math.cos(drift * 0.83) * 0.08),
            radius: span * (0.44 + beat * 0.08),
            color: hueColor(0.08, 1),
        },
        {
            x: width * (0.78 + Math.cos(drift * 0.72) * 0.08),
            y: height * (0.66 + Math.sin(drift * 0.91) * 0.06),
            radius: span * (0.5 + beat * 0.1),
            color: hueColor(0.82, 1),
        },
        {
            x: width * (0.5 + Math.sin(drift * 0.55) * 0.05),
            y: height * 0.42,
            radius: span * (0.28 + beat * 0.05),
            color: hueColor(0.5, 1),
            derived: true,
        },
    ];
    for (const bloom of blooms) {
        const glow = ctx.createRadialGradient(bloom.x, bloom.y, 0, bloom.x, bloom.y, bloom.radius);
        const colorAt = (alpha) => bloom.derived ? hueColor(0.5, alpha) : blendColor(alpha, bloom.color);
        glow.addColorStop(0, colorAt(0.075 + beat * 0.045));
        glow.addColorStop(0.52, colorAt(0.022 + beat * 0.016));
        glow.addColorStop(1, "rgba(0, 0, 0, 0)");
        ctx.fillStyle = glow;
        ctx.fillRect(0, 0, width, height);
    }

    const horizonY = height * (state.aspectMode === "portrait" ? 0.62 : 0.72);
    const horizon = ctx.createLinearGradient(0, horizonY - span * 0.08, 0, horizonY + span * 0.12);
    horizon.addColorStop(0, "rgba(0, 0, 0, 0)");
    horizon.addColorStop(0.5, hueColor(0.78, 0.045 + beat * 0.035));
    horizon.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.fillStyle = horizon;
    ctx.fillRect(0, horizonY - span * 0.08, width, span * 0.2);

    ctx.globalCompositeOperation = "source-over";
    const vignette = ctx.createRadialGradient(
        width / 2,
        height * 0.44,
        span * 0.16,
        width / 2,
        height * 0.44,
        Math.max(width, height) * 0.76,
    );
    vignette.addColorStop(0, "rgba(0, 0, 0, 0)");
    vignette.addColorStop(0.72, "rgba(0, 0, 0, 0.08)");
    vignette.addColorStop(1, "rgba(0, 0, 0, 0.42)");
    ctx.fillStyle = vignette;
    ctx.fillRect(0, 0, width, height);
    ctx.restore();
}

function particleColor(alpha, index, hot = false) {
    if (hot) {
        return hueColor(index / Math.max(1, state.particleCount) + 0.12, alpha);
    }
    return hueColor(index / Math.max(1, state.particleCount), alpha);
}

function createFxParticle(style, width, height, scatter, index = 0) {
    const particle = {
        style,
        index,
        x: Math.random() * width,
        y: Math.random() * height,
        vx: 0,
        vy: 0,
        size: 1.4,
        alpha: 0.3,
        life: 1,
        seed: index + 1,
    };

    if (style === "rain") {
        const depth = 0.18 + Math.pow(Math.random(), 0.65) * 0.82;
        particle.streak = true;
        particle.depth = depth;
        particle.x = Math.random() * (width + 80) - 40;
        particle.y = scatter ? Math.random() * height : -Math.random() * 120;
        particle.fall = (20 + Math.random() * 16) * (0.55 + depth);
        particle.length = 38 + depth * 78;
        particle.size = 0.45 + depth * 0.7;
        particle.alpha = 0.18 + depth * 0.38;
    } else if (style === "stars") {
        particle.size = 0.5 + Math.random() * 1.8;
        particle.baseAlpha = 0.28 + Math.random() * 0.62;
        particle.twinkleSpeed = 0.04 + Math.random() * 0.14;
        particle.twinklePhase = Math.random() * Math.PI * 2;
    } else if (style === "embers") {
        particle.x = Math.random() * width;
        particle.y = scatter ? Math.random() * height : height + Math.random() * 40;
        particle.vx = (Math.random() - 0.5) * 0.45;
        // Rise scales with canvas height so 1080p frames are not 3× taller in time.
        const rise = (0.95 + Math.random() * 1.85) * Math.max(0.85, height / 720);
        particle.vy = -rise;
        particle.size = 1.1 + Math.random() * 2.4;
        particle.alpha = 0.55 + Math.random() * 0.35;
        particle.wobble = Math.random() * Math.PI * 2;
    } else if (style === "warp") {
        const angle = Math.random() * Math.PI * 2;
        const radius = 0.03 + Math.pow(Math.random(), 0.65) * 0.5;
        particle.warpX = Math.cos(angle) * radius;
        particle.warpY = Math.sin(angle) * radius;
        particle.z = scatter ? 0.08 + Math.random() * 1.15 : 1.25;
        particle.depthSpeed = 0.006 + Math.random() * 0.008;
        particle.size = 0.6 + Math.random() * 1.4;
        particle.alpha = 0.45 + Math.random() * 0.45;
        const center = vizFocus(width, height);
        particle.prevX = center.x;
        particle.prevY = center.y;
    } else if (style === "notes") {
        particle.x = Math.random() * width;
        particle.y = scatter ? Math.random() * height : height + 20 + Math.random() * 70;
        particle.vx = (Math.random() - 0.5) * 0.55;
        particle.vy = -(0.65 + Math.random() * 1.35) * Math.max(0.85, height / 720);
        particle.size = 7 + Math.random() * 11;
        particle.alpha = 0.42 + Math.random() * 0.42;
        particle.rotation = Math.random() * Math.PI;
        particle.spin = (Math.random() - 0.5) * 0.05;
    } else if (style === "bokeh") {
        particle.size = 10 + Math.random() * 28;
        particle.vx = (Math.random() - 0.5) * 0.22;
        particle.vy = (Math.random() - 0.5) * 0.18;
        particle.alpha = 0.08 + Math.random() * 0.12;
        particle.twinklePhase = Math.random() * Math.PI * 2;
        particle.twinkleSpeed = 0.008 + Math.random() * 0.02;
    } else if (style === "snow") {
        particle.x = Math.random() * width;
        particle.y = scatter ? Math.random() * height : -Math.random() * 40;
        particle.vx = 0;
        particle.vy = 0.55 + Math.random() * 1.1;
        particle.size = 1.2 + Math.random() * 2.6;
        particle.alpha = 0.35 + Math.random() * 0.45;
        particle.wobble = Math.random() * Math.PI * 2;
    } else if (style === "bubbles") {
        particle.x = Math.random() * width;
        particle.y = scatter ? Math.random() * height : height + Math.random() * 40;
        particle.vx = (Math.random() - 0.5) * 0.28;
        particle.vy = -(0.4 + Math.random() * 0.95) * Math.max(0.85, height / 720);
        particle.size = 6 + Math.random() * 16;
        particle.alpha = 0.22 + Math.random() * 0.18;
        particle.wobble = Math.random() * Math.PI * 2;
        particle.spin = 0.02 + Math.random() * 0.03;
    } else {
        const angle = Math.random() * Math.PI * 2;
        const speed = 0.12 + Math.random() * 0.45;
        particle.vx = Math.cos(angle) * speed;
        particle.vy = Math.sin(angle) * speed * 0.45;
        particle.size = 0.7 + Math.random() * 2.4;
        particle.alpha = 0.1 + Math.random() * 0.18;
        particle.twinklePhase = Math.random() * Math.PI * 2;
        particle.twinkleSpeed = 0.0012 + Math.random() * 0.002;
    }
    return particle;
}

function projectWarpParticle(particle, width, height, resetTrail) {
    const center = vizFocus(width, height);
    const scale = Math.max(width, height) * 0.58;
    const x = center.x + (particle.warpX * scale) / Math.max(0.02, particle.z);
    const y = center.y + (particle.warpY * scale) / Math.max(0.02, particle.z);
    if (resetTrail || !Number.isFinite(particle.x)) {
        particle.prevX = x;
        particle.prevY = y;
    } else {
        particle.prevX = particle.x;
        particle.prevY = particle.y;
    }
    particle.x = x;
    particle.y = y;
}

function ensureParticles(width, height) {
    if (
        particleCache.style === state.particleStyle
        && particleCache.count === state.particleCount
        && particleCache.width === width
        && particleCache.height === height
    ) {
        return;
    }
    particleCache = {
        style: state.particleStyle,
        count: state.particleCount,
        width,
        height,
    };
    fxParticles = [];
    shootingStars = [];
    const count = Math.max(0, Math.min(180, Number(state.particleCount) || 0));
    for (let index = 0; index < count; index += 1) {
        fxParticles.push(createFxParticle(state.particleStyle, width, height, true, index));
        if (state.particleStyle === "warp") {
            projectWarpParticle(fxParticles[index], width, height, true);
        }
    }
}

function spawnShootingStar(width, height) {
    const fromLeft = Math.random() < 0.5;
    const startX = fromLeft ? Math.random() * width * 0.75 : width * (0.25 + Math.random() * 0.75);
    const startY = -24 - Math.random() * 50;
    const tilt = (fromLeft ? 1 : -1) * (0.2 + Math.random() * 0.26);
    const speed = 10 + Math.random() * 8;
    shootingStars.push({
        x: startX,
        y: startY,
        vx: Math.sin(tilt) * speed,
        vy: Math.cos(tilt) * speed,
        life: 34 + Math.random() * 16,
        maxLife: 50,
        tail: 22 + Math.random() * 18,
        brightness: 0.78 + Math.random() * 0.22,
    });
}

function setParticleStyle(style) {
    state.particleStyle = PARTICLE_STYLES[style] ? style : "dust";
    particleCache.count = -1;
    document.querySelectorAll("[data-particle]").forEach((button) => {
        button.classList.toggle("active", button.dataset.particle === state.particleStyle);
    });
    if (elements.particleStatus) {
        setStatus(elements.particleStatus, PARTICLE_STYLES[state.particleStyle]);
    }
}

function drawBubble(drawCtx, x, y, size, wobble) {
    const squash = 1 + Math.sin(wobble) * 0.07;
    drawCtx.save();
    drawCtx.translate(x, y);
    drawCtx.scale(squash, 2 - squash);
    const fill = drawCtx.createRadialGradient(-size * 0.28, -size * 0.32, size * 0.08, 0, 0, size);
    fill.addColorStop(0, "rgba(255,255,255,0.22)");
    fill.addColorStop(0.4, "rgba(190,230,255,0.06)");
    fill.addColorStop(0.78, "rgba(140,190,230,0.05)");
    fill.addColorStop(1, "rgba(230,250,255,0.28)");
    drawCtx.fillStyle = fill;
    drawCtx.beginPath();
    drawCtx.arc(0, 0, size, 0, Math.PI * 2);
    drawCtx.fill();
    drawCtx.strokeStyle = "rgba(220,245,255,0.55)";
    drawCtx.lineWidth = Math.max(1, size * 0.055);
    drawCtx.stroke();
    drawCtx.strokeStyle = "rgba(255,170,210,0.2)";
    drawCtx.lineWidth = Math.max(0.8, size * 0.035);
    drawCtx.beginPath();
    drawCtx.arc(0, 0, size * 0.9, 0.15, 1.35);
    drawCtx.stroke();
    drawCtx.fillStyle = "rgba(255,255,255,0.8)";
    drawCtx.beginPath();
    drawCtx.ellipse(-size * 0.3, -size * 0.34, size * 0.16, size * 0.1, -0.5, 0, Math.PI * 2);
    drawCtx.fill();
    drawCtx.restore();
}

let noteSprites = null;

function ensureNoteSprites() {
    if (noteSprites) {
        return noteSprites;
    }
    noteSprites = [];
    for (let index = 0; index < 16; index += 1) {
        const tile = document.createElement("canvas");
        tile.width = 64;
        tile.height = 64;
        const brush = tile.getContext("2d");
        drawMusicNote(brush, 32, 34, 18, 0, rainbowColor(index / 16, 0.92));
        noteSprites.push(tile);
    }
    return noteSprites;
}

function drawCachedNote(x, y, size, rotation, index, alpha) {
    const sprite = ensureNoteSprites()[index % 16];
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(rotation);
    ctx.globalAlpha = Math.max(0.12, Math.min(1, alpha));
    ctx.drawImage(sprite, -size, -size * 1.15, size * 2, size * 2.15);
    ctx.restore();
}

function drawMusicNote(drawCtx, x, y, size, rotation, color) {
    drawCtx.save();
    drawCtx.translate(x, y);
    drawCtx.rotate(rotation);
    drawCtx.fillStyle = color;
    drawCtx.beginPath();
    drawCtx.ellipse(0, size * 0.32, size * 0.42, size * 0.28, -0.45, 0, Math.PI * 2);
    drawCtx.fill();
    drawCtx.fillRect(size * 0.26, -size * 0.92, Math.max(1.4, size * 0.12), size * 1.18);
    drawCtx.restore();
}

function drawParticles(width, height, energy) {
    ensureParticles(width, height);
    if (!fxParticles.length) {
        return;
    }

    const now = performance.now();
    const delta = lastFxTimestamp ? Math.max(0.35, Math.min(2.4, (now - lastFxTimestamp) / (1000 / 60))) : 1;
    lastFxTimestamp = now;
    const energyBoost = 0.7 + (energy / 255) * 1.6;
    const style = state.particleStyle;

    ctx.save();
    ctx.globalCompositeOperation = (style === "rain" || style === "bubbles") ? "source-over" : "lighter";

    for (let index = 0; index < fxParticles.length; index += 1) {
        const particle = fxParticles[index];

        if (style === "rain") {
            if (!particle.streak) {
                Object.assign(particle, createFxParticle("rain", width, height, true, particle.index));
            }
            const wind = Math.sin(now * 0.00028) * 0.11;
            const fall = particle.fall * (0.95 + energyBoost * 0.08);
            const vx = wind * fall;
            const vy = fall;
            particle.x += vx * delta;
            particle.y += vy * delta;
            if (particle.y > height + 60 || particle.x < -50 || particle.x > width + 50) {
                Object.assign(particle, createFxParticle("rain", width, height, false, particle.index));
            }
            const speed = Math.hypot(vx, vy) || 1;
            const tailX = particle.x - (vx / speed) * particle.length;
            const tailY = particle.y - (vy / speed) * particle.length;
            const streak = ctx.createLinearGradient(tailX, tailY, particle.x, particle.y);
            streak.addColorStop(0, "rgba(170, 205, 230, 0)");
            streak.addColorStop(0.65, `rgba(190, 220, 240, ${particle.alpha * 0.45})`);
            streak.addColorStop(1, `rgba(236, 246, 255, ${particle.alpha})`);
            ctx.strokeStyle = streak;
            ctx.lineWidth = particle.size;
            ctx.lineCap = "butt";
            ctx.beginPath();
            ctx.moveTo(tailX, tailY);
            ctx.lineTo(particle.x, particle.y);
            ctx.stroke();
        } else if (style === "stars") {
            particle.twinklePhase += particle.twinkleSpeed * delta * energyBoost;
            const alpha = particle.baseAlpha * (0.25 + 0.75 * (0.5 + 0.5 * Math.sin(particle.twinklePhase)));
            ctx.fillStyle = particleColor(alpha, index);
            ctx.beginPath();
            ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
            ctx.fill();
        } else if (style === "embers") {
            particle.wobble += 0.03 * delta;
            particle.x += (particle.vx + Math.sin(particle.wobble) * 0.35) * delta;
            particle.y += particle.vy * energyBoost * delta;
            if (particle.y < -20 || particle.x < -24 || particle.x > width + 24) {
                Object.assign(particle, createFxParticle("embers", width, height, false, particle.index));
            }
            // Fade by height, not a short timer. Life used to die in the bottom third.
            const climb = 1 - Math.max(0, Math.min(1, particle.y / Math.max(1, height)));
            const fade = climb < 0.72 ? 1 : Math.max(0, 1 - (climb - 0.72) / 0.28);
            const glow = Math.max(0.08, particle.alpha * fade);
            ctx.fillStyle = particleColor(glow, index, true);
            ctx.beginPath();
            ctx.arc(particle.x, particle.y, particle.size * (0.8 + energyBoost * 0.15), 0, Math.PI * 2);
            ctx.fill();
        } else if (style === "warp") {
            particle.z -= particle.depthSpeed * energyBoost * delta;
            projectWarpParticle(particle, width, height, false);
            const outside = particle.x < -80 || particle.x > width + 80 || particle.y < -80 || particle.y > height + 80;
            if (particle.z <= 0.03 || outside) {
                Object.assign(particle, createFxParticle("warp", width, height, false, particle.index));
                projectWarpParticle(particle, width, height, true);
            }
            const near = 1 - Math.max(0.05, Math.min(1, particle.z));
            // One frame of motion is only a few pixels for a distant star, so
            // stretch the segment backwards into a streak that survives video
            // compression and actually reads as speed.
            const trail = 1.8 + near * 3.2;
            const tailX = particle.x - (particle.x - particle.prevX) * trail;
            const tailY = particle.y - (particle.y - particle.prevY) * trail;
            ctx.strokeStyle = particleColor(0.34 + near * 0.64, index);
            ctx.lineWidth = 1.5 + near * 3.8;
            ctx.lineCap = "round";
            ctx.beginPath();
            ctx.moveTo(tailX, tailY);
            ctx.lineTo(particle.x, particle.y);
            ctx.stroke();
            // A soft head on the closest stars sells the tunnel rush.
            if (near > 0.55) {
                ctx.fillStyle = particleColor((near - 0.55) * 1.6, index, true);
                ctx.beginPath();
                ctx.arc(particle.x, particle.y, 1.2 + near * 2.4, 0, Math.PI * 2);
                ctx.fill();
            }
            ctx.lineCap = "butt";
        } else if (style === "notes") {
            particle.rotation += particle.spin * delta;
            particle.x += (particle.vx + Math.sin(now * 0.0018 + particle.seed) * 0.45) * delta;
            particle.y += particle.vy * energyBoost * delta;
            if (particle.y < -50 || particle.x < -40 || particle.x > width + 40) {
                Object.assign(particle, createFxParticle("notes", width, height, false, particle.index));
            }
            drawCachedNote(
                particle.x,
                particle.y,
                particle.size * (0.9 + energyBoost * 0.08),
                particle.rotation,
                index,
                particle.alpha,
            );
        } else if (style === "bokeh") {
            particle.twinklePhase += particle.twinkleSpeed * delta;
            particle.x += particle.vx * delta;
            particle.y += particle.vy * delta;
            if (particle.x < -40) particle.x = width + 40;
            if (particle.x > width + 40) particle.x = -40;
            if (particle.y < -40) particle.y = height + 40;
            if (particle.y > height + 40) particle.y = -40;
            const pulse = 0.7 + 0.3 * (0.5 + 0.5 * Math.sin(particle.twinklePhase)) + (energy / 255) * 0.25;
            ctx.fillStyle = particleColor(particle.alpha * pulse, index);
            ctx.beginPath();
            ctx.arc(particle.x, particle.y, particle.size * pulse, 0, Math.PI * 2);
            ctx.fill();
        } else if (style === "snow") {
            particle.wobble += 0.025 * delta;
            particle.x += Math.sin(particle.wobble) * 0.55 * delta;
            particle.y += particle.vy * (0.85 + energyBoost * 0.12) * delta;
            if (particle.y > height + 12 || particle.x < -12 || particle.x > width + 12) {
                Object.assign(particle, createFxParticle("snow", width, height, false, particle.index));
            }
            ctx.fillStyle = `rgba(236, 246, 255, ${particle.alpha})`;
            ctx.beginPath();
            ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
            ctx.fill();
        } else if (style === "bubbles") {
            particle.wobble += 0.04 * delta;
            particle.x += (particle.vx + Math.sin(particle.wobble) * 0.4) * delta;
            particle.y += particle.vy * energyBoost * delta;
            if (particle.y < -30 || particle.x < -30 || particle.x > width + 30) {
                Object.assign(particle, createFxParticle("bubbles", width, height, false, particle.index));
            }
            drawBubble(ctx, particle.x, particle.y, particle.size, particle.wobble);
        } else {
            particle.x += particle.vx * delta;
            particle.y += particle.vy * delta;
            if (particle.x < -8) particle.x = width + 8;
            if (particle.x > width + 8) particle.x = -8;
            if (particle.y < -8) particle.y = height + 8;
            if (particle.y > height + 8) particle.y = -8;
            const twinkle = 0.22 + ((Math.sin(now * particle.twinkleSpeed + particle.seed) + 1) * 0.5);
            const alpha = particle.alpha + twinkle * 0.16 + (energy / 255) * 0.08;
            ctx.fillStyle = particleColor(alpha, index);
            ctx.beginPath();
            ctx.arc(particle.x, particle.y, particle.size, 0, Math.PI * 2);
            ctx.fill();
        }
    }

    if (style === "stars") {
        if (Math.random() < 0.008 * energyBoost && shootingStars.length < 3) {
            spawnShootingStar(width, height);
        }
        for (let index = shootingStars.length - 1; index >= 0; index -= 1) {
            const star = shootingStars[index];
            star.x += star.vx * delta;
            star.y += star.vy * delta;
            star.life -= delta;
            const fade = Math.max(0, star.life / star.maxLife);
            const tailX = star.x - star.vx * star.tail * 0.42;
            const tailY = star.y - star.vy * star.tail * 0.42;
            const trail = ctx.createLinearGradient(tailX, tailY, star.x, star.y);
            trail.addColorStop(0, "rgba(255,255,255,0)");
            trail.addColorStop(1, `rgba(255,255,255,${fade * star.brightness})`);
            ctx.strokeStyle = trail;
            ctx.lineWidth = 1.2 + fade * 1.4;
            ctx.lineCap = "round";
            ctx.beginPath();
            ctx.moveTo(tailX, tailY);
            ctx.lineTo(star.x, star.y);
            ctx.stroke();
            ctx.fillStyle = `rgba(255,255,255,${fade * star.brightness})`;
            ctx.beginPath();
            ctx.arc(star.x, star.y, 1.4 + fade, 0, Math.PI * 2);
            ctx.fill();
            if (star.life <= 0) {
                shootingStars.splice(index, 1);
            }
        }
    }

    ctx.restore();
}

function drawCover(centerX, centerY, radius) {
    ctx.save();
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius, 0, Math.PI * 2);
    ctx.closePath();
    ctx.clip();
    if (coverImage) {
        ctx.drawImage(coverImage, centerX - radius, centerY - radius, radius * 2, radius * 2);
    } else {
        const gradient = ctx.createLinearGradient(centerX - radius, centerY - radius, centerX + radius, centerY + radius);
        gradient.addColorStop(0, hueColor(0, 1));
        gradient.addColorStop(0.5, hueColor(0.5, 1));
        gradient.addColorStop(1, hueColor(0.99, 1));
        ctx.fillStyle = gradient;
        ctx.fillRect(centerX - radius, centerY - radius, radius * 2, radius * 2);
        ctx.fillStyle = "rgba(255,255,255,0.9)";
        ctx.font = `${Math.max(22, radius * 0.22)}px "Plus Jakarta Sans"`;
        ctx.textAlign = "center";
        ctx.fillText(songTitle.slice(0, 18), centerX, centerY + 10);
    }
    ctx.restore();

    ctx.lineWidth = Math.max(3, radius * 0.04);
    ctx.strokeStyle = hueColor(0.14, 0.84);
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius + 2, 0, Math.PI * 2);
    ctx.stroke();
}

function vizClock() {
    return Number(elements.audio.currentTime) || 0;
}

function sampleBands(spectrum, count) {
    const n = spectrum.length;
    const bands = new Array(count);
    const minBin = 1;
    const maxBin = Math.max(2, n - 1);
    for (let index = 0; index < count; index += 1) {
        const lo = minBin * ((maxBin / minBin) ** (index / count));
        const hi = minBin * ((maxBin / minBin) ** ((index + 1) / count));
        const start = Math.max(minBin, Math.floor(lo));
        const end = Math.min(n, Math.max(start + 1, Math.ceil(hi)));
        let sum = 0;
        for (let bin = start; bin < end; bin += 1) {
            sum += spectrum[bin] * spectrum[bin];
        }
        bands[index] = Math.sqrt(sum / (end - start)) / 255;
    }
    return bands;
}

function vizFloor(height) {
    return height - (state.aspectMode === "portrait" ? 20 : 16);
}

function vizBottomRise(height, landscape = 0.24, portrait = 0.16) {
    return height * (state.aspectMode === "portrait" ? portrait : landscape);
}

function sampleWave(waveform, count) {
    const out = new Array(count);
    const bucket = waveform.length / count;
    for (let index = 0; index < count; index += 1) {
        const start = Math.floor(index * bucket);
        const end = Math.max(start + 1, Math.floor((index + 1) * bucket));
        let sum = 0;
        for (let bin = start; bin < end; bin += 1) {
            sum += waveform[bin];
        }
        out[index] = (sum / (end - start) - 128) / 128;
    }
    return out;
}

function fillRoundBar(x, y, width, height, radius, floorFlush = true) {
    if (width <= 0 || height <= 0) {
        return;
    }
    const corner = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    if (typeof ctx.roundRect === "function") {
        ctx.roundRect(x, y, width, height, floorFlush ? [corner, corner, 0, 0] : corner);
    } else {
        ctx.rect(x, y, width, height);
    }
    ctx.fill();
}

function drawOrbitPreset(centerX, centerY, radius, spectrum) {
    const bands = sampleBands(spectrum, 80);
    const span = Math.min(elements.canvas.width, elements.canvas.height);
    const clock = vizClock();
    const beat = averageLevel(spectrum) / 255;
    const baseRadius = state.centerImage ? radius + 16 : span * 0.07;
    const maxBar = state.centerImage ? 142 : span * 0.42;
    const spin = clock * 0.22;
    const stroke = Math.max(2.4, state.centerImage
        ? (Math.PI * 2 * baseRadius) / bands.length * 0.58
        : span * 0.0042);

    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    const haze = ctx.createRadialGradient(centerX, centerY, baseRadius * 0.7, centerX, centerY, baseRadius + maxBar * 0.75);
    haze.addColorStop(0, hueColor(0.08, 0.12 + beat * 0.08));
    haze.addColorStop(0.5, hueColor(0.72, 0.035 + beat * 0.035));
    haze.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.fillStyle = haze;
    ctx.fillRect(centerX - span * 0.55, centerY - span * 0.55, span * 1.1, span * 1.1);

    ctx.lineWidth = Math.max(1.2, span * 0.0016);
    ctx.setLineDash([span * 0.008, span * 0.012]);
    ctx.strokeStyle = hueColor(0.78, 0.28 + beat * 0.2);
    ctx.beginPath();
    ctx.arc(centerX, centerY, baseRadius + maxBar * (0.52 + beat * 0.08), spin * 0.4, spin * 0.4 + Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.lineCap = "round";
    ctx.lineWidth = stroke;
    ctx.shadowBlur = Math.max(8, span * 0.012);
    for (let index = 0; index < bands.length; index += 1) {
        const angle = (index / bands.length) * Math.PI * 2 + spin;
        const harmonic = 0.82 + Math.sin(index * 0.43 + clock * 0.9) * 0.12;
        const barLength = 12 + bands[index] * maxBar * harmonic + beat * span * 0.018;
        ctx.strokeStyle = hueColor(index / bands.length, 0.95);
        ctx.shadowColor = ctx.strokeStyle;
        ctx.beginPath();
        ctx.moveTo(centerX + Math.cos(angle) * baseRadius, centerY + Math.sin(angle) * baseRadius);
        ctx.lineTo(
            centerX + Math.cos(angle) * (baseRadius + barLength),
            centerY + Math.sin(angle) * (baseRadius + barLength),
        );
        ctx.stroke();
    }

    const waveform = sampleBands(spectrum, 160);
    ctx.shadowBlur = Math.max(5, span * 0.007);
    ctx.lineWidth = Math.max(1.6, span * 0.0022);
    ctx.strokeStyle = hueColor(0.18, 0.72);
    ctx.beginPath();
    for (let index = 0; index <= waveform.length; index += 1) {
        const t = index / waveform.length;
        const angle = t * Math.PI * 2 - Math.PI / 2 + spin * 0.58;
        const waveRadius = baseRadius + maxBar * (0.32 + waveform[index % waveform.length] * 0.2 + beat * 0.03);
        const x = centerX + Math.cos(angle) * waveRadius;
        const y = centerY + Math.sin(angle) * waveRadius;
        if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.stroke();

    ctx.shadowBlur = Math.max(6, span * 0.009);
    for (let node = 0; node < 12; node += 1) {
        const angle = clock * (node % 2 ? -0.14 : 0.1) + node * Math.PI * 2 / 12;
        const nodeRadius = baseRadius + maxBar * (0.48 + Math.sin(clock * 0.8 + node) * 0.035);
        const size = 2.4 + beat * 3.2 + (node % 3 === 0 ? 2 : 0);
        ctx.fillStyle = hueColor(node / 12, 1);
        ctx.shadowColor = ctx.fillStyle;
        ctx.beginPath();
        ctx.arc(centerX + Math.cos(angle) * nodeRadius, centerY + Math.sin(angle) * nodeRadius, size, 0, Math.PI * 2);
        ctx.fill();
    }
    ctx.restore();
}

function drawBarsPreset(width, height, spectrum) {
    const count = 48;
    const bands = sampleBands(spectrum, count);
    const barWidth = width / count;
    const floor = vizFloor(height);
    const maxRise = vizBottomRise(height, 0.28, 0.16);
    const gap = Math.max(3, barWidth * 0.3);
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    const floorGlow = ctx.createLinearGradient(0, floor - maxRise * 0.2, 0, floor + height * 0.08);
    floorGlow.addColorStop(0, hueColor(0.12, 0.02));
    floorGlow.addColorStop(0.5, hueColor(0.72, 0.12));
    floorGlow.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.fillStyle = floorGlow;
    ctx.fillRect(0, floor - maxRise * 0.2, width, height * 0.12);
    for (let index = 0; index < count; index += 1) {
        const barHeight = 14 + bands[index] * maxRise;
        const x = index * barWidth + gap / 2;
        const w = Math.max(4, barWidth - gap);
        const y = floor - barHeight;
        const color = hueColor(index / Math.max(1, count - 1), 1);
        ctx.fillStyle = blendColor(0.22, color);
        fillRoundBar(x - 2, y - 6, w + 4, barHeight + 8, 8);
        const gradient = ctx.createLinearGradient(0, y, 0, floor);
        gradient.addColorStop(0, blendColor(1, color));
        gradient.addColorStop(1, blendColor(0.45, color));
        ctx.fillStyle = gradient;
        fillRoundBar(x, y, w, barHeight, 6);
        ctx.fillStyle = blendColor(0.95, color);
        fillRoundBar(x, y - 3, w, Math.min(5, Math.max(2, w * 0.26)), 3, false);
        ctx.globalAlpha = 0.22;
        const bounce = Math.min(height - floor - 2, Math.max(4, barHeight * 0.22));
        if (bounce > 2) fillRoundBar(x, floor + 2, w, bounce, 4, false);
        ctx.globalAlpha = 1;
    }
    ctx.restore();
}

function drawPulsePreset(centerX, centerY, radius, energy) {
    const clock = vizClock();
    const beat = energy / 255;
    const span = Math.min(elements.canvas.width, elements.canvas.height);
    const grow = state.centerImage ? radius * 1.85 : span * 0.48;
    for (let ring = 0; ring < 5; ring += 1) {
        const t = (clock * 0.55 + ring * 0.18) % 1;
        const fade = 1 - t;
        ctx.beginPath();
        ctx.lineWidth = Math.max(1.4, (14 - t * 11) * (0.55 + beat));
        ctx.strokeStyle = hueColor(ring / 5 + vizClock() * 0.04, fade * (ring % 2 === 0 ? 0.55 : 0.5));
        ctx.arc(centerX, centerY, (state.centerImage ? radius : 4) + t * grow + beat * span * 0.04, 0, Math.PI * 2);
        ctx.stroke();
    }
}

function drawWavePreset(width, height, waveform) {
    const samples = sampleWave(waveform, 144);
    const base = vizFloor(height);
    const amp = vizBottomRise(height, 0.14, 0.1);
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    const area = ctx.createLinearGradient(0, base - amp, 0, height);
    area.addColorStop(0, hueColor(0.12, 0.38));
    area.addColorStop(0.55, hueColor(0.72, 0.14));
    area.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.beginPath();
    ctx.moveTo(0, height);
    ctx.lineTo(0, base);
    for (let index = 0; index < samples.length; index += 1) {
        const x = (index / (samples.length - 1)) * width;
        const y = base + samples[index] * amp;
        ctx.lineTo(x, y);
    }
    ctx.lineTo(width, height);
    ctx.closePath();
    ctx.fillStyle = area;
    ctx.fill();

    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (let trail = 3; trail >= 0; trail -= 1) {
        ctx.beginPath();
        for (let index = 0; index < samples.length; index += 1) {
            const x = (index / (samples.length - 1)) * width;
            const y = base + samples[index] * amp * (1 - trail * 0.08) + trail * amp * 0.035;
            if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = trail === 0
            ? hueColor(0.16, 0.96)
            : hueColor(0.18 + trail * 0.2, 0.12 + (3 - trail) * 0.06);
        ctx.lineWidth = trail === 0 ? 3.5 : 2 + trail * 2.2;
        ctx.shadowBlur = trail === 0 ? 16 : 5;
        ctx.shadowColor = hueColor(0.18 + trail * 0.2, 1);
        ctx.stroke();
    }
    ctx.restore();
}

function drawHaloPreset(centerX, centerY, radius, spectrum) {
    const bands = sampleBands(spectrum, 64);
    const span = Math.min(elements.canvas.width, elements.canvas.height);
    const inner = state.centerImage ? radius + 10 : 0;
    const reach = state.centerImage ? 108 : span * 0.4;
    ctx.beginPath();
    for (let index = 0; index <= bands.length; index += 1) {
        const band = bands[index % bands.length];
        const angle = (index / bands.length) * Math.PI * 2 - Math.PI / 2;
        const outer = inner + 20 + band * reach;
        const x = centerX + Math.cos(angle) * outer;
        const y = centerY + Math.sin(angle) * outer;
        if (index === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    }
    for (let index = bands.length; index >= 0; index -= 1) {
        const angle = (index / bands.length) * Math.PI * 2 - Math.PI / 2;
        ctx.lineTo(centerX + Math.cos(angle) * inner, centerY + Math.sin(angle) * inner);
    }
    ctx.closePath();
    const glow = ctx.createRadialGradient(centerX, centerY, inner, centerX, centerY, inner + (state.centerImage ? 120 : span * 0.42));
    glow.addColorStop(0, hueColor(0.08, 0.22));
    glow.addColorStop(0.5, hueColor(0.5, 0.18));
    glow.addColorStop(1, hueColor(0.92, 0.58));
    ctx.fillStyle = glow;
    ctx.fill();
}

function drawSunburstPreset(centerX, centerY, radius, spectrum) {
    const rays = 120;
    const bands = sampleBands(spectrum, rays);
    const clock = vizClock();
    const inner = state.centerImage ? radius + 10 : 16;
    const maxLen = Math.min(centerX, centerY, elements.canvas.height * 0.42) * 0.88;
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.lineCap = "round";
    for (let index = 0; index < rays; index += 1) {
        const value = bands[index];
        const angle = (index / rays) * Math.PI * 2 - Math.PI / 2 + clock * 0.05;
        const len = inner + 18 + value * maxLen;
        const x0 = centerX + Math.cos(angle) * inner;
        const y0 = centerY + Math.sin(angle) * inner;
        const x1 = centerX + Math.cos(angle) * len;
        const y1 = centerY + Math.sin(angle) * len;
        ctx.strokeStyle = hueColor(index / rays, 0.35 + value * 0.55);
        ctx.shadowColor = ctx.strokeStyle;
        ctx.shadowBlur = 10 + value * 16;
        ctx.lineWidth = 1.1 + value * 2.8;
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        ctx.lineTo(x1, y1);
        ctx.stroke();
        ctx.fillStyle = "rgba(255,255,255,0.55)";
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.arc(x1, y1, 1.2 + value * 2.4, 0, Math.PI * 2);
        ctx.fill();
    }
    ctx.restore();
}

function drawGridPreset(width, height, spectrum) {
    const portrait = state.aspectMode === "portrait";
    const cols = 24;
    const rows = portrait ? 9 : 8;
    const gap = 5;
    const bandH = vizBottomRise(height, 0.28, 0.2);
    const originY = vizFloor(height) - bandH;
    const cellW = (width - gap * (cols + 1)) / cols;
    const cellH = (bandH - gap * (rows + 1)) / rows;
    const bands = sampleBands(spectrum, cols);
    for (let col = 0; col < cols; col += 1) {
        const litRows = Math.round(bands[col] * rows);
        for (let row = 0; row < rows; row += 1) {
            const lit = (rows - 1 - row) < litRows;
            const x = gap + col * (cellW + gap);
            const y = originY + row * (cellH + gap);
            ctx.fillStyle = lit
                ? hueColor(col / Math.max(1, cols - 1), 0.82)
                : "rgba(255,255,255,0.05)";
            fillRoundBar(x, y, cellW, cellH, 3, false);
        }
    }
}

function drawTunnelPreset(centerX, centerY, radius, energy, spectrum) {
    const beat = energy / 255;
    const clock = vizClock();
    const bands = sampleBands(spectrum, 10);
    const unit = state.centerImage ? radius : Math.min(elements.canvas.width, elements.canvas.height) * 0.22;
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.translate(centerX, centerY);
    ctx.rotate(clock * 0.12);
    for (let ring = 0; ring < 10; ring += 1) {
        const t = (clock * 0.32 + ring * 0.1) % 1;
        const size = unit * (0.3 + t * 2.55 + beat * 0.14);
        const depth = 1 - t;
        const skew = Math.sin(clock * 0.7 + ring * 0.55) * size * 0.08;
        ctx.beginPath();
        ctx.lineWidth = 1.8 + bands[ring] * 9 + depth * 2;
        ctx.strokeStyle = hueColor(ring / 10 + clock * 0.02, Math.max(0.1, 0.34 - t * 0.2));
        ctx.shadowBlur = 8 + depth * 18;
        ctx.shadowColor = ctx.strokeStyle;
        if (typeof ctx.roundRect === "function") {
            ctx.roundRect(-size + skew, -size * 0.56, size * 2, size * 1.12, Math.max(12, size * 0.08));
        } else {
            ctx.rect(-size + skew, -size * 0.56, size * 2, size * 1.12);
        }
        ctx.stroke();
    }

    ctx.shadowBlur = 0;
    ctx.lineWidth = Math.max(1.2, unit * 0.018);
    ctx.strokeStyle = hueColor(0.18, 0.5 + beat * 0.25);
    ctx.beginPath();
    ctx.moveTo(-unit * 1.9, 0);
    ctx.lineTo(unit * 1.9, 0);
    ctx.moveTo(0, -unit * 1.05);
    ctx.lineTo(0, unit * 1.05);
    ctx.stroke();
    ctx.restore();
}

function drawSplitPreset(width, height, spectrum) {
    const bands = sampleBands(spectrum, 28);
    const midY = height * (state.aspectMode === "portrait" ? 0.4 : 0.46);
    const gap = width * (state.aspectMode === "portrait" ? 0.5 : 0.4);
    const side = (width - gap) / 2 - 20;
    const maxH = height * (state.aspectMode === "portrait" ? 0.16 : 0.2);
    const barW = side / bands.length;
    const drawWing = (originX, direction) => {
        for (let index = 0; index < bands.length; index += 1) {
            const h = 8 + bands[index] * maxH;
            const x = direction < 0
                ? originX + side - (index + 1) * barW
                : originX + index * barW;
            const w = Math.max(3, barW * 0.62);
            const color = hueColor(index / Math.max(1, bands.length - 1), 1);
            ctx.fillStyle = color;
            fillRoundBar(x, midY - h, w, h, 4);
            ctx.globalAlpha = 0.55;
            fillRoundBar(x, midY + 4, w, h, 4, false);
            ctx.globalAlpha = 1;
        }
    };
    drawWing(16, 1);
    drawWing(width - 16 - side, -1);
}

function lyricsAreCentered() {
    return state.preset === "split" || state.preset === "peak";
}

function drawScopePreset(width, height, waveform) {
    const samples = sampleWave(waveform, 220);
    const portrait = state.aspectMode === "portrait";
    const mid = height * (portrait ? 0.38 : 0.4);
    const amp = height * (portrait ? 0.12 : 0.16);
    ctx.beginPath();
    ctx.moveTo(0, mid);
    for (let index = 0; index < samples.length; index += 1) {
        const x = (index / (samples.length - 1)) * width;
        ctx.lineTo(x, mid - Math.abs(samples[index]) * amp);
    }
    for (let index = samples.length - 1; index >= 0; index -= 1) {
        const x = (index / (samples.length - 1)) * width;
        ctx.lineTo(x, mid + Math.abs(samples[index]) * amp);
    }
    ctx.closePath();
    ctx.fillStyle = hueColor(0.72, 0.82);
    ctx.fill();
    ctx.strokeStyle = blendColor(0.95, "#f4f7fb");
    ctx.lineWidth = 2;
    ctx.stroke();
}

function drawMeshPreset(width, height, spectrum) {
    const cols = 26;
    const rows = 14;
    const bands = sampleBands(spectrum, cols);
    const clock = vizClock();
    const vanishX = width / 2;
    const vanishY = height * 0.2;
    const points = [];
    for (let row = 0; row < rows; row += 1) {
        const depth = 0.22 + (row / (rows - 1)) * 0.72;
        const line = [];
        for (let col = 0; col < cols; col += 1) {
            const t = col / (cols - 1) - 0.5;
            const x = vanishX + t * width * 0.98 * depth;
            const floor = vanishY + height * 0.38 * depth;
            const lift = (bands[col] * height * 0.14 + Math.sin(col * 0.55 + row * 0.4 + clock * 1.4) * 10) * (0.35 + depth);
            line.push({ x, y: floor - lift });
        }
        points.push(line);
    }
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.lineWidth = 1.35;
    for (let row = 0; row < rows; row += 1) {
        ctx.beginPath();
        ctx.strokeStyle = hueColor(row / rows, 0.28 + row / rows * 0.45);
        points[row].forEach((point, index) => {
            if (index === 0) ctx.moveTo(point.x, point.y);
            else ctx.lineTo(point.x, point.y);
        });
        ctx.stroke();
    }
    for (let col = 0; col < cols; col += 1) {
        ctx.beginPath();
        ctx.strokeStyle = hueColor(col / cols, 0.22);
        for (let row = 0; row < rows; row += 1) {
            const point = points[row][col];
            if (row === 0) ctx.moveTo(point.x, point.y);
            else ctx.lineTo(point.x, point.y);
        }
        ctx.stroke();
    }
    ctx.restore();
}

function drawPeakPreset(width, height, spectrum) {
    const bands = sampleBands(spectrum, 64);
    const floor = height;
    const maxH = vizBottomRise(height, 0.24, 0.18);
    const rainbow = ctx.createLinearGradient(0, 0, width, 0);
    rainbow.addColorStop(0, rainbowColor(0, 0.92));
    rainbow.addColorStop(0.25, rainbowColor(0.25, 0.92));
    rainbow.addColorStop(0.5, rainbowColor(0.5, 0.92));
    rainbow.addColorStop(0.75, rainbowColor(0.75, 0.92));
    rainbow.addColorStop(1, rainbowColor(0.99, 0.92));
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(0, floor);
    for (let index = 0; index < bands.length; index += 1) {
        const x = (index / (bands.length - 1)) * width;
        ctx.lineTo(x, floor - 4 - bands[index] * maxH);
    }
    ctx.lineTo(width, floor);
    ctx.closePath();
    ctx.fillStyle = rainbow;
    ctx.globalAlpha = 0.9;
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.shadowColor = "rgba(255,255,255,0.7)";
    ctx.shadowBlur = 14;
    ctx.strokeStyle = "rgba(255,255,255,0.85)";
    ctx.lineWidth = Math.max(1.8, height * 0.0022);
    ctx.beginPath();
    for (let index = 0; index < bands.length; index += 1) {
        const x = (index / (bands.length - 1)) * width;
        const y = floor - 4 - bands[index] * maxH;
        if (index === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.restore();
}

function drawAnalogPreset(width, height, waveform) {
    const cols = 96;
    const samples = sampleWave(waveform, cols);
    const mid = height * 0.5;
    const amp = height * 0.28;
    const colW = width / cols;
    ctx.save();
    for (let index = 0; index < cols; index += 1) {
        const h = Math.max(colW * 0.6, Math.abs(samples[index]) * amp);
        const x = index * colW;
        const gradient = ctx.createLinearGradient(x, mid - h, x, mid + h);
        gradient.addColorStop(0, rainbowColor(index / cols, 0.15));
        gradient.addColorStop(0.5, rainbowColor(index / cols, 1));
        gradient.addColorStop(1, rainbowColor(index / cols, 0.15));
        ctx.fillStyle = gradient;
        ctx.fillRect(x + colW * 0.12, mid - h, colW * 0.76, h * 2);
    }
    ctx.restore();
}

function drawEqPreset(width, height, spectrum) {
    const cols = 32;
    const rows = 16;
    const bands = sampleBands(spectrum, cols);
    const gap = Math.max(3, width * 0.005);
    const barW = (width - gap * (cols + 1)) / cols;
    const floor = vizFloor(height);
    const stackH = vizBottomRise(height, 0.32, 0.22);
    const barH = Math.max(6, (stackH - gap * (rows + 1)) / rows);
    ctx.save();
    for (let col = 0; col < cols; col += 1) {
        const lit = Math.max(1, Math.round(bands[col] * rows));
        const x = gap + col * (barW + gap);
        const color = eqBandColor(col / cols, 1);
        for (let row = 0; row < rows; row += 1) {
            const y = floor - (row + 1) * (barH + gap);
            ctx.fillStyle = row < lit ? color : "rgba(12, 12, 18, 0.55)";
            ctx.fillRect(x, y, barW, barH);
        }
    }
    ctx.restore();
}

function drawCascadePreset(width, height, spectrum) {
    const count = 56;
    const bands = sampleBands(spectrum, count);
    const mid = height * 0.5;
    const maxH = height * 0.38;
    const barW = width / count;
    ctx.save();
    ctx.shadowBlur = 18;
    for (let index = 0; index < count; index += 1) {
        const h = 10 + bands[index] * maxH;
        const x = index * barW + barW * 0.18;
        const w = barW * 0.64;
        const color = mixHsl(index / (count - 1), WARM_COOL_STOPS, 1);
        ctx.shadowColor = color;
        const gradient = ctx.createLinearGradient(x, mid - h, x, mid);
        gradient.addColorStop(0, "rgba(255,255,255,0.95)");
        gradient.addColorStop(0.18, color);
        gradient.addColorStop(1, mixHsl(index / (count - 1), WARM_COOL_STOPS, 0.55));
        ctx.fillStyle = gradient;
        fillRoundBar(x, mid - h, w, h, Math.min(8, w * 0.45), true);
        ctx.globalAlpha = 0.28;
        ctx.shadowBlur = 0;
        fillRoundBar(x, mid + 3, w, h * 0.9, Math.min(8, w * 0.45), false);
        ctx.globalAlpha = 1;
        ctx.shadowBlur = 18;
    }
    ctx.restore();
}

function drawStereoPreset(width, height, waveform) {
    const cols = 140;
    const samples = sampleWave(waveform, cols);
    const mid = height * 0.5;
    const amp = height * 0.32;
    const colW = width / cols;
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    for (let index = 0; index < cols; index += 1) {
        const h = 6 + Math.abs(samples[index]) * amp;
        const x = index * colW;
        const color = rainbowColor(index / cols, 1);
        ctx.fillStyle = color;
        ctx.shadowColor = color;
        ctx.shadowBlur = 10;
        ctx.fillRect(x + colW * 0.2, mid - h, colW * 0.6, h * 2);
    }
    ctx.restore();
}

function drawSilkPreset(width, height, waveform) {
    const energy = sampleWave(waveform, 32).reduce((sum, value) => sum + Math.abs(value), 0) / 32;
    const mid = height * 0.42;
    const clock = vizClock();
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    for (let layer = 0; layer < 14; layer += 1) {
        const amp = height * (0.07 + energy * 0.18 + layer * 0.004);
        ctx.beginPath();
        for (let x = 0; x <= width; x += 4) {
            const t = x / width;
            const y = mid + Math.sin(t * Math.PI * 4 + clock * 1.4 + layer * 0.38) * amp
                + Math.sin(t * Math.PI * 9 + layer) * amp * 0.18;
            if (x === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = rainbowColor(layer / 13, 0.55);
        ctx.lineWidth = 1.7;
        ctx.stroke();
    }
    ctx.save();
    ctx.globalAlpha = 0.35;
    ctx.translate(0, height * 0.52);
    ctx.scale(1, -0.42);
    ctx.translate(0, -mid);
    for (let layer = 0; layer < 8; layer += 1) {
        const amp = height * (0.07 + energy * 0.16);
        ctx.beginPath();
        for (let x = 0; x <= width; x += 5) {
            const t = x / width;
            const y = mid + Math.sin(t * Math.PI * 4 + clock * 1.4 + layer * 0.38) * amp;
            if (x === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = rainbowColor(layer / 7, 0.8);
        ctx.stroke();
    }
    ctx.restore();
    ctx.restore();
}

function drawDotsPreset(width, height, waveform) {
    const cols = 72;
    const samples = sampleWave(waveform, cols);
    const mid = height * 0.5;
    const amp = height * 0.26;
    ctx.save();
    ctx.globalCompositeOperation = "lighter";
    for (let col = 0; col < cols; col += 1) {
        const x = ((col + 0.5) / cols) * width;
        const h = Math.abs(samples[col]) * amp;
        const dots = Math.max(3, Math.round(6 + h / 14));
        for (let row = -dots; row <= dots; row += 1) {
            const y = mid + row * 10;
            const fall = 1 - Math.abs(row) / (dots + 0.01);
            ctx.fillStyle = rainbowColor(col / cols, 0.25 + fall * 0.7);
            ctx.beginPath();
            ctx.arc(x, y, 2.4 + fall * 1.6, 0, Math.PI * 2);
            ctx.fill();
        }
    }
    ctx.restore();
}

function drawArcPreset(centerX, centerY, radius, spectrum) {
    const bands = sampleBands(spectrum, 40);
    const canvasSpan = Math.min(elements.canvas.width, elements.canvas.height);
    const inner = state.centerImage ? radius + 16 : 0;
    const start = Math.PI * 0.12;
    const end = Math.PI * 0.88;
    const span = end - start;
    const rise = state.centerImage ? 150 : canvasSpan * 0.42;
    for (let index = 0; index < bands.length; index += 1) {
        const a0 = start + (index / bands.length) * span;
        const a1 = start + ((index + 1) / bands.length) * span;
        const outer = inner + 18 + bands[index] * rise;
        ctx.beginPath();
        ctx.moveTo(centerX + Math.cos(a0) * inner, centerY + Math.sin(a0) * inner);
        ctx.lineTo(centerX + Math.cos(a0) * outer, centerY + Math.sin(a0) * outer);
        ctx.lineTo(centerX + Math.cos(a1) * outer, centerY + Math.sin(a1) * outer);
        ctx.lineTo(centerX + Math.cos(a1) * inner, centerY + Math.sin(a1) * inner);
        ctx.closePath();
        ctx.fillStyle = hueColor(index / bands.length, 0.9);
        ctx.fill();
    }
}

function wrapTextLines(text, maxWidth, maxLines) {
    const normalized = String(text || "").replace(/\s+/g, " ").trim();
    if (!normalized) {
        return [];
    }
    const tokens = normalized.includes(" ") ? normalized.split(" ") : normalized.split("");
    const lines = [];
    let currentLine = "";
    let truncated = false;

    for (const token of tokens) {
        const separator = currentLine && normalized.includes(" ") ? " " : "";
        const candidate = `${currentLine}${separator}${token}`;
        if (!currentLine || ctx.measureText(candidate).width <= maxWidth) {
            currentLine = candidate;
            continue;
        }
        lines.push(currentLine);
        currentLine = token;
        if (lines.length === maxLines) {
            truncated = true;
            break;
        }
    }
    if (currentLine && lines.length < maxLines) {
        lines.push(currentLine);
    }

    if (truncated && lines.length === maxLines) {
        const lastLine = lines[maxLines - 1];
        let trimmed = lastLine;
        while (trimmed && ctx.measureText(`${trimmed}\u2026`).width > maxWidth) {
            trimmed = trimmed.slice(0, -1).trimEnd();
        }
        lines[maxLines - 1] = trimmed ? `${trimmed}\u2026` : "\u2026";
    }
    return lines;
}

function infoPanelContent() {
    const metaParts = [
        workspaceTitle,
        durationLabel,
        bpmValue ? `${bpmValue} BPM` : "",
        keyScale,
        vocalLanguage ? String(vocalLanguage).toUpperCase() : "",
    ].filter(Boolean);
    const summary = songSummary || styleText || "YuE2 Studio local visualizer";
    return {
        meta: metaParts.join(" • "),
        summary,
    };
}

function drawInfoPanel(width, height) {
    const portrait = state.aspectMode === "portrait";
    const margin = portrait ? 34 : 38;
    const panelWidth = Math.min(width - (margin * 2), portrait ? width * 0.82 : width * 0.46);
    const panelX = margin;
    const panelY = margin;
    const titleSize = portrait ? Math.max(30, width * 0.052) : Math.max(28, width * 0.03);
    const metaSize = portrait ? Math.max(15, width * 0.019) : Math.max(13, width * 0.0115);
    const summarySize = portrait ? Math.max(18, width * 0.026) : Math.max(16, width * 0.014);
    const sectionSize = Math.max(11, width * 0.009);
    const { meta, summary } = infoPanelContent();

    ctx.save();
    ctx.textAlign = "left";

    ctx.font = `800 ${titleSize}px "Plus Jakarta Sans"`;
    const titleLines = wrapTextLines(songTitle, panelWidth - 34, portrait ? 3 : 2);
    ctx.font = `500 ${metaSize}px "IBM Plex Mono"`;
    const metaLines = wrapTextLines(meta, panelWidth - 34, portrait ? 3 : 2);
    ctx.font = `600 ${summarySize}px "Plus Jakarta Sans"`;
    const summaryLines = wrapTextLines(summary, panelWidth - 34, portrait ? 5 : 4);

    const titleHeight = titleLines.length * titleSize * 1.14;
    const metaHeight = metaLines.length ? (16 + (metaLines.length * metaSize * 1.26)) : 0;
    const summaryHeight = summaryLines.length ? (16 + (summaryLines.length * summarySize * 1.36)) : 0;
    const panelHeight = 28 + titleHeight + metaHeight + summaryHeight + 16;

    ctx.fillStyle = "rgba(4, 6, 12, 0.58)";
    ctx.strokeStyle = "rgba(255,255,255,0.12)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.roundRect(panelX, panelY, panelWidth, panelHeight, 22);
    ctx.fill();
    ctx.stroke();

    let cursorY = panelY + 30;
    ctx.fillStyle = "rgba(255,255,255,0.97)";
    ctx.font = `800 ${titleSize}px "Plus Jakarta Sans"`;
    titleLines.forEach((line) => {
        ctx.fillText(line, panelX + 18, cursorY);
        cursorY += titleSize * 1.14;
    });

    if (metaLines.length) {
        cursorY += 8;
        ctx.fillStyle = "rgba(255,255,255,0.68)";
        ctx.font = `500 ${metaSize}px "IBM Plex Mono"`;
        metaLines.forEach((line) => {
            ctx.fillText(line, panelX + 18, cursorY);
            cursorY += metaSize * 1.26;
        });
    }

    if (summaryLines.length) {
        cursorY += 12;
        ctx.fillStyle = hueColor(0.82, 0.9);
        ctx.font = `800 ${sectionSize}px "IBM Plex Mono"`;
        ctx.fillText("STYLE / SUMMARY", panelX + 18, cursorY);
        cursorY += 16;
        ctx.fillStyle = "rgba(255,255,255,0.82)";
        ctx.font = `600 ${summarySize}px "Plus Jakarta Sans"`;
        summaryLines.forEach((line) => {
            ctx.fillText(line, panelX + 18, cursorY);
            cursorY += summarySize * 1.36;
        });
    }
    ctx.restore();
}

function lineStartTime(line) {
    const words = Array.isArray(line?.words) ? line.words : [];
    const firstWordStart = Number(words[0]?.start);
    if (Number.isFinite(firstWordStart) && firstWordStart >= 0) {
        return firstWordStart;
    }
    return Number(line?.start || 0);
}

function lineEndTime(line) {
    const words = Array.isArray(line?.words) ? line.words : [];
    const lastWordEnd = Number(words[words.length - 1]?.end);
    if (Number.isFinite(lastWordEnd) && lastWordEnd > 0) {
        return lastWordEnd;
    }
    return Number(line?.end || 0);
}

function activeLyricLines(currentTime) {
    if (!state.lyricLines.length) {
        return { current: null, next: null };
    }

    const leadInSeconds = 0.18;
    const lingerSeconds = 0.12;
    const upcomingWindowSeconds = 2.5;
    let current = null;
    let bestDistance = Infinity;
    for (const line of state.lyricLines) {
        const start = lineStartTime(line);
        const end = lineEndTime(line);
        if (currentTime >= (start - leadInSeconds) && currentTime <= (end + lingerSeconds)) {
            const mid = (start + end) / 2;
            const distance = Math.abs(currentTime - mid);
            if (!current || distance < bestDistance || (distance === bestDistance && start > lineStartTime(current))) {
                current = line;
                bestDistance = distance;
            }
        }
    }

    if (current) {
        const currentIndex = state.lyricLines.findIndex((line) => line.index === current.index);
        const nextLine = currentIndex >= 0 ? state.lyricLines[currentIndex + 1] || null : null;
        return { current, next: nextLine };
    }

    const next = state.lyricLines.find((line) => lineStartTime(line) > currentTime) || null;
    if (!next) {
        return { current: null, next: null };
    }
    if ((lineStartTime(next) - currentTime) <= upcomingWindowSeconds) {
        return { current: null, next };
    }
    return { current: null, next: null };
}

function lyricWordItems(line) {
    const words = Array.isArray(line?.words) ? line.words : [];
    if (words.length) {
        return words.map((word, index) => ({
            text: String(word.text || "").trim(),
            start: Number(word.start || line.start || 0),
            end: Number(word.end || line.end || 0),
            index,
        })).filter((word) => word.text);
    }
    const separator = noSpaceLanguages.has(state.lyricsLanguage) ? "" : " ";
    return String(line?.text || "")
        .split(separator ? /\s+/ : "")
        .map((text, index, items) => {
            const start = Number(line?.start || 0);
            const end = Number(line?.end || start);
            const segment = (end - start) / Math.max(1, items.length);
            return {
                text: String(text || "").trim(),
                start: start + (segment * index),
                end: index === items.length - 1 ? end : start + (segment * (index + 1)),
                index,
            };
        })
        .filter((word) => word.text);
}

function lyricWordGap(fontSize) {
    if (noSpaceLanguages.has(state.lyricsLanguage)) {
        return Math.max(1, fontSize * 0.04);
    }
    return Math.max(8, fontSize * 0.38);
}

function layoutLyricRows(words, maxWidth, wordGap) {
    const rows = [];
    let current = [];
    let currentWidth = 0;
    words.forEach((word) => {
        const displayText = String(word.text || "");
        const width = ctx.measureText(displayText).width;
        const extra = current.length ? wordGap : 0;
        if (current.length && currentWidth + extra + width > maxWidth) {
            rows.push({ items: current, width: currentWidth });
            current = [{ ...word, displayText, width }];
            currentWidth = width;
            return;
        }
        current.push({ ...word, displayText, width });
        currentWidth += extra + width;
    });
    if (current.length) {
        rows.push({ items: current, width: currentWidth });
    }
    return rows;
}

function lyricWordColor(word, currentTime) {
    if (currentTime >= word.end) {
        return "rgba(255,255,255,0.96)";
    }
    if (currentTime >= word.start) {
        return hueColor(0.88, 0.98);
    }
    return "rgba(255,255,255,0.42)";
}

function translationFontSize(fontSize) {
    return Math.max(15, Math.round(fontSize * 0.56));
}

function lyricBlockHeight(line, maxWidth, fontSize) {
    ctx.font = `800 ${fontSize}px "Plus Jakarta Sans"`;
    const sungRows = Math.max(1, layoutLyricRows(lyricWordItems(line), maxWidth, lyricWordGap(fontSize)).length);
    let height = sungRows * fontSize * 1.32;
    if (state.dualLyrics && line.translation) {
        const transSize = translationFontSize(fontSize);
        ctx.font = `600 ${transSize}px "Plus Jakarta Sans"`;
        const rows = wrapTextLines(line.translation, maxWidth, 2);
        height += transSize * 0.45 + rows.length * transSize * 1.28;
    }
    return height;
}

function drawKaraokeLine(line, currentTime, centerX, y, maxWidth, fontSize, inactive = false) {
    const words = lyricWordItems(line);
    const wordGap = lyricWordGap(fontSize);
    ctx.font = `800 ${fontSize}px "Plus Jakarta Sans"`;
    // Words are placed from the left of each row. Center alignment here used
    // to stack short words on top of each other ("thewater", "Neonundertow").
    ctx.textAlign = "left";
    ctx.textBaseline = "alphabetic";
    const rows = layoutLyricRows(words, maxWidth, wordGap);
    const lineHeight = fontSize * 1.32;
    rows.forEach((row, rowIndex) => {
        let cursorX = centerX - (row.width / 2);
        const rowY = y + (rowIndex * lineHeight);
        row.items.forEach((word, wordIndex) => {
            ctx.fillStyle = inactive ? "rgba(255,255,255,0.54)" : lyricWordColor(word, currentTime);
            ctx.fillText(word.displayText, cursorX, rowY);
            cursorX += word.width + (wordIndex < row.items.length - 1 ? wordGap : 0);
        });
    });
    let height = Math.max(1, rows.length) * lineHeight;
    if (state.dualLyrics && line.translation) {
        const transSize = translationFontSize(fontSize);
        ctx.font = `600 ${transSize}px "Plus Jakarta Sans"`;
        ctx.textAlign = "center";
        const translated = wrapTextLines(line.translation, maxWidth, 2);
        const startY = y + height + transSize * 0.2;
        translated.forEach((row, rowIndex) => {
            ctx.fillStyle = inactive ? "rgba(185,174,210,0.42)" : "rgba(185,174,210,0.92)";
            ctx.fillText(row, centerX, startY + rowIndex * transSize * 1.28);
        });
        height += transSize * 0.45 + translated.length * transSize * 1.28;
        ctx.textAlign = "left";
    }
    return height;
}

function easeSmooth(progress) {
    const clamped = Math.max(0, Math.min(1, progress));
    return clamped * clamped * (3 - 2 * clamped);
}

function lastStartedLyricIndex(currentTime) {
    const leadInSeconds = 0.12;
    let started = -1;
    for (let index = 0; index < state.lyricLines.length; index += 1) {
        if (currentTime >= (lineStartTime(state.lyricLines[index]) - leadInSeconds)) {
            started = index;
            continue;
        }
        break;
    }
    return started;
}

function lyricScrollFocusIndex(currentTime, currentIndex) {
    const startedIndex = Math.max(0, currentIndex);
    const nextIndex = startedIndex + 1;
    if (nextIndex >= state.lyricLines.length) {
        return startedIndex;
    }
    // Look ahead to the next line instead of waiting for it to become
    // current. The old path set currentIndex to -1 in the gap, snapped
    // focus back to 0, and the sung line vanished until it popped in.
    const nextStart = lineStartTime(state.lyricLines[nextIndex]);
    const currentEnd = lineEndTime(state.lyricLines[startedIndex]);
    const gap = nextStart - currentEnd;
    const scrollStart = gap <= 1.6 ? currentEnd : nextStart - 0.4;
    const scrollEnd = gap <= 1.6
        ? Math.max(nextStart, currentEnd + 0.4) + 0.12
        : nextStart + 0.28;
    if (currentTime < scrollStart) {
        return startedIndex;
    }
    const progress = easeSmooth((currentTime - scrollStart) / Math.max(0.3, scrollEnd - scrollStart));
    return startedIndex + progress;
}

function drawScrollingLyrics(width, height, currentTime) {
    if (!state.lyricsEnabled || !state.lyricLines.length) {
        return;
    }

    const portrait = state.aspectMode === "portrait";
    const startedIndex = lastStartedLyricIndex(currentTime);
    const { current } = activeLyricLines(currentTime);
    const highlightIndex = current
        ? state.lyricLines.findIndex((line) => line.index === current.index)
        : startedIndex;
    const focusIndex = lyricScrollFocusIndex(currentTime, startedIndex);
    const centered = lyricsAreCentered();
    const fontSize = Math.max(portrait ? 25 : 23, Math.min(width, height) * (portrait ? 0.035 : 0.02));
    const lyricsWidth = width * (centered ? (portrait ? 0.62 : 0.36) : (portrait ? 0.86 : 0.74));
    const scrollTop = height * (centered ? (portrait ? 0.28 : 0.34) : (portrait ? 0.48 : 0.58));
    const scrollBottom = height * (centered ? (portrait ? 0.58 : 0.62) : 1) - (portrait ? 52 : 40);
    const anchorY = height * (centered ? (portrait ? 0.42 : 0.48) : (portrait ? 0.72 : 0.77));
    const firstIndex = Math.max(0, Math.floor(focusIndex) - 1);
    const lastIndex = Math.min(state.lyricLines.length - 1, Math.ceil(focusIndex) + 1);
    ctx.font = `800 ${fontSize}px "Plus Jakarta Sans"`;
    let tallestBlock = fontSize * 1.32;
    for (let index = firstIndex; index <= lastIndex; index += 1) {
        tallestBlock = Math.max(tallestBlock, lyricBlockHeight(state.lyricLines[index], lyricsWidth, fontSize));
    }
    // Keep prev/current/next from colliding when a line wraps to two rows.
    const lineStep = tallestBlock + Math.max(fontSize * 1.15, portrait ? 28 : 24);

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, scrollTop, width, scrollBottom - scrollTop);
    ctx.clip();
    ctx.textAlign = "left";
    ctx.shadowColor = "rgba(0, 0, 0, 0.86)";
    ctx.shadowBlur = 12;
    ctx.shadowOffsetY = 2;

    for (let index = firstIndex; index <= lastIndex; index += 1) {
        const y = anchorY + ((index - focusIndex) * lineStep);
        if (y < scrollTop - lineStep || y > scrollBottom + lineStep) {
            continue;
        }
        const isCurrent = index === highlightIndex && highlightIndex >= 0;
        ctx.globalAlpha = isCurrent ? 1 : (index < Math.max(0, startedIndex) ? 0.34 : 0.48);
        drawKaraokeLine(
            state.lyricLines[index],
            currentTime,
            width / 2,
            y,
            lyricsWidth,
            fontSize,
            !isCurrent,
        );
    }
    ctx.restore();
}

let lastDrawStamp = 0;

function renderVisualizer(stamp) {
    renderFrame = window.requestAnimationFrame(renderVisualizer);
    if (state.audioSrcBackup) {
        return;
    }
    const now = stamp || performance.now();
    const minDelta = state.isRendering ? 32 : 14;
    if (now - lastDrawStamp < minDelta) {
        return;
    }
    lastDrawStamp = now;
    const width = elements.canvas.width;
    const height = elements.canvas.height;

    if (analyser) {
        analyser.getByteFrequencyData(frequencyData);
        analyser.getByteTimeDomainData(waveformData);
    } else {
        frequencyData.fill(0);
        waveformData.fill(128);
    }

    const energy = averageLevel(frequencyData);
    ctx.clearRect(0, 0, width, height);
    drawBackground(width, height, energy);
    drawParticles(width, height, energy);
    if (state.backgroundMode === "random") {
        drawCinematicAtmosphere(width, height, energy);
    }

    const cover = visualCenter(width, height);
    const { x: centerX, y: centerY, radius } = vizFocus(width, height);

    if (state.preset === "orbit") {
        drawOrbitPreset(centerX, centerY, radius, frequencyData);
    } else if (state.preset === "bars") {
        drawBarsPreset(width, height, frequencyData);
    } else if (state.preset === "pulse") {
        drawPulsePreset(centerX, centerY, radius, energy);
    } else if (state.preset === "wave") {
        drawWavePreset(width, height, waveformData);
    } else if (state.preset === "halo") {
        drawHaloPreset(centerX, centerY, radius, frequencyData);
    } else if (state.preset === "sunburst") {
        drawSunburstPreset(centerX, centerY, radius, frequencyData);
    } else if (state.preset === "grid") {
        drawGridPreset(width, height, frequencyData);
    } else if (state.preset === "tunnel") {
        drawTunnelPreset(centerX, centerY, radius, energy, frequencyData);
    } else if (state.preset === "split") {
        drawSplitPreset(width, height, frequencyData);
    } else if (state.preset === "scope") {
        drawScopePreset(width, height, waveformData);
    } else if (state.preset === "mesh") {
        drawMeshPreset(width, height, frequencyData);
    } else if (state.preset === "peak") {
        drawPeakPreset(width, height, frequencyData);
    } else if (state.preset === "analog") {
        drawAnalogPreset(width, height, waveformData);
    } else if (state.preset === "eq") {
        drawEqPreset(width, height, frequencyData);
    } else if (state.preset === "cascade") {
        drawCascadePreset(width, height, frequencyData);
    } else if (state.preset === "stereo") {
        drawStereoPreset(width, height, waveformData);
    } else if (state.preset === "silk") {
        drawSilkPreset(width, height, waveformData);
    } else if (state.preset === "dots") {
        drawDotsPreset(width, height, waveformData);
    } else {
        drawArcPreset(centerX, centerY, radius, frequencyData);
    }

    if (state.centerImage) {
        drawCover(cover.x, cover.y, cover.radius);
    }
    drawScrollingLyrics(width, height, elements.audio.currentTime || 0);
}

async function handlePlayToggle() {
    if (!audioUrl) {
        return;
    }
    await ensureAudioGraph();
    if (elements.audio.paused) {
        await elements.audio.play();
        notifyMainStudioPlayback();
    } else {
        elements.audio.pause();
    }
}

async function chooseUpload(kind) {
    if (kind === "image") {
        elements.imageInput.click();
    } else {
        elements.videoInput.click();
    }
}

async function applyImageFile(file) {
    if (!file) {
        return;
    }
    const url = URL.createObjectURL(file);
    backgroundImage = await loadImage(url);
    state.imageUrl = url;
    setBackgroundMode("image");
}

async function applyVideoFile(file) {
    if (!file) {
        return;
    }
    const url = URL.createObjectURL(file);
    backgroundVideo = await loadVideo(url);
    backgroundVideo.play().catch(() => {});
    state.videoUrl = url;
    setBackgroundMode("video");
}

function downloadCanvasFrame() {
    const aspect = currentAspectConfig();
    const link = document.createElement("a");
    link.href = elements.canvas.toDataURL("image/png");
    link.download = `${songTitle || "visualizer"}-${aspect.frameSuffix}-frame.png`;
    link.click();
}

function pickRecorderMimeType() {
    const candidates = [
        "video/webm;codecs=vp9,opus",
        "video/webm;codecs=vp8,opus",
        "video/webm",
    ];
    return candidates.find((value) => window.MediaRecorder.isTypeSupported(value)) || "";
}

async function renderMp4() {
    if (state.isRendering) {
        return;
    }
    if (!audioUrl) {
        setStatus(elements.renderStatus, "No song audio was passed to this page.");
        return;
    }
    const capture = elements.audio.captureStream || elements.audio.mozCaptureStream;
    if (!capture) {
        setStatus(elements.renderStatus, "This browser does not support audio capture for local rendering.");
        return;
    }

    const abort = new AbortController();
    state.renderAbort = abort;
    state.isRendering = true;
    elements.renderVideo.disabled = true;
    elements.playToggle.disabled = true;
    if (elements.renderCancel) elements.renderCancel.hidden = false;
    setStatus(elements.renderStatus, "Capturing browser render...");

    // The capture runs at playback speed, so show the clock rather than leaving
    // the user to guess how long a full song will take.
    const showProgress = () => {
        if (abort.signal.aborted) return;
        setStatus(
            elements.renderStatus,
            `Capturing ${formatDuration(elements.audio.currentTime)} / ${formatDuration(elements.audio.duration || 0)}`,
        );
    };
    elements.audio.addEventListener("timeupdate", showProgress);

    try {
        try {
            await fetch("/api/video/prepare", { method: "POST" });
        } catch {
            /* YuE2 unload is best-effort; capture still proceeds. */
        }
        await ensureAudioGraph();
        const canvasStream = elements.canvas.captureStream(30);
        const audioStream = capture.call(elements.audio);
        const combined = new MediaStream([
            ...canvasStream.getVideoTracks(),
            ...audioStream.getAudioTracks(),
        ]);
        const mimeType = pickRecorderMimeType();
        // Left unset, Chromium picks a low default bitrate, and the backend's
        // -crf 18 cannot recover detail that was never captured -- which is why
        // finished videos looked soft. ~15 Mbps at 1080p30, scaled by pixels.
        const videoBitsPerSecond = Math.min(
            40000000,
            Math.round(elements.canvas.width * elements.canvas.height * 30 * 0.25),
        );
        const recorderOptions = { videoBitsPerSecond, audioBitsPerSecond: 192000 };
        if (mimeType) recorderOptions.mimeType = mimeType;
        const recorder = new MediaRecorder(combined, recorderOptions);
        const chunks = [];

        recorder.ondataavailable = (event) => {
            if (event.data && event.data.size) {
                chunks.push(event.data);
            }
        };

        const stopped = new Promise((resolve) => {
            recorder.onstop = resolve;
        });

        recorder.start(250);
        elements.audio.currentTime = 0;
        await elements.audio.play();
        // Finish on the song ending OR on the user cancelling.
        await new Promise((resolve) => {
            const finish = () => resolve();
            elements.audio.onended = finish;
            abort.signal.addEventListener("abort", finish, { once: true });
        });
        recorder.stop();
        await stopped;

        if (abort.signal.aborted) {
            elements.audio.pause();
            setStatus(elements.renderStatus, "Render cancelled. Nothing was saved.");
            return;
        }

        const webmBlob = new Blob(chunks, { type: mimeType || "video/webm" });
        setStatus(elements.renderStatus, "Uploading for MP4 conversion...");

        const response = await fetch(`/api/video/render?title=${encodeURIComponent(songTitle || "visualizer")}`, {
            method: "POST",
            headers: { "Content-Type": "video/webm" },
            body: webmBlob,
            signal: abort.signal,
        });
        if (!response.ok) {
            const detail = await response.text();
            throw new Error(detail || "Video render failed.");
        }
        const mp4Blob = await response.blob();
        const downloadUrl = URL.createObjectURL(mp4Blob);
        const aspect = currentAspectConfig();
        const link = document.createElement("a");
        link.href = downloadUrl;
        link.download = `${songTitle || "visualizer"}-${aspect.frameSuffix}.mp4`;
        link.click();
        setStatus(elements.renderStatus, "MP4 ready and downloaded.");
    } catch (error) {
        if (error.name === "AbortError" || abort.signal.aborted) {
            setStatus(elements.renderStatus, "Render cancelled. Nothing was saved.");
        } else {
            setStatus(elements.renderStatus, `Render failed: ${error.message}`);
        }
    } finally {
        elements.audio.removeEventListener("timeupdate", showProgress);
        state.isRendering = false;
        state.renderAbort = null;
        elements.renderVideo.disabled = false;
        elements.playToggle.disabled = false;
        if (elements.renderCancel) elements.renderCancel.hidden = true;
        elements.audio.onended = null;
    }
}

async function loadTimedLyrics(urlOverride = state.currentLyricsUrl) {
    const url = urlOverride || state.currentLyricsUrl || "";
    if (!url) {
        state.currentLyricsUrl = "";
        state.lyricLines = [];
        setLyricsEnabled(false);
        return false;
    }
    try {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const payload = await response.json();
        state.currentLyricsUrl = url;
        state.lyricsLanguage = String(payload.language || "en").trim().toLowerCase() || "en";
        const lines = Array.isArray(payload.lines) ? payload.lines : [];
        state.lyricLines = lines
            .map((line, index) => ({
                index: Number(line.index || index + 1),
                text: String(line.text || "").trim(),
                start: Number(line.start || 0),
                end: Number(line.end || 0),
                matchScore: Number(line.matchScore ?? line.match_score ?? 1),
                translation: String(line.translation || "").trim(),
                words: Array.isArray(line.words) ? line.words : [],
            }))
            .filter((line) => line.text && Number.isFinite(line.start) && Number.isFinite(line.end) && line.end > line.start)
            .sort((a, b) => a.start - b.start);
        setLyricsEnabled(state.lyricLines.length > 0);
        setDualLyrics(state.dualLyrics && hasLyricTranslations());
        if (state.lyricLines.length) {
            const zeroConfidenceLines = state.lyricLines.filter((line) => Number(line.matchScore || 0) <= 0).length;
            const hasPoorTiming = zeroConfidenceLines > Math.max(2, state.lyricLines.length * 0.2);
            setLyricsSyncButton(true, false, "Re-sync Lyrics");
            setStatus(
                elements.lyricsStatus,
                hasPoorTiming
                    ? `Loaded ${state.lyricLines.length} lyric lines, but ${zeroConfidenceLines} have unreliable timing. Re-sync Lyrics will use the GPU and replace this timing pass.`
                    : `Loaded ${state.lyricLines.length} timed lyric lines${songId ? ` for ${songTitle}` : ""}. Lyrics scroll upward as the song plays, with the sung line highlighted.${hasLyricTranslations() ? " Dual language adds the English line under the sung line." : ""}`,
            );
        } else {
            setStatus(elements.lyricsStatus, "Timed lyric file loaded, but no usable subtitle lines were found.");
            setLyricsEnabled(false);
        }
        return state.lyricLines.length > 0;
    } catch (error) {
        state.lyricLines = [];
        setLyricsEnabled(false);
        state.currentLyricsUrl = "";
        setStatus(elements.lyricsStatus, `Timed lyric load failed: ${error.message}`);
        return false;
    }
}

function notifyParent(type, payload = {}) {
    if (window.parent && window.parent !== window) {
        window.parent.postMessage({ type, ...payload }, "*");
    }
}

async function findSongSnapshot() {
    if (!songId) {
        return null;
    }
    const response = await fetch("/api/library");
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    return (payload.items || []).find((song) => song.folder_name === songId || song.id === songId) || null;
}

async function refreshLyricsState() {
    if (!state.lyricsSyncBusy) {
        clearLyricsPoll();
    }
    if (!songId) {
        setLyricsEnabled(false);
        setLyricsSyncButton(false, false);
        setStatus(elements.lyricsStatus, "Open Video Studio from a saved song to load or sync timed lyrics.");
        return;
    }

    let song = null;
    try {
        song = await findSongSnapshot();
    } catch (error) {
        if (state.lyricsSyncBusy) {
            return;
        }
        setLyricsEnabled(false);
        setLyricsSyncButton(false, false);
        setStatus(elements.lyricsStatus, `Could not read the song state: ${error.message}`);
        return;
    }

    state.songHasAlignableLyrics = canAlignLyrics(song);

    const timedLyricsUrl = `/api/library/${encodeURIComponent(songId)}/timed-lyrics`;
    if (!state.lyricsSyncBusy && song?.timed_lyrics?.lines?.length && await loadTimedLyrics(timedLyricsUrl)) {
        return;
    }
    if (state.lyricsSyncBusy) {
        return;
    }

    state.currentLyricsUrl = "";
    state.lyricLines = [];
    setLyricsEnabled(false);

    if (state.songHasAlignableLyrics) {
        state.lyricsSyncJobId = "";
        setLyricsSyncButton(true, false, "Sync Lyrics");
        setStatus(
            elements.lyricsStatus,
            "Sync Lyrics matches each written line to the vocal performance. When it finishes, the lyrics will scroll upward in the preview and MP4 render.",
        );
        return;
    }

    state.lyricsSyncJobId = "";
    setLyricsSyncButton(false, false);
    setStatus(elements.lyricsStatus, "This song is instrumental or does not have saved vocal lyrics to align.");
}

function finishLyricsSyncBusy() {
    state.lyricsSyncBusy = false;
    state.lyricsSyncJobId = "";
    state.lyricsPollFailures = 0;
    clearLyricsPoll();
    restoreAudioAfterSync();
}

async function applyLyricsJobSnapshot(job, blocker = null) {
    if (!job || (job.kind && job.kind !== "lyrics_sync")) {
        return;
    }
    if (job.id) {
        state.lyricsSyncJobId = job.id;
    }
    if (job.status === "succeeded") {
        if (state.lyricsSyncNotified !== job.id) {
            state.lyricsSyncNotified = job.id;
            notifyParent("codex-song-studio-refresh-library", { songId });
        }
        const timedLyricsUrl = `/api/library/${encodeURIComponent(songId)}/timed-lyrics`;
        const loaded = await loadTimedLyrics(timedLyricsUrl);
        finishLyricsSyncBusy();
        if (!loaded) {
            setLyricsSyncButton(true, false, "Re-sync Lyrics");
            setStatus(elements.lyricsStatus, "Timed lyrics finished, but this page could not load them yet. Close and reopen Video Studio if they do not appear.");
        }
        return;
    }
    if (job.status === "failed" || job.status === "cancelled") {
        finishLyricsSyncBusy();
        setLyricsSyncButton(true, false, "Re-sync Lyrics");
        setStatus(elements.lyricsStatus, job.error || "Lyrics sync failed.");
        return;
    }
    state.lyricsSyncBusy = true;
    if (job.status === "queued") {
        restoreAudioAfterSync();
        setLyricsSyncButton(true, true, "Queued...");
        const ahead = blocker || await findBlockingJob(job.id);
        setStatus(elements.lyricsStatus, queuedLyricsStatus(ahead));
        return;
    }
    releaseAudioForSync();
    setLyricsSyncButton(true, true, "Syncing...");
    setStatus(elements.lyricsStatus, job.phase || "Aligning the written lyrics to the sung vocals.");
}

async function startLyricsSync() {
    if (!songId) {
        setStatus(elements.lyricsStatus, "Save the song first, then open Video Studio from that saved song.");
        return;
    }
    try {
        state.lyricsSyncBusy = true;
        state.lyricsPollFailures = 0;
        setLyricsSyncButton(true, true, "Starting...");
        setStatus(elements.lyricsStatus, "Starting lyric synchronization...");
        const { response, payload } = await fetchJson(`/api/library/${encodeURIComponent(songId)}/lyrics-sync`, {
            method: "POST",
        }, 20000);
        if (!response.ok) {
            throw new Error(jobErrorDetail(payload, "Lyrics sync failed to start."));
        }
        const job = payload.job || {};
        if (!job.id) {
            throw new Error("Lyrics sync started but the studio did not return a job id.");
        }
        state.lyricsSyncJobId = job.id;
        await applyLyricsJobSnapshot(job);
        notifyParent("codex-song-studio-refresh-library", { songId });
        scheduleLyricsPoll(job.id, 400);
    } catch (error) {
        finishLyricsSyncBusy();
        setLyricsSyncButton(true, false, "Re-sync Lyrics");
        setStatus(elements.lyricsStatus, `Lyrics sync start failed: ${error.message}`);
    }
}

async function pollLyricsSyncJob(jobId) {
    clearLyricsPoll();
    if (!jobId) {
        finishLyricsSyncBusy();
        setLyricsSyncButton(true, false, "Re-sync Lyrics");
        setStatus(elements.lyricsStatus, "Lyrics sync started but the studio lost the job id.");
        return;
    }
    try {
        const { response, payload } = await fetchJson(`/api/jobs/${encodeURIComponent(jobId)}`);
        if (!response.ok) {
            throw new Error(jobErrorDetail(payload, "Lyrics sync polling failed."));
        }
        const job = payload.job || payload;
        state.lyricsPollFailures = 0;
        await applyLyricsJobSnapshot(job);
        if (state.lyricsSyncBusy && job.status !== "succeeded" && job.status !== "failed" && job.status !== "cancelled") {
            scheduleLyricsPoll(jobId, 1500);
        }
    } catch (error) {
        state.lyricsPollFailures += 1;
        if (!jobId) {
            finishLyricsSyncBusy();
            setLyricsSyncButton(true, false, "Re-sync Lyrics");
            setStatus(elements.lyricsStatus, `Lyrics sync polling failed: ${error.message}`);
            return;
        }
        setStatus(
            elements.lyricsStatus,
            state.lyricsPollFailures > 2
                ? "Still waiting in the studio job queue. Retrying…"
                : "Waiting for lyric synchronization...",
        );
        scheduleLyricsPoll(jobId, 2000);
    }
}

async function refreshCoverArtState() {
    if (!songId) {
        state.coverArt = { status: "missing", imageUrl: "", downloadUrl: "", workflowName: "" };
        setStatus(elements.coverStatus, "Open this page from a saved song to use its local cover art.");
        elements.generateCover.disabled = true;
        elements.useCoverBackground.disabled = true;
        return;
    }
    try {
        const song = await findSongSnapshot();
        const coverArt = song?.cover_url
            ? { status: "ready", imageUrl: new URL(song.cover_url, window.location.origin).href, downloadUrl: song.cover_url, workflowName: "local SD 1.5" }
            : { status: "missing", imageUrl: "", downloadUrl: "", workflowName: "local SD 1.5" };
        state.coverArt = coverArt;
        if (coverArt.imageUrl) {
            try {
                coverImage = await loadImage(coverArt.imageUrl);
            } catch {
                coverImage = null;
            }
        }
        elements.generateCover.disabled = coverArt.status === "queued" || coverArt.status === "running";
        elements.useCoverBackground.disabled = !coverArt.imageUrl;
        if (coverArt.status === "queued" || coverArt.status === "running") {
            state.coverArtJobId = coverArt.id || "";
            setButtonBusy(elements.generateCover, true, "Rendering...", "Generate Cover");
            setStatus(elements.coverStatus, coverArt.progressText || "Generating local cover art.");
        } else {
            setButtonBusy(elements.generateCover, false, "Rendering...", "Generate Cover");
            if (coverArt.imageUrl) {
                setStatus(elements.coverStatus, `Cover art ready${coverArt.workflowName ? ` via ${coverArt.workflowName}` : ""}.`);
            } else {
                setStatus(elements.coverStatus, "Generate local cover art here, then use it in the visualizer.");
            }
        }
    } catch (error) {
        setButtonBusy(elements.generateCover, false, "Rendering...", "Generate Cover");
        elements.useCoverBackground.disabled = true;
        setStatus(elements.coverStatus, `Cover art status failed: ${error.message}`);
    }
}

async function pollCoverArtJob(jobId) {
    if (!jobId) {
        return;
    }
    try {
        const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || "Cover art polling failed.");
        }
        const job = payload.job || {};
        state.coverArt = job;
        if (job.status === "queued" || job.status === "running") {
            setStatus(elements.coverStatus, job.phase || "Generating local cover art.");
            setButtonBusy(elements.generateCover, true, "Rendering...", "Generate Cover");
            window.setTimeout(() => pollCoverArtJob(jobId), 3000);
            return;
        }
        setButtonBusy(elements.generateCover, false, "Rendering...", "Generate Cover");
        if (job.status === "succeeded") {
            await refreshCoverArtState();
            setStatus(elements.coverStatus, "Cover art finished. Use it as the visualizer background if you want.");
            notifyParent("codex-song-studio-cover-art-updated", { songId });
            return;
        }
        setStatus(elements.coverStatus, job.error || "Cover art generation failed.");
    } catch (error) {
        setButtonBusy(elements.generateCover, false, "Rendering...", "Generate Cover");
        setStatus(elements.coverStatus, `Cover art polling failed: ${error.message}`);
    }
}

async function generateCoverArt() {
    if (!songId) {
        setStatus(elements.coverStatus, "Save the song in the studio first, then open Video Studio from that song.");
        return;
    }
    try {
        setButtonBusy(elements.generateCover, true, "Rendering...", "Generate Cover");
        const response = await fetch(`/api/library/${encodeURIComponent(songId)}/cover`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ direction: "" }),
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || "Cover art generation failed.");
        }
        state.coverArtJobId = payload.job?.id || "";
        setStatus(elements.coverStatus, payload.job?.phase || "Generating local cover art.");
        elements.useCoverBackground.disabled = true;
        notifyParent("codex-song-studio-refresh-library", { songId });
        window.setTimeout(() => pollCoverArtJob(state.coverArtJobId), 1200);
    } catch (error) {
        setButtonBusy(elements.generateCover, false, "Rendering...", "Generate Cover");
        setStatus(elements.coverStatus, `Cover art start failed: ${error.message}`);
    }
}

async function useCoverAsBackground() {
    const coverArtUrl = state.coverArt?.imageUrl || "";
    if (!coverArtUrl) {
        setStatus(elements.coverStatus, "Generate cover art first.");
        return;
    }
    try {
        backgroundImage = await loadImage(coverArtUrl);
        state.imageUrl = coverArtUrl;
        setBackgroundMode("image");
        setStatus(elements.coverStatus, "Generated cover art is now the visualizer background.");
    } catch (error) {
        setStatus(elements.coverStatus, `Could not load cover art into the background: ${error.message}`);
    }
}

async function init() {
    if (embedded) {
        document.body.classList.add("embedded");
    }
    elements.title.textContent = songTitle;
    elements.trackWorkspace.textContent = workspaceTitle ? `Workspace: ${workspaceTitle}` : "Workspace not set";
    elements.trackLength.textContent = durationLabel || "--";
    elements.audio.src = audioUrl;
    elements.audio.volume = Number(elements.volume.value);
    elements.audio.loop = false;
    setLyricsEnabled(Boolean(initialLyricsUrl));
    setLyricsSyncButton(false, false);
    setParticleStyle(state.particleStyle);
    setAspectMode("landscape");

    if (!audioUrl) {
        setStatus(elements.loadStatus, "No audio URL was provided.");
    } else {
        setStatus(elements.loadStatus, "Waiting to play.");
    }

    if (coverUrl) {
        try {
            coverImage = await loadImage(coverUrl);
        } catch {
            coverImage = null;
        }
    }

    await refreshLyricsState();
    await refreshCoverArtState();
    updateCanvasDisplaySize();
    renderVisualizer();
}

document.querySelectorAll("[data-preset]").forEach((button) => {
    button.addEventListener("click", () => {
        state.preset = button.dataset.preset || "orbit";
        updatePresetButtons();
    });
});

document.querySelectorAll("[data-particle]").forEach((button) => {
    button.addEventListener("click", () => {
        setParticleStyle(button.dataset.particle || "dust");
    });
});

document.querySelectorAll(".swatch").forEach((button) => {
    button.addEventListener("click", () => {
        state.sceneA = button.dataset.a || state.sceneA;
        state.sceneB = button.dataset.b || state.sceneB;
        state.sceneKind = button.dataset.kind || "wash";
        document.querySelectorAll(".swatch").forEach((item) => item.classList.remove("active"));
        button.classList.add("active");
    });
});

elements.ratioLandscape.addEventListener("click", () => setAspectMode("landscape"));
elements.ratioPortrait.addEventListener("click", () => setAspectMode("portrait"));
elements.lyricsOn.addEventListener("click", () => {
    if (!state.lyricLines.length) {
        setLyricsEnabled(false);
        if (state.songHasAlignableLyrics) {
            setStatus(elements.lyricsStatus, "This song has lyrics, but they still need timing markers. Click Sync Lyrics first.");
        } else {
            setStatus(elements.lyricsStatus, "No timed lyrics are loaded.");
        }
        return;
    }
    setLyricsEnabled(true);
    if (state.lyricLines.length) {
        setStatus(elements.lyricsStatus, "Lyric overlay is on for preview and MP4 renders.");
    }
});
elements.lyricsOff.addEventListener("click", () => {
    state.lyricsEnabled = false;
    setLyricsEnabled(false);
    setStatus(elements.lyricsStatus, state.lyricLines.length ? "Lyric overlay is off." : "No timed lyrics are loaded.");
});
if (elements.dualOn && elements.dualOff) {
    elements.dualOn.addEventListener("click", () => {
        if (!hasLyricTranslations()) {
            setDualLyrics(false);
            setStatus(elements.lyricsStatus, "No English translation is saved for this song yet. Use Translate to English in Edit details first.");
            return;
        }
        setDualLyrics(true);
        setStatus(elements.lyricsStatus, "Dual language is on. The English line sits under the sung line in preview and MP4.");
    });
    elements.dualOff.addEventListener("click", () => {
        setDualLyrics(false);
        setStatus(elements.lyricsStatus, "Sung lyrics only. English translation stays saved on the song.");
    });
}
elements.bgRandom.addEventListener("click", () => setBackgroundMode("random"));
elements.bgImage.addEventListener("click", () => setBackgroundMode("image"));
elements.bgVideo.addEventListener("click", () => setBackgroundMode("video"));
elements.uploadImage.addEventListener("click", () => chooseUpload("image"));
elements.uploadVideo.addEventListener("click", () => chooseUpload("video"));
elements.imageInput.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (file) {
        await applyImageFile(file);
    }
});
elements.videoInput.addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (file) {
        await applyVideoFile(file);
    }
});
elements.bgDim.addEventListener("input", () => {
    state.backgroundDim = Number(elements.bgDim.value) / 100;
});
elements.particleCount.addEventListener("input", () => {
    state.particleCount = Number(elements.particleCount.value);
    particleCache.count = -1;
});
elements.syncLyrics.addEventListener("click", startLyricsSync);
window.addEventListener("message", (event) => {
    if (event.data?.type !== "yue2-video-studio-job") {
        return;
    }
    void applyLyricsJobSnapshot(event.data.job, event.data.blocker);
});
function setCenterImage(on) {
    state.centerImage = Boolean(on);
    elements.centerImageOn.classList.toggle("active", state.centerImage);
    elements.centerImageOff.classList.toggle("active", !state.centerImage);
    particleCache.count = -1;
    const status = document.getElementById("center-image-status");
    if (status) {
        setStatus(status, state.centerImage
            ? "Cover wraps circular presets around the thumbnail."
            : "No thumbnail. Orbit, Pulse, Halo, Sunburst, Tunnel, and Arc fill the frame.");
    }
}

elements.centerImageOn.addEventListener("click", () => setCenterImage(true));
elements.centerImageOff.addEventListener("click", () => setCenterImage(false));
elements.generateCover.addEventListener("click", generateCoverArt);
elements.useCoverBackground.addEventListener("click", useCoverAsBackground);
elements.playToggle.addEventListener("click", handlePlayToggle);
elements.volume.addEventListener("input", () => {
    elements.audio.volume = Number(elements.volume.value);
});
elements.seek.addEventListener("input", () => {
    if (Number.isFinite(elements.audio.duration) && elements.audio.duration > 0) {
        const nextTime = (Number(elements.seek.value) / 100) * elements.audio.duration;
        elements.audio.currentTime = nextTime;
        if (backgroundVideo && Number.isFinite(backgroundVideo.duration) && backgroundVideo.duration > 0) {
            backgroundVideo.currentTime = nextTime % backgroundVideo.duration;
        }
    }
});
elements.downloadFrame.addEventListener("click", downloadCanvasFrame);
elements.renderVideo.addEventListener("click", renderMp4);
if (elements.renderCancel) {
    elements.renderCancel.addEventListener("click", () => {
        if (!state.renderAbort) return;
        setStatus(elements.renderStatus, "Stopping the capture...");
        elements.audio.pause();
        state.renderAbort.abort();
    });
}

elements.audio.addEventListener("play", () => {
    elements.playToggle.textContent = "Pause";
    setStatus(elements.loadStatus, "Playing preview.");
    if (backgroundVideo && state.backgroundMode === "video") {
        backgroundVideo.play().catch(() => {});
    }
});
elements.audio.addEventListener("pause", () => {
    elements.playToggle.textContent = "Play";
    if (!state.isRendering) {
        setStatus(elements.loadStatus, "Preview paused.");
        if (backgroundVideo) {
            backgroundVideo.pause();
        }
    }
});
elements.audio.addEventListener("loadedmetadata", () => {
    elements.timeTotal.textContent = formatDuration(elements.audio.duration);
    setStatus(elements.loadStatus, "Ready.");
});
elements.audio.addEventListener("timeupdate", () => {
    elements.timeCurrent.textContent = formatDuration(elements.audio.currentTime);
    if (Number.isFinite(elements.audio.duration) && elements.audio.duration > 0) {
        elements.seek.value = String((elements.audio.currentTime / elements.audio.duration) * 100);
    } else {
        elements.seek.value = "0";
    }
});
elements.audio.addEventListener("ended", () => {
    elements.playToggle.textContent = "Play";
    elements.seek.value = "100";
    if (!state.isRendering) {
        setStatus(elements.loadStatus, "Preview finished.");
    }
});

window.addEventListener("resize", updateCanvasDisplaySize);

window.addEventListener("beforeunload", () => {
    if (renderFrame) {
        cancelAnimationFrame(renderFrame);
    }
    if (previewResizeObserver) {
        previewResizeObserver.disconnect();
    }
    if (audioContext) {
        audioContext.close().catch(() => {});
    }
});

init().catch((error) => {
    setStatus(elements.loadStatus, `Init failed: ${error.message}`);
});

if ("ResizeObserver" in window) {
    previewResizeObserver = new ResizeObserver(() => {
        updateCanvasDisplaySize();
    });
    previewResizeObserver.observe(elements.previewStage);
}
