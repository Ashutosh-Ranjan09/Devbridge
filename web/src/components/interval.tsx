/** One skill's interval on a 0–1 line, exactly as M6 returns it: the band is the
 * interval, the tick is the mean. No colour for good or bad, and no single number. */
export function Interval({ interval: [lo, hi], mean }: { interval: [number, number]; mean: number }) {
  return (
    <div className="flex items-center gap-3">
      <div className="relative h-2 w-40 rounded-full bg-line" aria-hidden>
        <div className="absolute h-2 rounded-full bg-accent/50" style={{ left: `${lo * 100}%`, width: `${(hi - lo) * 100}%` }} />
        <div className="absolute -top-1 h-4 w-0.5 bg-accent" style={{ left: `${mean * 100}%` }} />
      </div>
      <span className="font-mono text-sm">{lo.toFixed(2)}–{hi.toFixed(2)}</span>
    </div>
  );
}
