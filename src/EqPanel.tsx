import { EQ_BAND_LABELS, EQ_PRESETS } from "./eqProfiles";

type Props = {
  autoEq: boolean;
  setAutoEq: (value: boolean) => void;
  autoPreset: string;
  preset: string;
  displayGains: number[];
  applyPreset: (name: string) => void;
  setBand: (band: number, value: number) => void;
  note: string;
};

export default function EqPanel({ autoEq, setAutoEq, autoPreset, preset, displayGains, applyPreset, setBand, note }: Props) {
  return <div className="eq-panel">
    <label className="switch eq-auto-eq radio-auto-eq"><input type="checkbox" checked={autoEq} onChange={(event) => setAutoEq(event.target.checked)} /><span /><strong>Auto EQ</strong><small>{autoEq ? `${autoPreset} · animated` : "Manual"}</small></label>
    <div className="eq-presets radio-presets">{Object.keys(EQ_PRESETS).map((name) => <button key={name} type="button" className={autoEq && autoPreset === name ? "auto-active" : !autoEq && preset === name ? "active" : ""} onClick={() => applyPreset(name)}>{name}</button>)}</div>
    <div className="eq-bands radio-bands">
      {EQ_BAND_LABELS.map((label, band) => <label key={label} className="eq-band radio-band">
        <input type="range" min={-12} max={12} step={1} value={displayGains[band] ?? 0} onChange={(event) => setBand(band, Number(event.target.value))} />
        <b>{(displayGains[band] ?? 0) > 0 ? `+${Math.round(displayGains[band])}` : Math.round(displayGains[band] ?? 0)}</b>
        <span>{label}</span>
      </label>)}
    </div>
    <p className="modal-note">{note}</p>
  </div>;
}
