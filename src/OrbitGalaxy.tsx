import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { Song } from "./api";
import { measureOrbitAudio, followAudio } from "./orbitAudio";

const MAX_RIPPLES = 6;
const STAR_COUNT = 4200;
const INNER_RING = 2.2;
const RING_GAP = 0.92;
const RING_WIDTH = 0.7;
const RIBBON_HEIGHT = 160;
const RIBBON_FONT_SIZE = 125;
const RIBBON_MAX_WIDTH = 8192;
const MUSIC_WAVE_RATE = 60;
// Preserve Orbitwave travel time and displacement in this larger scene.
const MUSIC_SCENE_SCALE = RING_GAP / 0.18;
const MUSIC_WAVE_SPEED = 3.15 * MUSIC_SCENE_SCALE;
const MUSIC_WAVE_HISTORY = 360;
const CURRENT_COLOR = "#7ef6ff";
const RECENT_COLOR = "#ffb24a";
const REST_COLOR = "#efe8dc";

const rippleVertex = /* glsl */ `
  varying vec2 vUv;
  uniform float uTime;
  uniform vec4 uRipples[${MAX_RIPPLES}];
  float rippleLift(vec3 p) {
    float lift = 0.0;
    for (int i = 0; i < ${MAX_RIPPLES}; i++) {
      vec4 rip = uRipples[i];
      if (rip.w <= 0.001) continue;
      float age = uTime - rip.z;
      if (age < 0.0 || age > 4.2) continue;
      float rad = age * 2.55;
      float d = length(p.xz - rip.xy) - rad;
      float sigma = 0.16 + age * 0.14;
      lift += rip.w * exp(-age * 1.05) * exp(-(d * d) / (2.0 * sigma * sigma));
    }
    return lift;
  }
  void main() {
    vUv = uv;
    vec3 p = position;
    p.y += rippleLift(p);
    gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
  }
`;

const rippleFragment = /* glsl */ `
  varying vec2 vUv;
  uniform sampler2D uMap;
  uniform float uOpacity;
  void main() {
    vec4 c = texture2D(uMap, vUv);
    gl_FragColor = vec4(c.rgb, c.a * uOpacity);
  }
`;

const starVertex = /* glsl */ `
  attribute float aSize;
  varying float vGlow;
  void main() {
    vGlow = 0.94;
    vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = clamp(aSize * vGlow * (68.0 / max(1.0, -mvPosition.z)), 1.35, 6.2);
    gl_Position = projectionMatrix * mvPosition;
  }
`;

const starFragment = /* glsl */ `
  uniform vec3 uStarColor;
  varying float vGlow;
  void main() {
    float d = length(gl_PointCoord - vec2(0.5));
    float core = 1.0 - smoothstep(0.0, 0.11, d);
    float halo = 1.0 - smoothstep(0.08, 0.5, d);
    float alpha = (core + halo * 0.68) * min(vGlow * 1.28, 1.5);
    if (alpha < 0.01) discard;
    gl_FragColor = vec4(uStarColor * (1.05 + vGlow * 0.62), alpha);
  }
`;

const coreVertex = /* glsl */ `
  varying vec2 vUv;
  void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }
`;

const coreFragment = /* glsl */ `
  varying vec2 vUv;
  uniform vec3 uCoreColor;
  void main() {
    vec2 p = (vUv - 0.5) * 2.0;
    float r = length(p);
    float angle = atan(p.y, p.x);
    float halo = 1.0 - smoothstep(0.08, 1.0, r);
    float rim = exp(-pow((r - 0.76) * 9.0, 2.0));
    float current = 0.5 + 0.5 * sin(angle * 5.0 + r * 10.0);
    float alpha = (halo * 0.13 + rim * 0.32 + current * halo * 0.045) * 0.9;
    if (r > 1.0 || alpha < 0.008) discard;
    gl_FragColor = vec4(uCoreColor * (0.72 + rim * 0.65), alpha);
  }
`;

type RibbonItem = { id: string; title: string; isCurrent: boolean; isRecent: boolean };
type Ring = {
  mesh: THREE.Mesh;
  items: RibbonItem[];
  angle: number;
  radius: number;
  lift: number;
  bandIndex: number;
  speed: number;
  hasCurrent: boolean;
};

