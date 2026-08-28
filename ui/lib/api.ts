/**
 * Typed fetch client for the B3 CIO Advisory Assistant FastAPI backend.
 *
 * Routes (SPEC §6):
 *   POST /v1/briefing        -> AdvisoryBriefing
 *   POST /v1/talking-points  -> TalkingPointsResponse
 *   POST /v1/suitability     -> SuitabilityAssessment
 *   GET  /healthz            -> HealthResponse
 *   GET  /v1/personas        -> Persona[] (local profile only; feeds the picker)
 *
 * Identity is resolved SERVER-side (never from the request body). In the local profile
 * the backend resolves a seeded dev persona from the `X-Dev-Persona` header; in secure
 * profiles that header is ignored (identity comes from the IAP-injected assertion).
 *
 * A guardrail block or an unavailable client returns HTTP 200 with an explicit envelope
 * (`blocked` or `unavailable`), never a 5xx; the client surfaces that as a typed error so
 * the UI can render it cleanly.
 */

import type {
  AdvisoryBriefing,
  HealthResponse,
  SuitabilityAssessment,
  TalkingPointsResponse,
} from "./types";
import { ConfiguredEmptyError, readEnvValue } from "./env-setting.mjs";

// The API base is resolved in THREE states, not two.
//
// Reading `process.env.NEXT_PUBLIC_API_BASE || "<loopback default>"` hands a
// variable an operator DELIBERATELY EMPTIED the loopback default. That is a widening: the
// console then talks to a local API instead of the configured one, and `connect-src` is built
// from the same value, so the emptied deployment is byte-identical to one that never configured
// the variable at all. Next inlines NEXT_PUBLIC_* AT BUILD TIME, so the wrong value is frozen
// into the bundle and cannot be corrected by fixing the environment at start-up.
//
// Unset keeps the documented loopback default, which is what a laptop wants. Set-and-empty
// refuses, because an emptied value names nothing and the default is the more permissive branch.
const DEFAULT_API_BASE = "http://localhost:8091";
// The literal member expression is required: a bundler substitutes the public value
// only where it sees exactly this, and handing it `process.env` leaves the browser
// reading {} and silently taking the hard-coded loopback default.
const API_BASE_SETTING = readEnvValue(
  "NEXT_PUBLIC_API_BASE",
  process.env.NEXT_PUBLIC_API_BASE,
);
if (API_BASE_SETTING.isConfiguredEmpty) {
  throw new ConfiguredEmptyError(
    "NEXT_PUBLIC_API_BASE is set to an empty value. An emptied variable names nothing, " +
      "so it cannot inherit the unset default (" + DEFAULT_API_BASE + "), which points this " +
      "console at a loopback API and widens connect-src to match. Unset it to take that " +
      "default deliberately, or give it the API origin this deployment should call.",
  );
}
export const API_BASE = (API_BASE_SETTING.hasValue ? API_BASE_SETTING.value : DEFAULT_API_BASE).replace(
  /\/+$/,
  "",
);

// Dev-only identity selection. In LOCAL mode the backend resolves identity from
// the X-Dev-Persona header; in secure profiles this is ignored (identity comes
// from an IAP assertion injected by the platform).
let devPersona = "";

export function setDevPersona(id: string): void {
  devPersona = id;
}

export function getDevPersona(): string {
  return devPersona;
}

export interface Persona {
  id: string;
  subject: string;
  tenant: string;
  principals: string;
}

export class ApiError extends Error {
  status: number;
  body: string;
  constructor(message: string, status: number, body: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

function requestHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (devPersona) headers["X-Dev-Persona"] = devPersona;
  return headers;
}

async function parseJsonOrThrow(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!res.ok) {
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      detail = (parsed && (parsed.detail || parsed.message || parsed.error)) || text;
    } catch {
      /* keep raw text */
    }
    throw new ApiError(
      `${res.status} ${res.statusText}: ${detail || "request failed"}`,
      res.status,
      text,
    );
  }
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    throw new ApiError("Malformed JSON in response", res.status, text);
  }
}

/** Reject a 200 envelope that signals a blocked or unavailable request. */
function rejectEnvelope(raw: unknown): void {
  if (raw && typeof raw === "object") {
    const obj = raw as Record<string, unknown>;
    if (obj.blocked === true || obj.unavailable === true) {
      const reason = String(obj.detail || obj.reason || "request could not be completed");
      throw new ApiError(reason, 200, JSON.stringify(obj));
    }
  }
}

