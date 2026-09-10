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
    primaryColor: document.getElementById("primary-color"),
    secondaryColor: document.getElementById("secondary-color"),
    particleCount: document.getElementById("particle-count"),
    lyricsOn: document.getElementById("lyrics-on"),
    lyricsOff: document.getElementById("lyrics-off"),
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

const ctx = elements.canvas.getContext("2d");
const state = {
    preset: "orbit",
    aspectMode: "landscape",
    backgroundMode: "random",
    backgroundDim: Number(elements.bgDim.value) / 100,
    primaryColor: elements.primaryColor.value,
    secondaryColor: elements.secondaryColor.value,
    particleStyle: "dust",
    particleCount: Number(elements.particleCount.value),
    lyricsEnabled: Boolean(initialLyricsUrl),
    lyricLines: [],
    lyricsLanguage: "en",
    currentLyricsUrl: initialLyricsUrl,
    lyricsSyncJobId: "",
    lyricsPollTimer: null,
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
    rain: "A sheet of rain falling in one wind, with longer downward streaks.",
    stars: "Twinkling starfield with occasional shooting stars.",
    embers: "Rising embers that climb the full frame and fade near the top.",
    warp: "A star-tunnel rush out from the cover art.",
    sparks: "Audio-reactive sparks bursting from the visualizer ring.",
};

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
        video.onloadeddata = () => resolve(video);
        video.onerror = reject;
    });
}

function blendColor(alpha, color) {
    const hex = color.replace("#", "");
    const normalized = hex.length === 3 ? hex.split("").map((value) => value + value).join("") : hex;
    const red = Number.parseInt(normalized.slice(0, 2), 16);
    const green = Number.parseInt(normalized.slice(2, 4), 16);
    const blue = Number.parseInt(normalized.slice(4, 6), 16);
    return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
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
        gradient.addColorStop(0, blendColor(0.9, state.primaryColor));
        gradient.addColorStop(0.5, "rgba(6, 10, 18, 0.96)");
        gradient.addColorStop(1, blendColor(0.9, state.secondaryColor));
        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, width, height);
    }

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
    highlight.addColorStop(0, blendColor(0.16 + energy * 0.0005, state.secondaryColor));
    highlight.addColorStop(1, "rgba(0, 0, 0, 0)");
    ctx.fillStyle = highlight;
    ctx.fillRect(0, 0, width, height);
}

