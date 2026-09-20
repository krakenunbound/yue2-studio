import type { TimedLyricLine, TimedLyrics, TimedWord } from "./api";

function displayWords(line: TimedLyricLine): TimedWord[] {
  if (line.words?.length) return line.words;
  const words = line.text.trim().split(/\s+/).filter(Boolean);
  const span = Math.max(0.18, line.end - line.start);
  return words.map((text, index) => ({ text, start: line.start + (span * index / words.length), end: index === words.length - 1 ? line.end : line.start + (span * (index + 1) / words.length) }));
}

export default function KaraokeLyrics({ lyrics, currentTime, compact = false }: { lyrics?: TimedLyrics | null; currentTime: number; compact?: boolean }) {
  const lines = lyrics?.lines ?? [];
  if (!lines.length) return null;
  const performingIndex = lines.findIndex((line) => currentTime >= line.start - 0.12 && currentTime <= line.end + 0.16);
  let focusIndex = performingIndex;
  if (focusIndex < 0) {
    const upcoming = lines.findIndex((line) => line.start > currentTime);
    focusIndex = upcoming >= 0 ? upcoming : lines.length - 1;
  }
  const lineHeight = compact ? 48 : 76;
  const focusOffset = compact ? 21 : 104;
  return <section className={`karaoke ${compact ? "compact" : ""}`} aria-label="Synchronized lyrics">
    <div className="karaoke-focus" aria-hidden="true" />
    <div className="karaoke-track" style={{ transform: `translateY(${focusOffset - focusIndex * lineHeight}px)` }}>
      {lines.map((line, index) => {
        const words = displayWords(line);
        return <div className={`karaoke-line ${index === performingIndex ? "active" : currentTime > line.end + 0.16 ? "past" : "future"}`} key={`${line.index}-${line.start}`}>
          <div className="karaoke-original">{words.map((word, wordIndex) => {
            const state = currentTime >= word.end ? "sung" : currentTime >= word.start ? "singing" : "waiting";
            return <span className={state} key={`${word.start}-${wordIndex}`}>{word.text}{wordIndex < words.length - 1 ? " " : ""}</span>;
          })}</div>
          {line.translation && <div className="karaoke-translation">{line.translation}</div>}
        </div>;
      })}
    </div>
  </section>;
}