function withTimeout(signal?: AbortSignal, ms = 60_000): AbortSignal {
  if (signal) return signal;
  const ctor = AbortSignal as typeof AbortSignal & {
    timeout?: (ms: number) => AbortSignal;
  };
  if (typeof ctor.timeout === "function") {
    return ctor.timeout(ms);
  }
  return new AbortController().signal;
}

// NOTE: no `actor` field. The backend derives the audit actor from the verified
// Principal (api/security.py); anything the client asserts would be ignored.
interface ClientBody {
  client_id: string;
}

interface SuitabilityBody {
  client_id: string;
  theme: string;
}

// --------------------------------------------------------------------------- //
// Endpoints
// --------------------------------------------------------------------------- //
export async function briefing(
  body: ClientBody,
  signal?: AbortSignal,
): Promise<AdvisoryBriefing> {
  const res = await fetch(`${API_BASE}/v1/briefing`, {
    method: "POST",
    headers: requestHeaders(),
    body: JSON.stringify(body),
    signal: withTimeout(signal),
  });
  const raw = await parseJsonOrThrow(res);
  rejectEnvelope(raw);
  return raw as AdvisoryBriefing;
}

export async function talkingPoints(
  body: ClientBody,
  signal?: AbortSignal,
): Promise<TalkingPointsResponse> {
  const res = await fetch(`${API_BASE}/v1/talking-points`, {
    method: "POST",
    headers: requestHeaders(),
    body: JSON.stringify(body),
    signal: withTimeout(signal),
  });
  const raw = await parseJsonOrThrow(res);
  rejectEnvelope(raw);
  return raw as TalkingPointsResponse;
}

export async function suitability(
  body: SuitabilityBody,
  signal?: AbortSignal,
): Promise<SuitabilityAssessment> {
  const res = await fetch(`${API_BASE}/v1/suitability`, {
    method: "POST",
    headers: requestHeaders(),
    body: JSON.stringify(body),
    signal: withTimeout(signal),
  });
  const raw = await parseJsonOrThrow(res);
  rejectEnvelope(raw);
  return raw as SuitabilityAssessment;
}

export async function healthz(
  signal?: AbortSignal,
): Promise<{ ok: boolean; raw: HealthResponse | null }> {
  try {
    const res = await fetch(`${API_BASE}/healthz`, {
      method: "GET",
      signal: withTimeout(signal, 8_000),
    });
    if (!res.ok) return { ok: false, raw: null };
    const raw = (await res.json().catch(() => null)) as HealthResponse | null;
    return { ok: raw?.status === "ok", raw };
  } catch {
    return { ok: false, raw: null };
  }
}

/** Seeded dev personas for the local picker; empty outside the local profile. */
export async function listPersonas(signal?: AbortSignal): Promise<Persona[]> {
  const res = await fetch(`${API_BASE}/v1/personas`, {
    method: "GET",
    signal: withTimeout(signal, 8_000),
  });
  const raw = await parseJsonOrThrow(res);
  return (raw ?? []) as Persona[];
}

/** Where the client registration JSON template can be downloaded. */
export const CLIENT_TEMPLATE_URL = `${API_BASE}/v1/clients/template`;

export interface ClientRegistration {
  client_id: string;
  tenant: string;
  holdings: number;
  total_value: number;
}

/** Register an audience-provided client (profile + holdings JSON, opaque ids only). */
export async function registerClient(
  body: unknown,
  signal?: AbortSignal,
): Promise<ClientRegistration> {
  const res = await fetch(`${API_BASE}/v1/clients`, {
    method: "POST",
    headers: requestHeaders(),
    body: JSON.stringify(body),
    signal: withTimeout(signal),
  });
  const raw = await parseJsonOrThrow(res);
  return raw as ClientRegistration;
}

/** The client ids registered for the caller's tenant (live profile picker). */
export async function listClients(signal?: AbortSignal): Promise<string[]> {
  const res = await fetch(`${API_BASE}/v1/clients`, {
    method: "GET",
    headers: requestHeaders(),
    signal: withTimeout(signal, 8_000),
  });
  const raw = (await parseJsonOrThrow(res)) as { clients?: string[] };
  return raw?.clients ?? [];
}

export const api = {
  briefing,
  talkingPoints,
  suitability,
  healthz,
  listPersonas,
  registerClient,
  listClients,
};
