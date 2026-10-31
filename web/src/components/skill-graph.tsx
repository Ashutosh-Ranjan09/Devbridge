"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import { Icon } from "./icons";
import { ScoreRing } from "./score";

export type GraphNode = {
  id: string; label: string; score: number; inferred: boolean; tier: string;
  from: string | null; // estimated from this skill, when there is no direct evidence
  evidence: { label: string; detail: string; date: string; against: boolean }[];
};
export type GraphLink = { from: string; to: string; type: string };

const GROUPS = [
  { tier: "fundamental", label: "Fundamentals" },
  { tier: "ecosystem", label: "Languages & tools" },
  { tier: "framework", label: "Frameworks & libraries" },
  { tier: "other", label: "Other" },
];
const LINK: Record<string, string> = { REQUIRES: "requires", PREREQUISITE_OF: "is a prerequisite of", RELATED_TO: "is related to" };

const W = 1000, H = 860, CX = W / 2, CY = H / 2;

/** The developer's own skills as a graph: themselves in the middle, the shared list's
 * tiers around them, each skill on its tier, and the list's own edges between skills.
 * A bigger, darker node is a higher score; a dashed one is estimated. Clicking a node
 * shows the evidence behind it. Laid out by angle, so it is the same on every visit. */
export function SkillGraph({ nodes, links }: { nodes: GraphNode[]; links: GraphLink[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const layout = useMemo(() => place(nodes), [nodes]);
  const ids = new Set(nodes.map((n) => n.id));
  const shown = links.filter((l) => ids.has(l.from) && ids.has(l.to));
  const focus = hover ?? selected;
  const near = new Set(focus ? [focus, ...shown.flatMap((l) => (l.from === focus ? [l.to] : l.to === focus ? [l.from] : []))] : []);
  const node = nodes.find((n) => n.id === selected) ?? null;
  const related = node ? shown.filter((l) => l.from === node.id || l.to === node.id) : [];
  // One line per kind of evidence, most influential kind first (they arrive in that order).
  const evidence = node ? [...node.evidence.reduce((m, e) => {
    const seen = m.get(e.label);
    m.set(e.label, seen ? { ...seen, count: seen.count + 1 } : { ...e, count: 1 });
    return m;
  }, new Map<string, GraphNode["evidence"][number] & { count: number }>()).values()] : [];
  const nameOf = (id: string) => nodes.find((n) => n.id === id)?.label ?? id;

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
      <section className="overflow-hidden rounded-2xl border border-line bg-panel lg:self-start">
        <svg viewBox={`0 0 ${W} ${H}`} className="block h-auto w-full select-none" role="group" aria-label="Your skill graph">
          <defs>
            <radialGradient id="g-bg" cx="50%" cy="50%" r="60%">
              <stop offset="0" stopColor="var(--accent)" stopOpacity="0.07" />
              <stop offset="1" stopColor="var(--accent)" stopOpacity="0" />
            </radialGradient>
          </defs>
          <rect width={W} height={H} fill="url(#g-bg)" onClick={() => setSelected(null)} />

          {/* You → tiers → skills. */}
          {layout.hubs.map((h) => (
            <line key={h.tier} x1={CX} y1={CY} x2={h.x} y2={h.y} className="stroke-line" strokeWidth="2" />
          ))}
          {nodes.map((n) => {
            const p = layout.at.get(n.id)!;
            const h = layout.hubs.find((x) => x.tier === p.group)!;
            const dim = focus && !near.has(n.id);
            return <line key={`h-${n.id}`} x1={h.x} y1={h.y} x2={p.x} y2={p.y} className="stroke-line" strokeWidth="1.5" opacity={dim ? 0.35 : 1} />;
          })}

          {/* The shared list's edges between skills. */}
          {shown.map((l) => {
            const a = layout.at.get(l.from)!, b = layout.at.get(l.to)!;
            const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
            const qx = mx + (CX - mx) * 0.35, qy = my + (CY - my) * 0.35;
            const lit = focus && (l.from === focus || l.to === focus);
            return (
              <path key={`${l.from}-${l.to}`} d={`M${a.x},${a.y} Q${qx},${qy} ${b.x},${b.y}`} fill="none"
                className={lit ? "stroke-accent" : "stroke-accent/40"} strokeWidth={lit ? 2.5 : 1.5} strokeDasharray="5 5"
                opacity={focus && !lit ? 0.25 : 1} />
            );
          })}

          {layout.hubs.map((h) => (
            <g key={`hub-${h.tier}`}>
              <rect x={h.x - h.w / 2} y={h.y - 17} width={h.w} height={34} rx={17} className="fill-panel stroke-line" strokeWidth="1.5" />
              <text x={h.x} y={h.y + 5} textAnchor="middle" className="fill-muted text-[15px] font-semibold">{h.label}</text>
            </g>
          ))}

          <g>
            <circle cx={CX} cy={CY} r={34} className="fill-accent" />
            <text x={CX} y={CY + 6} textAnchor="middle" className="fill-on-accent text-[17px] font-bold">You</text>
          </g>

          {nodes.map((n) => {
            const p = layout.at.get(n.id)!;
            const r = 17 + n.score * 26;
            const tone = 0.15 + n.score * 0.85;
            const dark = tone > 0.5;
            const on = selected === n.id;
            const dim = focus && !near.has(n.id);
            const c = Math.cos(p.angle);
            const anchor = c > 0.35 ? "start" : c < -0.35 ? "end" : "middle";
            const lx = p.x + Math.cos(p.angle) * (r + 8), ly = p.y + Math.sin(p.angle) * (r + 8) + (Math.abs(c) <= 0.35 ? (Math.sin(p.angle) > 0 ? 12 : -2) : 4);
            return (
              <g key={n.id} role="button" tabIndex={0} aria-pressed={on} aria-label={`${n.label}, ${Math.round(n.score * 100)} out of 100`}
                className="cursor-pointer outline-none" opacity={dim ? 0.3 : 1}
                onClick={(e) => { e.stopPropagation(); setSelected(on ? null : n.id); }}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelected(on ? null : n.id); } }}
                onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}>
                {on && <circle cx={p.x} cy={p.y} r={r + 7} fill="none" className="stroke-accent" strokeWidth="3" />}
                <circle cx={p.x} cy={p.y} r={r} className="fill-panel" />
                <circle cx={p.x} cy={p.y} r={r} className="fill-accent stroke-accent" fillOpacity={tone} strokeWidth="2"
                  strokeDasharray={n.inferred ? "4 3" : undefined} />
                <title>{n.label}</title>
                <text x={p.x} y={p.y + 5.5} textAnchor="middle" className={`text-[16px] font-bold ${dark ? "fill-on-accent" : "fill-foreground"}`}>
                  {Math.round(n.score * 100)}
                </text>
                <text x={lx} y={ly} textAnchor={anchor} className={`text-[17px] ${on ? "fill-accent font-bold" : "fill-foreground font-medium"}`}>{short(n.label)}</text>
              </g>
            );
          })}
        </svg>
        <div className="flex flex-wrap gap-x-5 gap-y-2 border-t border-line px-5 py-3 text-xs text-muted">
          <span className="flex items-center gap-1.5"><span className="size-3 rounded-full bg-accent" /> Bigger, darker: higher score</span>
          <span className="flex items-center gap-1.5"><span className="size-3 rounded-full border-2 border-dashed border-accent" /> Estimated from a related skill</span>
          <span className="flex items-center gap-1.5"><span className="w-5 border-t-2 border-dashed border-accent/60" /> Linked skills</span>
        </div>
      </section>

      <aside className="lg:sticky lg:top-20 lg:self-start">
        {node ? (
          <div className="rounded-2xl border border-line bg-panel p-5">
            <div className="flex items-center gap-4">
              <ScoreRing value={Math.round(node.score * 100)} size={72} />
              <div className="min-w-0">
                <h2 className="truncate text-lg font-bold">{node.label}</h2>
                <p className="text-sm text-muted">
                  {node.from ? `Estimated from ${nameOf(node.from)}` : `${node.evidence.length} piece${node.evidence.length === 1 ? "" : "s"} of evidence`}
                </p>
              </div>
            </div>
            <h3 className="mt-5 mb-2 text-xs font-semibold tracking-wider text-muted uppercase">What backs it</h3>
            {evidence.length === 0 ? (
              <p className="text-sm text-muted">No direct evidence yet.</p>
            ) : (
              <ul className="space-y-2.5">
                {evidence.map((e) => (
                  <li key={e.label} className="flex gap-3 text-sm">
                    <span className={`mt-1 size-2 shrink-0 rounded-full ${e.against ? "bg-danger" : "bg-accent"}`} />
                    <span className="min-w-0 flex-1">
                      <span className="font-medium">{e.label}</span>
                      {e.count > 1 && <span className="ml-1.5 rounded-full bg-accent/10 px-1.5 py-0.5 text-xs font-semibold text-accent">×{e.count}</span>}
                      {e.detail && <span className="block text-xs text-muted">{e.detail}</span>}
                    </span>
                    <span className="shrink-0 text-xs text-muted">{e.date}</span>
                  </li>
                ))}
              </ul>
            )}
            {related.length > 0 && (
              <>
                <h3 className="mt-5 mb-2 text-xs font-semibold tracking-wider text-muted uppercase">Linked skills</h3>
                <div className="flex flex-wrap gap-1.5">
                  {related.map((l) => {
                    const other = l.from === node.id ? l.to : l.from;
                    return (
                      <button key={other} type="button" onClick={() => setSelected(other)}
                        title={l.from === node.id ? `${node.label} ${LINK[l.type] ?? "links to"} ${nameOf(other)}` : `${nameOf(other)} ${LINK[l.type] ?? "links to"} ${node.label}`}
                        className="rounded-full border border-line px-2.5 py-1 text-xs font-medium transition hover:border-accent hover:text-accent">
                        {nameOf(other)}
                      </button>
                    );
                  })}
                </div>
              </>
            )}
            <Link href={`/candidate/skills/${encodeURIComponent(node.id)}`}
              className="mt-5 flex items-center justify-center gap-1.5 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-on-accent transition hover:brightness-110">
              Details and how to improve <Icon.Arrow className="size-4" />
            </Link>
          </div>
        ) : (
          <div className="rounded-2xl border border-dashed border-line bg-panel p-6 text-center">
            <span className="mx-auto grid size-12 place-items-center rounded-full bg-accent/10 text-accent"><Icon.Spark className="size-6" /></span>
            <p className="mt-3 font-semibold">Click a skill</p>
            <p className="mt-1 text-sm text-muted">See the evidence and assessments behind its score, and the skills linked to it.</p>
          </div>
        )}
      </aside>
    </div>
  );
}

