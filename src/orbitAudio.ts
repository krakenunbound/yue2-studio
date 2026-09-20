/** Measure linear audible amplitude, using FFT power only to split it into bands. */
export function measureOrbitAudio(spectrum: Float32Array, waveform: Float32Array, sampleRate: number) {
  let square = 0;
  for (const sample of waveform) square += sample * sample;
  const rms = Math.sqrt(square / Math.max(1, waveform.length));
  let total = 0, low = 0, mid = 0, high = 0;
  const binHz = sampleRate / (2 * spectrum.length);
  for (let i = 1; i < spectrum.length; i++) {
    const power = Number.isFinite(spectrum[i]) ? Math.pow(10, spectrum[i] / 10) : 0;
    const hz = i * binHz;
    total += power;
    if (hz < 240) low += power;
    else if (hz < 2500) mid += power;
    else high += power;
  }
  const amplitude = (power: number) => total > 0 ? rms * Math.sqrt(power / total) : 0;
  return { low: amplitude(low), mid: amplitude(mid), high: amplitude(high), rms };
}

/** Attack/release in seconds, independent of display refresh rate. */
export function followAudio(value: number, target: number, dt: number, attack = 0.012, release = 0.075) {
  return value + (target - value) * (1 - Math.exp(-Math.max(0, dt) / (target > value ? attack : release)));
}
