import type { Proof } from "@/generated/prisma/client";

import { Card } from "./ui";

/** A candidate's CV file and the documents they added beside it, for a recruiter or an
 * admin. Their uploads: nothing in them was checked, and the label says so. */
export function Documents({ cv, proofs }: { cv: { id: string; fileName: string }; proofs: Proof[] }) {
  return (
    <Card>
      <h2 className="mb-1 font-semibold">Documents</h2>
      <p className="mb-3 text-xs text-muted">Uploaded by the candidate. Not checked against any source.</p>
      <ul className="space-y-2 text-sm">
        <li>
          <a href={`/files/cv/${cv.id}`} target="_blank" rel="noopener" className="font-medium text-accent hover:underline">{cv.fileName}</a>
          <span className="text-muted"> · the CV</span>
        </li>
        {proofs.map((p) => (
          <li key={p.id}>
            <a href={`/files/proof/${p.id}`} target="_blank" rel="noopener" className="font-medium text-accent hover:underline">{p.fileName}</a>
            <span className="text-muted"> · for {p.label}</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
