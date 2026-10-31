import "server-only";

/** The four modules, called from the server only: the browser never sees a module's
 * address or key. Nothing here interprets an answer; it moves JSON and errors. */

export type Service = "m5" | "m6" | "assess" | "chat";

const SERVICES: Record<Service, { label: string; url: string; key?: string; health: string }> = {
  m5: {
    label: "M5 · CV verification",
    url: process.env.M5_URL ?? "http://127.0.0.1:8080",
    key: process.env.M5_API_KEY,
    health: "/healthz",
  },
  m6: {
    label: "M6 · skill graph",
    url: process.env.M6_URL ?? "http://127.0.0.1:8300",
    health: "/health",
  },
  assess: {
    label: "Assessment",
    url: process.env.ASSESS_URL ?? "http://127.0.0.1:8070",
    key: process.env.ASSESS_API_KEY,
    health: "/healthz",
  },
  chat: {
    label: "Chat",
    url: process.env.CHAT_URL ?? "http://127.0.0.1:8090",
    key: process.env.CHAT_API_KEY,
    health: "/healthz",
  },
};

export class ServiceError extends Error {
  constructor(
    readonly service: Service,
    readonly status: number, // 0: no answer at all
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

/** The error code and message, whichever module's shape it came in. M6 and assessment
 * answer {error, detail}; M5 nests that under `detail`, or sends a string there; a
 * FastAPI validation error is a list. */
export function errorOf(payload: unknown, status: number): { code: string; message: string } {
  const fallback = { code: `http_${status}`, message: `HTTP ${status}` };
  if (typeof payload !== "object" || payload === null) return fallback;
  const p = payload as Record<string, unknown>;
  if (typeof p.error === "string") {
    return { code: p.error, message: typeof p.detail === "string" ? p.detail : p.error };
  }
  if (typeof p.detail === "string") return { ...fallback, message: p.detail };
  if (Array.isArray(p.detail)) return { code: "invalid_request", message: JSON.stringify(p.detail) };
  if (typeof p.detail === "object" && p.detail !== null) return errorOf(p.detail, status);
  return fallback;
}

export async function call<T>(
  service: Service,
  path: string,
  // `body` is sent as JSON; `form` as multipart (fetch writes its boundary header).
  options: { method?: string; body?: unknown; form?: FormData; timeoutMs?: number } = {},
): Promise<T> {
  const { url, key } = SERVICES[service];
  const headers: Record<string, string> = {};
  if (key) headers.Authorization = `Bearer ${key}`;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const sends = options.body !== undefined || options.form !== undefined;
  let response: Response;
  try {
    response = await fetch(url + path, {
      method: options.method ?? (sends ? "POST" : "GET"),
      headers,
      body: options.form ?? (options.body === undefined ? undefined : JSON.stringify(options.body)),
      cache: "no-store",
      signal: AbortSignal.timeout(options.timeoutMs ?? 30_000),
    });
  } catch {
    throw new ServiceError(service, 0, "unreachable", `${SERVICES[service].label} is not answering at ${url}`);
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const { code, message } = errorOf(payload, response.status);
    throw new ServiceError(service, response.status, code, message);
  }
  return payload as T;
}

/** A module's event stream, as the response it is: the caller hands its body to the
 * browser unread. No timeout — it lasts as long as the page — and `signal` ends it when
 * the browser goes. */
export async function stream(service: Service, path: string, signal: AbortSignal): Promise<Response> {
  const { url, key } = SERVICES[service];
  let response: Response;
  try {
    response = await fetch(url + path, {
      headers: { Accept: "text/event-stream", ...(key ? { Authorization: `Bearer ${key}` } : {}) },
      cache: "no-store",
      signal,
    });
  } catch {
    throw new ServiceError(service, 0, "unreachable", `${SERVICES[service].label} is not answering at ${url}`);
  }
  if (!response.ok || !response.body) {
    const { code, message } = errorOf(await response.json().catch(() => null), response.status);
    throw new ServiceError(service, response.status, code, message);
  }
  return response;
}

export type Health = { service: Service; label: string; url: string; ok: boolean; detail: string };

/** Each module's own health route. Assessment answers 200 even when its sandbox cannot
 * run, with the reason in the body, so that is read too. */
export async function health(): Promise<Health[]> {
  return Promise.all(
    (Object.keys(SERVICES) as Service[]).map(async (service) => {
      const { label, url, health: path } = SERVICES[service];
      try {
        const body = await call<Record<string, unknown>>(service, path, { timeoutMs: 5_000 });
        const sandboxDown = service === "assess" && body.image_present === false;
        return {
          service, label, url,
          ok: !sandboxDown,
          detail: sandboxDown ? `sandbox image ${String(body.image)} is not built` : "answering",
        };
      } catch (e) {
        return { service, label, url, ok: false, detail: e instanceof Error ? e.message : String(e) };
      }
    }),
  );
}
