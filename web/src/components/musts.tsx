import type { ShortlistEntry } from "@/lib/types";

/** One applicant against a job's must-haves, as M6's shortlist answered: each interval,
 * and M6's own `clears`. Nothing is added up and nothing is ranked. */
export function Musts({ entry, skills }: { entry: ShortlistEntry | null; skills: string[] }) {
  if (!entry) return <span className="text-sm text-muted">no evidence on record</span>;
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
      {skills.map((skill) => {
        const col = entry.must[skill];
        const clears = entry.clears[skill];
        const mark = clears === true ? "✓" : clears === false ? "✗" : "·";
        return (
          <li key={skill}>
            <span className={clears === true ? "text-ok" : clears === false ? "text-danger" : "text-muted"}>{mark}</span>{" "}
            <code>{skill}</code>{" "}
            <span className="font-mono text-muted">
              {col ? `${col.interval[0].toFixed(2)}–${col.interval[1].toFixed(2)}` : "no evidence"}
            </span>
            {col?.inferred && <span className="text-muted"> inferred from related skills</span>}
            {clears === null && <span className="text-muted"> (assessed, not filtered)</span>}
          </li>
        );
      })}
    </ul>
  );
}
