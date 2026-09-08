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
import { PortfolioSummaryPanel } from "@/components/PortfolioSummaryPanel";
import { ClientPanel } from "@/components/ClientPanel";
import { Stage, activeStage, useStageTakeover } from "@/components/StageStack";
import { ErrorNote, Panel } from "@/components/ui";
import { ASSET_CLASS_LABEL } from "@/lib/types";
import { ApiError, api, setDevPersona } from "@/lib/api";
import type { Persona } from "@/lib/api";
import type { AdvisoryBriefing, PortfolioSummary } from "@/lib/types";

const IS_EMBEDDED = process.env.NEXT_PUBLIC_EMBED === "1";

export default function Home() {
  const [briefing, setBriefing] = useState<AdvisoryBriefing | null>(null);
  // The before-picture. Loaded when a client is PICKED, not when a briefing is built: the
  // gaps are arithmetic over the holdings and the published allocation, so there is no
  // reason to make a reader wait for a model to see what their client actually holds.
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<{
    ok: boolean;
    profile?: string;
    region?: string;
  }>({ ok: false });
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedPersona, setSelectedPersona] = useState("");
  // Which stages a reader has opened or closed by hand. Once taken over, a stage stops
  // being driven by how far the work has got: see components/StageStack.tsx.
  const { taken, onTakeOver } = useStageTakeover();

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

  const select = useCallback(async (clientId: string) => {
    setBriefing(null);
    setError(null);
    setSummary(null);
    if (!clientId.trim()) return;
    try {
      setSummary(await api.clientPortfolio(clientId.trim()));
    } catch {
      // A client with no portfolio yet is a normal state, not an error worth a banner:
      // the panel simply does not render and the briefing button still works.
      setSummary(null);
    }
  }, []);

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

  // Once a briefing exists, its OWN portfolio summary feeds the portfolio stage: that is the
  // book the briefing was computed from, and preferring it means the collapsed line and the
  // conclusions above it can never describe two different reads.
  const portfolio = briefing?.portfolio_summary ?? summary;

  // "The last stage that has something to show" — so the newest content is the focus
  // without any stage having to name itself, and adding a stage later needs no new rule.
  const active = activeStage([
    { id: "portfolio", ready: portfolio !== null },
    { id: "briefing", ready: briefing !== null },
  ]);

  return (
    <main
      className={
        IS_EMBEDDED
          ? "flex flex-col gap-4 p-4 lg:flex-row"
          : "mx-auto flex max-w-6xl flex-col gap-6 p-6 lg:flex-row"
      }
    >
      <ClientPanel onRun={run} onSelect={select} loading={loading} health={health} />

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

        {/* The portfolio and the briefing are STAGES, not a swap. The portfolio is what
            makes the recommendations mean something, so when the briefing arrives it
            collapses to a line that still carries its figures rather than unmounting: a
            reader can reopen the evidence beside the conclusion drawn from it, and the
            briefing is at the top of the viewport without anyone scrolling. */}
        {portfolio && (
          <Stage
            id="portfolio"
            active={active === "portfolio"}
            taken={taken}
            onTakeOver={onTakeOver}
            summary={<PortfolioStageSummary summary={portfolio} />}
          >
            <PortfolioSummaryPanel summary={portfolio} />
          </Stage>
        )}

        {!error && !briefing && !portfolio && !loading && (
          <div className="rounded-xl border border-dashed border-ink-200 bg-white p-10 text-center text-sm text-ink-400">
            Pick a client to see their portfolio, then build a briefing.
          </div>
        )}
        {loading && (
          <div className="rounded-xl border border-ink-200 bg-white p-10 text-center text-sm text-ink-400">
            Building a grounded, suitability-checked briefing...
          </div>
        )}
        {briefing && (
          <Stage
            id="briefing"
            active={active === "briefing"}
            taken={taken}
            onTakeOver={onTakeOver}
            summary={<BriefingStageSummary briefing={briefing} />}
          >
            <BriefingView briefing={briefing} />
          </Stage>
        )}
      </div>
    </main>
  );
}

/**
 * The portfolio stage's collapsed line.
 *
 * It carries the FIGURES, not the panel's name. That is the whole discipline of this
 * pattern: a stage that closes must still assert what it found, or collapsing has deleted
 * the evidence the panel existed to show. What survives here is what the panel is for —
 * the size of the book, and how many asset classes sit outside their band.
 */
function PortfolioStageSummary({ summary }: { summary: PortfolioSummary }) {
  const outside = summary.allocation_gaps.filter((g) => g.status !== "in_range");
  const total = summary.total_value.toLocaleString(undefined, {
    maximumFractionDigits: 0,
  });
  return (
    <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <span className="font-medium text-ink-800">Portfolio</span>
      <span className="text-ink-500">
        {summary.holdings.length}{" "}
        {summary.holdings.length === 1 ? "position" : "positions"} &middot; {total}{" "}
        {summary.currency}
      </span>
      {outside.length > 0 ? (
        <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[11px] font-medium text-amber-700">
          {outside.length} outside band:{" "}
          {outside
            .map((g) => ASSET_CLASS_LABEL[g.asset_class] ?? g.asset_class)
            .join(", ")}
        </span>
      ) : (
        <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-[11px] font-medium text-emerald-700">
          every class in band
        </span>
      )}
    </span>
  );
}

/** The briefing stage's collapsed line: how many points, and whether a human must sign. */
function BriefingStageSummary({ briefing }: { briefing: AdvisoryBriefing }) {
  return (
    <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <span className="font-medium text-ink-800">Briefing</span>
      <span className="text-ink-500">
        {briefing.talking_points.length}{" "}
        {briefing.talking_points.length === 1 ? "talking point" : "talking points"}
      </span>
      {briefing.requires_human_review ? (
        <span className="rounded bg-regblue-50 px-1.5 py-0.5 text-[11px] font-medium text-regblue-700">
          requires human review
        </span>
      ) : null}
    </span>
  );
}
