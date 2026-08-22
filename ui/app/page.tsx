/**
 * B3 CIO Advisory console.
 *
 * Pick a client, build a suitability-checked advisory briefing, and read the personalised
 * talking points (each tagged with a suitability verdict and citations) plus the portfolio
 * alignment. The whole surface is framed as decision-support, not advice.
 *
 * Identity is server-verified: no actor is ever sent in a request body. In the local
 * profile a "Demo identity" picker selects a seeded dev persona (X-Dev-Persona header);
 * in secure profiles identity comes from the IAP assertion and the picker never renders.
 */

"use client";

import { useCallback, useEffect, useState } from "react";
import { BriefingView } from "@/components/BriefingView";
import { ClientPanel } from "@/components/ClientPanel";
import { ErrorNote, Panel } from "@/components/ui";
import { ApiError, api, setDevPersona } from "@/lib/api";
import type { Persona } from "@/lib/api";
import type { AdvisoryBriefing } from "@/lib/types";

const IS_EMBEDDED = process.env.NEXT_PUBLIC_EMBED === "1";

export default function Home() {
  const [briefing, setBriefing] = useState<AdvisoryBriefing | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<{
    ok: boolean;
    profile?: string;
    region?: string;
  }>({ ok: false });
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedPersona, setSelectedPersona] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const h = await api.healthz();
      if (cancelled) return;
      setHealth({ ok: h.ok, profile: h.raw?.profile, region: h.raw?.region });
      // The persona picker is a LOCAL-profile convenience only: secure profiles
      // resolve identity from the IAP assertion and /v1/personas returns [].
      if (h.raw?.profile !== "local") return;
      try {
        const list = await api.listPersonas();
        if (cancelled || list.length === 0) return;
        setPersonas(list);
        setSelectedPersona(list[0].id);
        setDevPersona(list[0].id);
      } catch {
        // Persona picker is dev-only convenience; ignore lookup failures.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function onPersonaChange(id: string) {
    setSelectedPersona(id);
    setDevPersona(id);
  }

  const run = useCallback(async (clientId: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.briefing({ client_id: clientId });
      setBriefing(result);
    } catch (e) {
      const message =
        e instanceof ApiError ? e.message : "Could not reach the advisory backend.";
      setError(message);
      setBriefing(null);
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <main
      className={
        IS_EMBEDDED
          ? "flex flex-col gap-4 p-4 lg:flex-row"
          : "mx-auto flex max-w-6xl flex-col gap-6 p-6 lg:flex-row"
      }
    >
      <ClientPanel onRun={run} loading={loading} health={health} />

      <div className="min-w-0 flex-1 space-y-4">
        {!IS_EMBEDDED && personas.length > 0 && (
          <Panel title="Demo identity">
            <label className="text-sm">
              <span className="text-ink-500">Persona (local profile only)</span>
              <select
                className="mt-1 w-full rounded-md border border-ink-200 px-2 py-1.5 text-sm sm:w-96"
                value={selectedPersona}
                onChange={(e) => onPersonaChange(e.target.value)}
              >
                {personas.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.subject} · {p.tenant}
                  </option>
                ))}
              </select>
            </label>
          </Panel>
        )}

        {error && <ErrorNote message={error} />}
        {!error && !briefing && !loading && (
          <div className="rounded-xl border border-dashed border-ink-200 bg-white p-10 text-center text-sm text-ink-400">
            Pick a client and build a briefing to see suitability-checked talking points.
          </div>
        )}
        {loading && (
          <div className="rounded-xl border border-ink-200 bg-white p-10 text-center text-sm text-ink-400">
            Building a grounded, suitability-checked briefing...
          </div>
        )}
        {briefing && <BriefingView briefing={briefing} />}
      </div>
    </main>
  );
}
