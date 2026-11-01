import "server-only";

import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";

/** Files people upload here: a candidate's CV (so it can be shown back) and the proofs
 * beside it. On disk under .data/files/ (gitignored, like the database), named by the
 * row that owns them, never by anything the uploader typed. */

// FILES_DIR: the tests point it at a temporary folder, as they do the database.
const ROOT = process.env.FILES_DIR ?? path.join(process.cwd(), ".data", "files");

/** What may be stored, by extension, with the type it is served as. No SVG or HTML:
 * a file that runs script must not be served from this site's origin. */
const TYPES: Record<string, string> = {
  ".pdf": "application/pdf",
  ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
};

export const extOf = (fileName: string): string => path.extname(fileName).toLowerCase();
export const typeOf = (fileName: string): string => TYPES[extOf(fileName)] ?? "application/octet-stream";
/** Shown in the page (an iframe or an img); anything else is downloaded. */
export const viewable = (fileName: string): boolean => [".pdf", ".png", ".jpg", ".jpeg"].includes(extOf(fileName));

type Kind = "cv" | "proofs";
// `id` is a cuid or M5's verification id: letters, digits, _ and - only, so it cannot
// climb out of its folder whatever the extension.
const where = (kind: Kind, id: string, fileName: string) => {
  if (!/^[\w-]+$/.test(id) || !TYPES[extOf(fileName)]) throw new Error("bad file key");
  return path.join(ROOT, kind, id + extOf(fileName));
};

export async function saveFile(kind: Kind, id: string, fileName: string, file: File): Promise<void> {
  const to = where(kind, id, fileName);
  await mkdir(path.dirname(to), { recursive: true });
  await writeFile(to, Buffer.from(await file.arrayBuffer()));
}

/** The bytes, or null when there are none (a CV uploaded before files were kept). */
export async function readStored(kind: Kind, id: string, fileName: string): Promise<Buffer | null> {
  try {
    return await readFile(where(kind, id, fileName));
  } catch {
    return null;
  }
}

export async function removeFile(kind: Kind, id: string, fileName: string): Promise<void> {
  await rm(where(kind, id, fileName), { force: true });
}

/** The file as a response: its own type (by extension, from the list above), shown in
 * the page when it can be, never sniffed into something else, never cached. */
export function fileResponse(bytes: Buffer, fileName: string): Response {
  const safe = fileName.replace(/[^\w.\- ()]/g, "_");
  return new Response(new Uint8Array(bytes), {
    headers: {
      "Content-Type": typeOf(fileName),
      "Content-Disposition": `${viewable(fileName) ? "inline" : "attachment"}; filename="${safe}"; filename*=UTF-8''${encodeURIComponent(fileName)}`,
      "X-Content-Type-Options": "nosniff",
      "Cache-Control": "private, no-store",
    },
  });
}