/** A long name, cut to fit beside its node; the whole name is the node's tooltip. */
const short = (label: string) => (label.length > 16 ? `${label.slice(0, 15)}…` : label);

type Placed = { x: number; y: number; angle: number; group: string };

/** Skills round an ellipse, grouped by tier, each tier's arc as wide as its share of the
 * skills; tier labels between them and the centre. Alternate radii keep neighbours'
 * labels apart when there are many. */
function place(nodes: GraphNode[]) {
  const groupOf = (n: GraphNode) => (GROUPS.some((g) => g.tier === n.tier) ? n.tier : "other");
  const groups = GROUPS.map((g) => ({ ...g, members: nodes.filter((n) => groupOf(n) === g.tier) })).filter((g) => g.members.length);
  const step = (2 * Math.PI) / Math.max(nodes.length, 1);
  const at = new Map<string, Placed>();
  const hubs: { tier: string; label: string; x: number; y: number; w: number }[] = [];
  let angle = -Math.PI / 2 - (groups[0]?.members.length ?? 0) * step / 2;
  const many = nodes.length > 12;
  let i = 0;
  for (const g of groups) {
    const start = angle;
    for (const n of g.members) {
      const a = angle + step / 2;
      const r = 315 + (many ? (i % 2 ? 26 : -26) : 0);
      at.set(n.id, { x: CX + Math.cos(a) * r * 1.08, y: CY + Math.sin(a) * r, angle: a, group: g.tier });
      angle += step;
      i++;
    }
    const mid = (start + angle) / 2;
    hubs.push({ tier: g.tier, label: g.label, x: CX + Math.cos(mid) * 165, y: CY + Math.sin(mid) * 150, w: g.label.length * 8.6 + 30 });
  }
  return { at, hubs };
}