function newestSongId(songs: Song[]) {
  let latest = "";
  let stamp = "";
  for (const song of songs) {
    if (song.created_at >= stamp) {
      stamp = song.created_at;
      latest = song.id;
    }
  }
  return latest;
}

function catalogItems(songs: Song[], playing: string | null, recentId: string): RibbonItem[] {
  const items: RibbonItem[] = [];
  const seen = new Set<string>();
  const ordered = [...songs].sort((left, right) => String(left.created_at || "").localeCompare(String(right.created_at || "")));
  for (const song of ordered) {
    const title = song.title.replace(/\s+/g, " ").trim();
    if (!title || seen.has(song.id)) continue;
    seen.add(song.id);
    items.push({
      id: song.id,
      title,
      isCurrent: Boolean(playing) && song.id === playing,
      isRecent: song.id === recentId && song.id !== playing,
    });
  }
  return items;
}

function starRandomFactory() {
  let seed = 0x72697070;
  return () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 4294967296;
  };
}

export default function OrbitGalaxy({ songs, playing, analyser = null }: { songs: Song[]; playing: string | null; analyser?: AnalyserNode | null }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const songsRef = useRef(songs);
  const playingRef = useRef(playing);
  const analyserRef = useRef(analyser);
  const rebuildRef = useRef<() => void>(() => undefined);
  const retintRef = useRef<() => void>(() => undefined);
  const recentId = useMemo(() => newestSongId(songs), [songs]);
  const catalogKey = [...songs].map((song) => song.id).sort().join("|");
  songsRef.current = songs;
  playingRef.current = playing;
  analyserRef.current = analyser;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false, stencil: false, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.25));
    renderer.setClearColor(0x070708, 1);
    const scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0x070708, 28, 160);
    const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 280);
    camera.position.set(0, 22.5, 13.8);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.enablePan = false;
    controls.enableZoom = false;
    controls.minDistance = 15;
    controls.maxDistance = 48;
    controls.minPolarAngle = 0.55;
    controls.maxPolarAngle = 1.15;
    controls.target.set(0, 0.2, 0);
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.25;
    const clock = new THREE.Clock();
    const ripples = Array.from({ length: MAX_RIPPLES }, () => new THREE.Vector4(0, 0, -99, 0));
    const sharedUniforms = {
      uTime: { value: 0 },
      uRipples: { value: ripples },
      uStarColor: { value: new THREE.Color("#d8e2ff") },
      uCoreColor: { value: new THREE.Color("#f3eee4") },
    };

    const random = starRandomFactory();
    const starPositions: number[] = [];
    const starSizes: number[] = [];
    for (let index = 0; index < STAR_COUNT; index += 1) {
      const y = random() * 2 - 1;
      const angle = random() * Math.PI * 2;
      const nearby = index < STAR_COUNT * 0.22;
      const radius = nearby ? 16 + random() * 14 : 48 + random() * 90;
      const span = Math.sqrt(1 - y * y);
      starPositions.push(Math.cos(angle) * span * radius, y * radius, Math.sin(angle) * span * radius);
      starSizes.push((nearby ? 1.2 : 2.4) + Math.pow(random(), 4) * (nearby ? 3.4 : 6.5));
    }
    const starGeo = new THREE.BufferGeometry();
    starGeo.setAttribute("position", new THREE.Float32BufferAttribute(starPositions, 3));
    starGeo.setAttribute("aSize", new THREE.Float32BufferAttribute(starSizes, 1));
    const starMat = new THREE.ShaderMaterial({
      uniforms: { uStarColor: sharedUniforms.uStarColor },
      vertexShader: starVertex,
      fragmentShader: starFragment,
      transparent: true,
      depthTest: false,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      fog: false,
    });
    const starfield = new THREE.Points(starGeo, starMat);
    starfield.renderOrder = -10;
    scene.add(starfield);

    const orbitalGroup = new THREE.Group();
    scene.add(orbitalGroup);
    const ringGroup = new THREE.Group();
    orbitalGroup.add(ringGroup);

    const hubMat = new THREE.MeshBasicMaterial({ color: 0x111114, side: THREE.DoubleSide });
    const hub = new THREE.Mesh(new THREE.CircleGeometry(0.48, 48), hubMat);
    hub.rotation.x = -Math.PI / 2;
    hub.position.y = 0.02;
    orbitalGroup.add(hub);
    const hubRingMat = new THREE.MeshBasicMaterial({ color: 0xf3eee4, transparent: true, opacity: 0.35, side: THREE.DoubleSide });
    const hubRing = new THREE.Mesh(new THREE.RingGeometry(0.48, 0.52, 64), hubRingMat);
    hubRing.rotation.x = -Math.PI / 2;
    hubRing.position.y = 0.03;
    orbitalGroup.add(hubRing);
    const coreGlow = new THREE.Mesh(new THREE.CircleGeometry(0.45, 64), new THREE.ShaderMaterial({
      uniforms: { uCoreColor: sharedUniforms.uCoreColor },
      vertexShader: coreVertex,
      fragmentShader: coreFragment,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
    }));
    coreGlow.rotation.x = -Math.PI / 2;
    coreGlow.position.y = 0.045;
    orbitalGroup.add(coreGlow);
    const CORE_SIGNAL_POINTS = 96;
    const coreSignalGeo = new THREE.BufferGeometry();
    coreSignalGeo.setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(CORE_SIGNAL_POINTS * 3), 3));
    (coreSignalGeo.getAttribute("position") as THREE.BufferAttribute).setUsage(THREE.DynamicDrawUsage);
    const coreSignalLevels = new Float32Array(CORE_SIGNAL_POINTS);
    const coreSignalMat = new THREE.LineBasicMaterial({ color: 0xf3eee4, transparent: true, opacity: 0.72, depthWrite: false });
    const coreSignal = new THREE.LineLoop(coreSignalGeo, coreSignalMat);
    coreSignal.position.y = 0.062;
    orbitalGroup.add(coreSignal);
    const beaconMat = new THREE.MeshBasicMaterial({ color: 0xf3eee4, transparent: true, opacity: 0.95, depthWrite: false, side: THREE.DoubleSide });
    const beaconGroup = new THREE.Group();
    beaconGroup.position.y = 0.075;
    const beacon = new THREE.Mesh(new THREE.CircleGeometry(0.022, 16), beaconMat);
    beacon.rotation.x = -Math.PI / 2;
    beacon.position.x = 0.33;
    beaconGroup.add(beacon);
    const beaconEcho = new THREE.Mesh(new THREE.CircleGeometry(0.011, 12), beaconMat.clone());
    beaconEcho.rotation.x = -Math.PI / 2;
    beaconEcho.position.x = -0.25;
    beaconGroup.add(beaconEcho);
    orbitalGroup.add(beaconGroup);

    const ribbonProbe = document.createElement("canvas").getContext("2d");
    if (!ribbonProbe) return () => { renderer.dispose(); };
    ribbonProbe.font = `800 ${RIBBON_FONT_SIZE}px Syne, Inter, "Segoe UI", sans-serif`;
    const measureRibbon = (text: string) => Math.ceil(ribbonProbe.measureText(text).width) + 24;

    const makeRibbonTexture = (items: RibbonItem[]) => {
      const labels = items.map((item) => ({ ...item, text: `${item.title.toUpperCase()}  ·  ` }));
      const width = Math.max(64, Math.min(RIBBON_MAX_WIDTH, measureRibbon(labels.map((item) => item.text).join(""))));
      const textureCanvas = document.createElement("canvas");
      textureCanvas.width = width;
      textureCanvas.height = RIBBON_HEIGHT;
      const context = textureCanvas.getContext("2d");
      if (!context) return null;
      context.font = `800 ${RIBBON_FONT_SIZE}px Syne, Inter, "Segoe UI", sans-serif`;
      context.textBaseline = "middle";
      context.textAlign = "left";
      let x = 12;
      for (const item of labels) {
        if (item.isCurrent) {
          context.shadowColor = CURRENT_COLOR;
          context.shadowBlur = 28;
          context.fillStyle = CURRENT_COLOR;
        } else if (item.isRecent) {
          context.shadowColor = RECENT_COLOR;
          context.shadowBlur = 18;
          context.fillStyle = RECENT_COLOR;
        } else {
          context.shadowBlur = 0;
          context.fillStyle = REST_COLOR;
        }
        context.fillText(item.text, x, RIBBON_HEIGHT * 0.54);
        x += context.measureText(item.text).width;
      }
      const texture = new THREE.CanvasTexture(textureCanvas);
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.anisotropy = Math.min(8, renderer.capabilities.getMaxAnisotropy());
      return { texture, aspect: width / RIBBON_HEIGHT };
    };

    const makeAnnulus = (inner: number, outer: number, arcSpan: number, segments: number) => {
      const positions: number[] = [];
      const uvs: number[] = [];
      const indices: number[] = [];
      for (let index = 0; index <= segments; index += 1) {
        const t = index / segments;
        const angle = (t - 0.5) * arcSpan;
        const cos = Math.cos(angle);
        const sin = Math.sin(angle);
        positions.push(cos * inner, 0, sin * inner, cos * outer, 0, sin * outer);
        uvs.push(t, 0.04, t, 0.96);
        if (index < segments) {
          const offset = index * 2;
          indices.push(offset, offset + 1, offset + 2, offset + 1, offset + 3, offset + 2);
        }
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
      geometry.setAttribute("uv", new THREE.Float32BufferAttribute(uvs, 2));
      geometry.setIndex(indices);
      return geometry;
    };

    let rings: Ring[] = [];
    const clearRings = () => {
      for (const ring of rings) {
        ringGroup.remove(ring.mesh);
        ring.mesh.geometry.dispose();
        const material = ring.mesh.material as THREE.ShaderMaterial;
        (material.uniforms.uMap.value as THREE.Texture).dispose();
        material.dispose();
      }
      rings = [];
    };

    const fitCamera = (outerRadius: number) => {
      const width = canvas.clientWidth || window.innerWidth;
      const height = canvas.clientHeight || window.innerHeight;
      camera.aspect = width / Math.max(1, height);
      const wanted = Math.max(24, outerRadius * 1.2 + 10);
      controls.minDistance = wanted * 0.72;
      controls.maxDistance = wanted * 1.55;
      const dist = camera.position.distanceTo(controls.target);
      if (dist > 0.01 && (dist < wanted * 0.68 || dist > wanted * 1.6)) {
        camera.position.sub(controls.target).setLength(wanted).add(controls.target);
      }
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
    };

    const retintRings = () => {
      const playingId = playingRef.current;
      const recent = newestSongId(songsRef.current);
      for (const ring of rings) {
        const items = ring.items.map((item) => ({
          ...item,
          isCurrent: Boolean(playingId) && item.id === playingId,
          isRecent: item.id === recent && item.id !== playingId,
        }));
        const flagsChanged = items.some((item, index) => item.isCurrent !== ring.items[index]?.isCurrent || item.isRecent !== ring.items[index]?.isRecent);
        if (!flagsChanged) continue;
        ring.items = items;
        ring.hasCurrent = items.some((item) => item.isCurrent);
        const image = makeRibbonTexture(items);
        if (!image) continue;
        const material = ring.mesh.material as THREE.ShaderMaterial;
        const previous = material.uniforms.uMap.value as THREE.Texture;
        material.uniforms.uMap.value = image.texture;
        material.uniforms.uOpacity.value = ring.hasCurrent ? 1 : 0.86;
        previous.dispose();
      }
    };

    const addRibbonRing = (ribbon: RibbonItem[], rowIndex: number, angle = (rowIndex * 2.399963229728653) % (Math.PI * 2), lift = 0) => {
      const radius = INNER_RING + rowIndex * RING_GAP;
      const image = makeRibbonTexture(ribbon);
      if (!image) return;
      const arcSpan = (RING_WIDTH * image.aspect) / radius;
      const hasCurrent = ribbon.some((item) => item.isCurrent);
      const material = new THREE.ShaderMaterial({
        uniforms: {
          uTime: sharedUniforms.uTime,
          uRipples: sharedUniforms.uRipples,
          uMap: { value: image.texture },
          uOpacity: { value: hasCurrent ? 1 : 0.86 },
        },
        vertexShader: rippleVertex,
        fragmentShader: rippleFragment,
        transparent: true,
        side: THREE.DoubleSide,
        depthWrite: false,
      });
      const mesh = new THREE.Mesh(
        makeAnnulus(radius - RING_WIDTH * 0.5, radius + RING_WIDTH * 0.5, arcSpan, Math.max(24, Math.ceil(arcSpan * 48))),
        material,
      );
      mesh.rotation.y = angle;
      ringGroup.add(mesh);
      rings.push({
        mesh,
        items: ribbon,
        angle,
        radius,
        lift,
        bandIndex: rowIndex % 3,
        speed: (rowIndex % 2 ? -1 : 1) * (0.035 + (rowIndex % 11) * 0.004),
        hasCurrent,
      });
      mesh.position.y = lift;
    };

    const packIntoRings = (items: RibbonItem[], startRow = 0, startAngles: number[] = [], startLift: number[] = []) => {
      let titleIndex = 0;
      let rowIndex = startRow;
      while (titleIndex < items.length) {
        const radius = INNER_RING + rowIndex * RING_GAP;
        const nativeCapacity = Math.min(RIBBON_MAX_WIDTH, Math.max(64, Math.floor(((Math.PI * 2 * radius * 0.94) / RING_WIDTH) * RIBBON_HEIGHT)));
        const ribbon: RibbonItem[] = [];
        let ribbonText = "";
        while (titleIndex < items.length) {
          const next = `${items[titleIndex].title.toUpperCase()}  ·  `;
          const needed = measureRibbon(ribbonText + next);
          if (needed > nativeCapacity) {
            if (!ribbon.length) {
              if (radius > 36) {
                ribbon.push(items[titleIndex]);
                titleIndex += 1;
                break;
              }
              rowIndex += 1;
              break;
            }
            break;
          }
          ribbon.push(items[titleIndex]);
          ribbonText += next;
          titleIndex += 1;
        }
        if (!ribbon.length) continue;
        addRibbonRing(ribbon, rowIndex, startAngles[rowIndex - startRow], startLift[rowIndex - startRow]);
        rowIndex += 1;
      }
    };

    const syncCatalog = () => {
      const items = catalogItems(songsRef.current, playingRef.current, newestSongId(songsRef.current));
      if (!rings.length) {
        packIntoRings(items);
        fitCamera(rings.length ? INNER_RING + (rings.length - 1) * RING_GAP + RING_WIDTH : INNER_RING + 2);
        return;
      }
      const known = new Set(rings.flatMap((ring) => ring.items.map((item) => item.id)));
      const newcomers = items.filter((item) => !known.has(item.id));
      if (!newcomers.length) {
        retintRings();
        return;
      }
      packIntoRings(newcomers, rings.length);
    };

    rebuildRef.current = syncCatalog;
    retintRef.current = retintRings;
    syncCatalog();
    fitCamera(rings.length ? INNER_RING + (rings.length - 1) * RING_GAP + RING_WIDTH : INNER_RING + 2);

    let freqData = new Uint8Array(1);
    let timeData = new Float32Array(1);
    let spectrum = new Float32Array(1);
    let audioStepTime: number | null = null;
    const bassHistory = new Float32Array(MUSIC_WAVE_HISTORY);
    const midHistory = new Float32Array(MUSIC_WAVE_HISTORY);
    const highHistory = new Float32Array(MUSIC_WAVE_HISTORY);
    const presenceHistory = new Float32Array(MUSIC_WAVE_HISTORY);
    let waveWrite = 0;
    let waveAccumulator = 0;
    let bandLow = 0;
    let bandMid = 0;
    let bandHigh = 0;
    let bassDrive = 0;
    let midDrive = 0;
    let highDrive = 0;
    let presenceDrive = 0;
    let beatPulse = 0;
    let wasPlaying = false;
    let lastAnalyser: AnalyserNode | null = null;
    let lastPlaying: string | null = null;
    const resetAudio = () => {
      bassHistory.fill(0); midHistory.fill(0); highHistory.fill(0); presenceHistory.fill(0);
      waveWrite = 0; waveAccumulator = 0;
      bandLow = 0; bandMid = 0; bandHigh = 0;
      bassDrive = 0; midDrive = 0; highDrive = 0; presenceDrive = 0;
      beatPulse = 0;
      wasPlaying = false;
    };
    const stepAudio = () => {
      const currentAnalyser = analyserRef.current;
      if (currentAnalyser !== lastAnalyser || playingRef.current !== lastPlaying) {
        resetAudio();
        audioStepTime = null;
        lastAnalyser = currentAnalyser;
        lastPlaying = playingRef.current;
      }
      if (!currentAnalyser || !playingRef.current || currentAnalyser.context.state !== "running") {
        resetAudio();
        audioStepTime = null;
        return;
      }
      const audioTime = currentAnalyser.context.currentTime;
      const elapsed = audioStepTime === null ? 1 / 60 : Math.max(0, audioTime - audioStepTime);
      audioStepTime = audioTime;
      // A hidden/throttled window must not replay seconds of stale ripples.
      if (elapsed > 0.25) resetAudio();
      const dt = Math.min(elapsed, 0.1);
      if (freqData.length !== currentAnalyser.frequencyBinCount) {
        freqData = new Uint8Array(currentAnalyser.frequencyBinCount);
        spectrum = new Float32Array(currentAnalyser.frequencyBinCount);
      }
      if (timeData.length !== currentAnalyser.fftSize) timeData = new Float32Array(currentAnalyser.fftSize);
      currentAnalyser.getByteFrequencyData(freqData);
      currentAnalyser.getFloatFrequencyData(spectrum);
      currentAnalyser.getFloatTimeDomainData(timeData);
      const levels = measureOrbitAudio(spectrum, timeData, currentAnalyser.context.sampleRate);
      // Linear amplitude: a quiet hit remains quiet. No logarithmic byte levels,
      // automatic gain normalization, or accumulating preset beat impulses.
      bandLow = followAudio(bandLow, levels.low, dt);
      bandMid = followAudio(bandMid, levels.mid, dt);
      bandHigh = followAudio(bandHigh, levels.high, dt);
      bassDrive = followAudio(bassDrive, levels.low, dt);
      midDrive = followAudio(midDrive, levels.mid, dt);
      highDrive = followAudio(highDrive, levels.high, dt);
      presenceDrive = followAudio(presenceDrive, levels.rms, dt);
      beatPulse = bandLow;
      wasPlaying = true;
      recordWave(elapsed > 0.25 ? 1 / MUSIC_WAVE_RATE : elapsed);
    };
    const updateCore = (time: number) => {
      const positions = coreSignalGeo.getAttribute("position");
      const playingNow = wasPlaying;
      for (let index = 0; index < CORE_SIGNAL_POINTS; index += 1) {
        const angle = (index / CORE_SIGNAL_POINTS) * Math.PI * 2;
        const folded = index <= CORE_SIGNAL_POINTS / 2 ? index / (CORE_SIGNAL_POINTS / 2) : (CORE_SIGNAL_POINTS - index) / (CORE_SIGNAL_POINTS / 2);
        const sample = playingNow ? freqData[Math.floor(Math.max(1, folded * (freqData.length - 1)))] / 255 : 0;
        coreSignalLevels[index] += (sample - coreSignalLevels[index]) * 0.2;
        const radius = 0.275 + coreSignalLevels[index] * 0.045 + bandMid * 0.012 + beatPulse * 0.008 * (0.5 + 0.5 * Math.sin(angle * 6 - time * 3));
        positions.setXYZ(index, Math.cos(angle) * radius, 0, Math.sin(angle) * radius);
      }
      positions.needsUpdate = true;
    };
    const recordWave = (delta: number) => {
      waveAccumulator += delta;
      while (waveAccumulator >= 1 / MUSIC_WAVE_RATE) {
        bassHistory[waveWrite] = bassDrive;
        midHistory[waveWrite] = midDrive;
        highHistory[waveWrite] = highDrive;
        presenceHistory[waveWrite] = presenceDrive;
        waveWrite = (waveWrite + 1) % MUSIC_WAVE_HISTORY;
        waveAccumulator -= 1 / MUSIC_WAVE_RATE;
      }
    };
    const frame = () => {
      const delta = Math.min(clock.getDelta(), 0.1);
      const time = clock.elapsedTime;
      sharedUniforms.uTime.value = time;
      stepAudio();
      updateCore(time);
      for (const ring of rings) {
        const energy = ring.bandIndex === 0 ? bandMid : ring.bandIndex === 1 ? bandHigh : bandMid * 0.62 + bandHigh * 0.38;
        ring.angle += ring.speed * (0.35 + (wasPlaying ? energy * 1.35 : 0)) * delta;
        ring.mesh.rotation.y = ring.angle;
        const outerRadius = Math.max(INNER_RING + RING_GAP, rings[rings.length - 1]?.radius || INNER_RING);
        // A large catalog must not show beats from several seconds ago at its edge.
        const waveSpeed = Math.max(MUSIC_WAVE_SPEED, (outerRadius - INNER_RING) / 0.8);
        const delay = Math.min(MUSIC_WAVE_HISTORY - 1, Math.round(Math.max(0, ring.radius - INNER_RING) / waveSpeed * MUSIC_WAVE_RATE));
        const sampleIndex = (waveWrite - 1 - delay + MUSIC_WAVE_HISTORY) % MUSIC_WAVE_HISTORY;
        const lift = bassHistory[sampleIndex] * 0.95 + midHistory[sampleIndex] * 0.24
          + highHistory[sampleIndex] * 0.12 + presenceHistory[sampleIndex] * 0.04;
        const distance = Math.min(1, Math.max(0, (ring.radius - INNER_RING) / (outerRadius - INNER_RING)));
        // Live panels cover the center. Keep the exposed outer rings responsive.
        const targetLift = Math.min(0.65, lift) * MUSIC_SCENE_SCALE * (1 - distance * 0.55);
        ring.lift = followAudio(ring.lift, targetLift, delta, 0.018, 0.07);
        ring.mesh.position.y = ring.lift;
      }
      // Ambient orbit is independent of the audio-driven vertical ripple.
      // Keep these steady rotations; never synthesize a bobbing camera or lift.
      hubRing.rotation.z += 0.01 * delta;
      ringGroup.rotation.y += delta * 0.001;
      orbitalGroup.rotation.x += delta * 0.018;
      orbitalGroup.rotation.y += delta * 0.006;
      orbitalGroup.rotation.z += delta * 0.009;
      starfield.rotation.y += delta * 0.0007;
      starfield.rotation.z += delta * 0.00015;
      hub.scale.setScalar(1 + beatPulse * 0.025 + bandLow * 0.012);
      hubRing.scale.setScalar(1 + beatPulse * 0.04 + bandMid * 0.025);
      beaconGroup.rotation.y += delta * (bandMid * 0.12 + beatPulse * 0.06);
      controls.update(delta);
      renderer.render(scene, camera);
    };
    let raf = 0;
    const render = () => { frame(); raf = requestAnimationFrame(render); };
    const resize = () => {
      const outer = rings.length ? INNER_RING + (rings.length - 1) * RING_GAP + RING_WIDTH : INNER_RING + 2;
      fitCamera(outer);
    };
    resize();
    window.addEventListener("resize", resize);
    raf = requestAnimationFrame(render);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      rebuildRef.current = () => undefined;
      retintRef.current = () => undefined;
      clearRings();
      starGeo.dispose();
      starMat.dispose();
      hub.geometry.dispose();
      hubMat.dispose();
      hubRing.geometry.dispose();
      hubRingMat.dispose();
      coreGlow.geometry.dispose();
      (coreGlow.material as THREE.Material).dispose();
      coreSignalGeo.dispose();
      coreSignalMat.dispose();
      beacon.geometry.dispose();
      beaconMat.dispose();
      beaconEcho.geometry.dispose();
      (beaconEcho.material as THREE.Material).dispose();
      controls.dispose();
      renderer.dispose();
    };
  }, []);

  useEffect(() => {
    rebuildRef.current();
  }, [catalogKey]);

  useEffect(() => {
    retintRef.current();
  }, [playing, recentId]);

  return <canvas ref={canvasRef} className="orbit-galaxy" aria-hidden="true" />;
}
