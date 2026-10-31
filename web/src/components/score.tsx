/** A skill's score out of 100 in a ring. One colour whatever the value: the ring shows
 * how far along, not whether that is good or bad. */
export function ScoreRing({ value, size = 64, label }: { value: number; size?: number; label?: string }) {
  const r = 15.5;
  const c = 2 * Math.PI * r;
  const big = size >= 96;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }} role="img" aria-label={label ?? `Score ${value} out of 100`}>
      <svg viewBox="0 0 36 36" className="size-full -rotate-90">
        <circle cx="18" cy="18" r={r} fill="none" strokeWidth="3" className="stroke-line" />
        <circle
          cx="18" cy="18" r={r} fill="none" strokeWidth="3" strokeLinecap="round" className="stroke-accent"
          strokeDasharray={`${(Math.max(value, 2) / 100) * c} ${c}`}
        />
      </svg>
      <span className="absolute inset-0 grid place-items-center">
        <span className="text-center leading-none">
          <span className={`block font-bold tracking-tight ${big ? "text-3xl" : "text-base"}`}>{value}</span>
          {big && <span className="mt-1 block text-xs text-muted">out of 100</span>}
        </span>
      </span>
    </div>
  );
}
