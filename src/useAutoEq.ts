import { useEffect, useRef, useState } from "react";
import type { Song } from "./api";
import { automaticPreset, EQ_FLAT, EQ_PRESETS } from "./eqProfiles";

const EQ_GAINS_STORAGE = "yue2-radio-eq";
const AUTO_EQ_STORAGE = "yue2-radio-auto-eq";

export type AutoEqState = {
  autoEq: boolean;
  setAutoEq: (value: boolean) => void;
  autoPreset: string;
  preset: string;
  displayGains: number[];
  displayGainsRef: React.MutableRefObject<number[]>;
  applyPreset: (name: string) => void;
  setBand: (band: number, value: number) => void;
};

export default function useAutoEq(song: Song | null): AutoEqState {
  const [gains, setGains] = useState<number[]>(() => {
    try { return JSON.parse(localStorage.getItem(EQ_GAINS_STORAGE) || "null") || EQ_FLAT.slice(); }
    catch { return EQ_FLAT.slice(); }
  });
  const [autoEq, setAutoEq] = useState(() => localStorage.getItem(AUTO_EQ_STORAGE) !== "false");
  const [preset, setPreset] = useState("Flat");
  const [displayGains, setDisplayGains] = useState<number[]>(gains);
  const displayGainsRef = useRef(displayGains);
  const autoPreset = automaticPreset(song);

  useEffect(() => { localStorage.setItem(EQ_GAINS_STORAGE, JSON.stringify(gains)); }, [gains]);
  useEffect(() => { localStorage.setItem(AUTO_EQ_STORAGE, String(autoEq)); }, [autoEq]);

  useEffect(() => {
    const target = (autoEq ? EQ_PRESETS[autoPreset] : gains).slice();
    if (!autoEq) {
      displayGainsRef.current = target;
      setDisplayGains(target);
      return;
    }
    const from = displayGainsRef.current.slice();
    const started = performance.now();
    let frame = 0;
    const animate = (now: number) => {
      const progress = Math.min(1, (now - started) / 900);
      const eased = progress < 0.5 ? 2 * progress * progress : 1 - ((-2 * progress + 2) ** 2) / 2;
      const next = target.map((value, band) => (from[band] ?? 0) + (value - (from[band] ?? 0)) * eased);
      displayGainsRef.current = next;
      setDisplayGains(next);
      if (progress < 1) frame = requestAnimationFrame(animate);
    };
    frame = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frame);
  }, [autoEq, autoPreset, song?.id, gains]);

  function applyPreset(name: string) {
    setAutoEq(false);
    setPreset(name);
    setGains((EQ_PRESETS[name] || EQ_FLAT).slice());
  }

  function setBand(band: number, value: number) {
    setAutoEq(false);
    setPreset("Custom");
    setGains((current) => current.map((gain, index) => index === band ? value : gain));
  }

  return { autoEq, setAutoEq, autoPreset, preset, displayGains, displayGainsRef, applyPreset, setBand };
}