function particleColor(alpha, index, hot = false) {
    if (hot) {
        return blendColor(alpha, index % 2 === 0 ? "#ffb14a" : state.primaryColor);
    }
    return blendColor(alpha, index % 2 === 0 ? state.primaryColor : state.secondaryColor);
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
        // Shared wind + faster fall. Per-drop gust and short dashes read as
        // confetti instead of weather.
        const depth = 0.12 + Math.pow(Math.random(), 0.72) * 0.88;
        const lean = 0.26;
        particle.streak = true;
        particle.depth = depth;
        particle.x = Math.random() * (width + height * lean) - height * lean * 0.35;
        particle.y = scatter ? Math.random() * height : -Math.random() * 90;
        particle.fall = (13 + Math.random() * 12) * (0.55 + depth);
        particle.length = 26 + depth * 52;
        particle.size = 0.7 + depth * 1.15;
        particle.alpha = 0.2 + depth * 0.42;
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
        particle.prevX = width / 2;
        particle.prevY = height / 2;
    } else if (style === "sparks") {
        const angle = Math.random() * Math.PI * 2;
        particle.x = width / 2;
        particle.y = height / 2;
        particle.vx = Math.cos(angle) * (1.2 + Math.random() * 2.4);
        particle.vy = Math.sin(angle) * (1.2 + Math.random() * 2.4);
        particle.size = 1.1 + Math.random() * 1.8;
        particle.life = 0.35 + Math.random() * 0.55;
        particle.alpha = 0.75;
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
    const scale = Math.max(width, height) * 0.58;
    const x = width * 0.5 + (particle.warpX * scale) / Math.max(0.02, particle.z);
    const y = height * 0.5 + (particle.warpY * scale) / Math.max(0.02, particle.z);
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
    const fromTop = Math.random() < 0.55;
    const startX = fromTop ? Math.random() * width : (Math.random() < 0.5 ? -40 : width + 40);
    const startY = fromTop ? -30 : Math.random() * height * 0.45;
    const targetX = width * (0.25 + Math.random() * 0.5);
    const targetY = height * (0.35 + Math.random() * 0.35);
    const dx = targetX - startX;
    const dy = targetY - startY;
    const distance = Math.hypot(dx, dy) || 1;
    const speed = 7 + Math.random() * 6;
    shootingStars.push({
        x: startX,
        y: startY,
        vx: (dx / distance) * speed,
        vy: (dy / distance) * speed,
        life: 28 + Math.random() * 18,
        maxLife: 40,
        tail: 18 + Math.random() * 22,
        brightness: 0.7 + Math.random() * 0.3,
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
    ctx.globalCompositeOperation = "lighter";

    for (let index = 0; index < fxParticles.length; index += 1) {
        const particle = fxParticles[index];

        if (style === "rain") {
            if (!particle.streak) {
                Object.assign(particle, createFxParticle("rain", width, height, true, particle.index));
            }
            // One wind angle for every drop. A tiny shared gust keeps the
            // sheet alive without scattering streaks into confetti.
            const wind = 0.24 + Math.sin(now * 0.00055) * 0.035;
            const fall = particle.fall * (0.92 + energyBoost * 0.12);
            const vx = Math.sin(wind) * fall;
            const vy = Math.cos(wind) * fall;
            particle.x += vx * delta;
            particle.y += vy * delta;
            if (particle.y > height + 50 || particle.x > width + 50) {
                Object.assign(particle, createFxParticle("rain", width, height, false, particle.index));
            }
            const speed = Math.hypot(vx, vy) || 1;
            ctx.strokeStyle = `rgba(198, 226, 242, ${particle.alpha})`;
            ctx.lineWidth = particle.size;
            ctx.lineCap = "round";
            ctx.beginPath();
            ctx.moveTo(particle.x - (vx / speed) * particle.length, particle.y - (vy / speed) * particle.length);
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
        } else if (style === "sparks") {
            particle.x += particle.vx * energyBoost * delta;
            particle.y += particle.vy * energyBoost * delta;
            particle.vx *= 0.985;
            particle.vy *= 0.985;
            particle.life -= 0.012 * delta;
            if (particle.life <= 0 || particle.x < -20 || particle.x > width + 20 || particle.y < -20 || particle.y > height + 20) {
                Object.assign(particle, createFxParticle("sparks", width, height, false, particle.index));
                const radius = Math.min(width, height) * 0.16;
                const angle = Math.random() * Math.PI * 2;
                particle.x = width / 2 + Math.cos(angle) * radius;
                particle.y = height / 2 + Math.sin(angle) * radius;
            }
            ctx.fillStyle = particleColor(Math.max(0.08, particle.life * particle.alpha), index, true);
            ctx.beginPath();
            ctx.arc(particle.x, particle.y, particle.size * (0.7 + energyBoost * 0.2), 0, Math.PI * 2);
            ctx.fill();
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
            ctx.strokeStyle = `rgba(255,255,255,${fade * star.brightness})`;
            ctx.lineWidth = 1.4 + fade;
            ctx.beginPath();
            ctx.moveTo(star.x, star.y);
            ctx.lineTo(star.x - star.vx * star.tail * 0.35, star.y - star.vy * star.tail * 0.35);
            ctx.stroke();
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
        gradient.addColorStop(0, state.primaryColor);
        gradient.addColorStop(1, state.secondaryColor);
        ctx.fillStyle = gradient;
        ctx.fillRect(centerX - radius, centerY - radius, radius * 2, radius * 2);
        ctx.fillStyle = "rgba(255,255,255,0.9)";
        ctx.font = `${Math.max(22, radius * 0.22)}px "Plus Jakarta Sans"`;
        ctx.textAlign = "center";
        ctx.fillText(songTitle.slice(0, 18), centerX, centerY + 10);
    }
    ctx.restore();

    ctx.lineWidth = Math.max(3, radius * 0.04);
    ctx.strokeStyle = blendColor(0.7, state.primaryColor);
    ctx.beginPath();
    ctx.arc(centerX, centerY, radius + 2, 0, Math.PI * 2);
    ctx.stroke();
}

function drawOrbitPreset(centerX, centerY, radius, spectrum) {
    const bars = 96;
    const baseRadius = radius + 18;
    for (let index = 0; index < bars; index += 1) {
        const value = spectrum[index % spectrum.length] / 255;
        const angle = (index / bars) * Math.PI * 2;
        const barLength = 20 + value * 100;
        const innerX = centerX + Math.cos(angle) * baseRadius;
        const innerY = centerY + Math.sin(angle) * baseRadius;
        const outerX = centerX + Math.cos(angle) * (baseRadius + barLength);
        const outerY = centerY + Math.sin(angle) * (baseRadius + barLength);
        ctx.strokeStyle = index % 2 === 0 ? blendColor(0.95, state.primaryColor) : blendColor(0.95, state.secondaryColor);
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(innerX, innerY);
        ctx.lineTo(outerX, outerY);
        ctx.stroke();
    }
}

function drawBarsPreset(width, height, spectrum) {
    const portrait = state.aspectMode === "portrait";
    const barWidth = width / 72;
    // Sit on the canvas floor. Portrait lyrics occupy ~48–96% of the frame, so
    // keep the bars in the bottom band instead of growing through the karaoke.
    const maxRise = height * (portrait ? 0.18 : 0.32);
    spectrum.slice(0, 72).forEach((value, index) => {
        const normalized = value / 255;
        const barHeight = 18 + normalized * maxRise;
        const x = index * barWidth;
        const y = height - barHeight;
        ctx.fillStyle = index % 2 === 0 ? blendColor(0.95, state.primaryColor) : blendColor(0.95, state.secondaryColor);
        ctx.fillRect(x + 3, y, Math.max(4, barWidth - 6), barHeight);
    });
}

function drawPulsePreset(centerX, centerY, radius, energy) {
    for (let ring = 0; ring < 4; ring += 1) {
        const scale = 1 + ring * 0.22 + energy / 900 + Math.sin((performance.now() / 220) + ring) * 0.02;
        ctx.beginPath();
        ctx.lineWidth = 10 - ring * 2;
        ctx.strokeStyle = ring % 2 === 0 ? blendColor(0.45 - ring * 0.08, state.primaryColor) : blendColor(0.42 - ring * 0.08, state.secondaryColor);
        ctx.arc(centerX, centerY, radius * scale, 0, Math.PI * 2);
        ctx.stroke();
    }
}

function drawWavePreset(width, height, waveform) {
    ctx.beginPath();
    ctx.lineWidth = 5;
    ctx.strokeStyle = blendColor(0.9, state.primaryColor);
    const mid = height * 0.58;
    waveform.forEach((value, index) => {
        const x = (index / (waveform.length - 1)) * width;
        const y = mid + ((value - 128) / 128) * (height * 0.18);
        if (index === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });
    ctx.stroke();
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
        ctx.fillStyle = blendColor(0.9, state.primaryColor);
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
        return blendColor(0.98, state.primaryColor);
    }
    return "rgba(255,255,255,0.42)";
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
    return rows.length * lineHeight;
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
    const fontSize = Math.max(portrait ? 25 : 23, Math.min(width, height) * (portrait ? 0.035 : 0.02));
    const lyricsWidth = width * (portrait ? 0.86 : 0.74);
    const scrollTop = height * (portrait ? 0.48 : 0.58);
    const scrollBottom = height - (portrait ? 52 : 40);
    const anchorY = height * (portrait ? 0.72 : 0.77);
    const firstIndex = Math.max(0, Math.floor(focusIndex) - 1);
    const lastIndex = Math.min(state.lyricLines.length - 1, Math.ceil(focusIndex) + 1);
    const wordGap = lyricWordGap(fontSize);
    ctx.font = `800 ${fontSize}px "Plus Jakarta Sans"`;
    let tallestBlock = fontSize * 1.32;
    for (let index = firstIndex; index <= lastIndex; index += 1) {
        const rows = layoutLyricRows(lyricWordItems(state.lyricLines[index]), lyricsWidth, wordGap);
        tallestBlock = Math.max(tallestBlock, rows.length * fontSize * 1.32);
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

function renderVisualizer() {
    renderFrame = window.requestAnimationFrame(renderVisualizer);
    const width = elements.canvas.width;
    const height = elements.canvas.height;
    const portrait = state.aspectMode === "portrait";

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

    const centerX = width / 2;
    const centerY = portrait ? height * 0.39 : (height / 2) - 40;
    const radius = Math.min(width, height) * (portrait ? 0.19 : 0.14);

    if (state.preset === "orbit") {
        drawOrbitPreset(centerX, centerY, radius, frequencyData);
    } else if (state.preset === "bars") {
        drawBarsPreset(width, height, frequencyData);
    } else if (state.preset === "pulse") {
        drawPulsePreset(centerX, centerY, radius, energy);
        drawOrbitPreset(centerX, centerY, radius, frequencyData.slice(0, 48));
    } else {
        drawWavePreset(width, height, waveformData);
    }

    if (state.centerImage) {
        drawCover(centerX, centerY, radius);
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
        if (state.lyricLines.length) {
            const zeroConfidenceLines = state.lyricLines.filter((line) => Number(line.matchScore || 0) <= 0).length;
            const hasPoorTiming = zeroConfidenceLines > Math.max(2, state.lyricLines.length * 0.2);
            setLyricsSyncButton(true, false, "Re-sync Lyrics");
            setStatus(
                elements.lyricsStatus,
                hasPoorTiming
                    ? `Loaded ${state.lyricLines.length} lyric lines, but ${zeroConfidenceLines} have unreliable timing. Re-sync Lyrics will use the GPU and replace this timing pass.`
                    : `Loaded ${state.lyricLines.length} timed lyric lines${songId ? ` for ${songTitle}` : ""}. Lyrics scroll upward as the song plays, with the sung line highlighted.`,
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
    if (state.lyricsPollTimer) {
        window.clearTimeout(state.lyricsPollTimer);
        state.lyricsPollTimer = null;
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
        setLyricsEnabled(false);
        setLyricsSyncButton(false, false);
        setStatus(elements.lyricsStatus, `Could not read the song state: ${error.message}`);
        return;
    }

    state.songHasAlignableLyrics = canAlignLyrics(song);

    const timedLyricsUrl = `/api/library/${encodeURIComponent(songId)}/timed-lyrics`;
    if (song?.timed_lyrics?.lines?.length && await loadTimedLyrics(timedLyricsUrl)) return;

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

async function startLyricsSync() {
    if (!songId) {
        setStatus(elements.lyricsStatus, "Save the song first, then open Video Studio from that saved song.");
        return;
    }
    try {
        setLyricsSyncButton(true, true, "Syncing...");
        const response = await fetch(`/api/library/${encodeURIComponent(songId)}/lyrics-sync`, {
            method: "POST",
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || "Lyrics sync failed to start.");
        }
        const job = payload.job || {};
        state.lyricsSyncJobId = job.id || "";
        setStatus(elements.lyricsStatus, job.phase || "Aligning the written lyrics to the sung vocals.");
        notifyParent("codex-song-studio-refresh-library", { songId });
        if (state.lyricsPollTimer) {
            window.clearTimeout(state.lyricsPollTimer);
        }
        state.lyricsPollTimer = window.setTimeout(() => pollLyricsSyncJob(state.lyricsSyncJobId), 1200);
    } catch (error) {
        setLyricsSyncButton(true, false, "Re-sync Lyrics");
        setStatus(elements.lyricsStatus, `Lyrics sync start failed: ${error.message}`);
    }
}

async function pollLyricsSyncJob(jobId) {
    if (state.lyricsPollTimer) {
        window.clearTimeout(state.lyricsPollTimer);
        state.lyricsPollTimer = null;
    }
    if (!jobId) {
        return;
    }
    try {
        const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.detail || "Lyrics sync polling failed.");
        }
        const job = payload.job || {};
        if (job.status === "succeeded") {
            notifyParent("codex-song-studio-refresh-library", { songId });
            state.currentLyricsUrl = `/api/library/${encodeURIComponent(songId)}/timed-lyrics`;
            await refreshLyricsState();
            return;
        }
        if (job.status === "failed") {
            setLyricsSyncButton(true, false, "Re-sync Lyrics");
            setStatus(elements.lyricsStatus, job.error || "Lyrics sync failed.");
            return;
        }
        setLyricsSyncButton(true, true, "Syncing...");
        setStatus(elements.lyricsStatus, job.phase || "Aligning the written lyrics to the sung vocals.");
        state.lyricsPollTimer = window.setTimeout(() => pollLyricsSyncJob(jobId), 2500);
    } catch (error) {
        setLyricsSyncButton(true, false, "Re-sync Lyrics");
        setStatus(elements.lyricsStatus, `Lyrics sync polling failed: ${error.message}`);
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
        state.primaryColor = button.dataset.primary || state.primaryColor;
        state.secondaryColor = button.dataset.secondary || state.secondaryColor;
        elements.primaryColor.value = state.primaryColor;
        elements.secondaryColor.value = state.secondaryColor;
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
elements.primaryColor.addEventListener("input", () => {
    state.primaryColor = elements.primaryColor.value;
});
elements.secondaryColor.addEventListener("input", () => {
    state.secondaryColor = elements.secondaryColor.value;
});
elements.particleCount.addEventListener("input", () => {
    state.particleCount = Number(elements.particleCount.value);
    particleCache.count = -1;
});
elements.syncLyrics.addEventListener("click", startLyricsSync);
function setCenterImage(on) {
    state.centerImage = Boolean(on);
    elements.centerImageOn.classList.toggle("active", state.centerImage);
    elements.centerImageOff.classList.toggle("active", !state.centerImage);
    const status = document.getElementById("center-image-status");
    if (status) {
        setStatus(status, state.centerImage
            ? "Circular cover sits in the visualizer."
            : "Center image is off. Visualizer rings keep going.");
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
        elements.audio.currentTime = (Number(elements.seek.value) / 100) * elements.audio.duration;
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
});
elements.audio.addEventListener("pause", () => {
    elements.playToggle.textContent = "Play";
    if (!state.isRendering) {
        setStatus(elements.loadStatus, "Preview paused.");
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
    if (backgroundVideo && backgroundVideo.readyState >= 2 && Number.isFinite(backgroundVideo.duration) && backgroundVideo.duration > 0) {
        backgroundVideo.currentTime = elements.audio.currentTime % backgroundVideo.duration;
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
