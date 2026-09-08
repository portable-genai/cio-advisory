/**
 * What the client holds today, beside what their risk profile calls for.
 *
 * This is the before-picture a briefing is read against, and it is the panel that makes the
 * talking points mean anything: without it a recommendation is a theme, and with it a
 * recommendation is a theme that closes a gap the reader can see.
 *
 * Every figure comes from the server, including the drift and the money. Nothing here
 * recomputes a number the engine owns, so what the reader sees is what the engine used.
 */

import type { AllocationGap, GapStatus, PortfolioSummary } from "@/lib/types";
import { ASSET_CLASS_LABEL, GAP_STATUS_LABEL } from "@/lib/types";
import { Empty } from "./ui";

const STATUS_TONE: Record<GapStatus, string> = {
  under: "bg-regblue-100 text-regblue-800",
  in_range: "bg-emerald-100 text-emerald-800",
  over: "bg-amber-100 text-amber-800",
};

function pct(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function money(value: number, currency: string): string {
  const rounded = Math.round(Math.abs(value));
  return `${currency} ${rounded.toLocaleString("en-US")}`;
}

/** The band as a bar, with the client's actual weight marked on it. */
function BandBar({ gap }: { gap: AllocationGap }) {
  // The scale runs to the larger of the band's ceiling and where the client actually sits,
  // so an over-allocated position stays visible on its own bar instead of pinning at 100%.
  const scale = Math.max(gap.max_weight, gap.current_weight, 0.01) * 1.15;
  const left = (gap.min_weight / scale) * 100;
  const width = ((gap.max_weight - gap.min_weight) / scale) * 100;
  const marker = Math.min((gap.current_weight / scale) * 100, 100);
  const target = (gap.target_weight / scale) * 100;
  return (
    <div className="relative h-2 w-full rounded-full bg-ink-100" aria-hidden="true">
      <div
        className="absolute h-2 rounded-full bg-emerald-200"
        style={{ left: `${left}%`, width: `${Math.max(width, 1)}%` }}
      />
      <div
        className="absolute h-2 w-px bg-emerald-700"
        style={{ left: `${target}%` }}
      />
      <div
        className={`absolute -top-0.5 h-3 w-1 rounded-sm ${
          gap.status === "in_range" ? "bg-emerald-700" : "bg-regblue-700"
        }`}
        style={{ left: `${marker}%` }}
      />
    </div>
  );
}

function GapRow({ gap, currency }: { gap: AllocationGap; currency: string }) {
  const short = gap.status === "under";
  return (
    <tr className="border-t border-ink-100 align-middle">
      <td className="py-2 pr-3 text-sm text-ink-800">
        {ASSET_CLASS_LABEL[gap.asset_class] ?? gap.asset_class}
      </td>
      <td className="py-2 pr-3 text-right font-mono text-sm text-ink-800">
        {pct(gap.current_weight)}
      </td>
      <td className="py-2 pr-3 text-right font-mono text-sm text-ink-400">
        {pct(gap.target_weight)}
        <span className="ml-1 text-[11px]">
          ({pct(gap.min_weight)} to {pct(gap.max_weight)})
        </span>
      </td>
      <td className="w-32 py-2 pr-3">
        <BandBar gap={gap} />
      </td>
      <td className="py-2 pr-3">
        <span
          className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${STATUS_TONE[gap.status]}`}
        >
          {GAP_STATUS_LABEL[gap.status]}
        </span>
      </td>
      <td className="py-2 text-right font-mono text-sm">
        {gap.status === "in_range" ? (
          <span className="text-ink-300">-</span>
        ) : (
          <span className={short ? "text-regblue-700" : "text-amber-700"}>
            {short ? "+" : "-"}
            {money(gap.value_gap, currency)}
          </span>
        )}
      </td>
    </tr>
  );
}

export function PortfolioSummaryPanel({ summary }: { summary?: PortfolioSummary | null }) {
  if (!summary) return <Empty>No portfolio loaded.</Empty>;
  const model = summary.model_portfolio;
  const under = summary.allocation_gaps.filter((g) => g.status === "under");
  const over = summary.allocation_gaps.filter((g) => g.status === "over");

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="font-mono text-lg text-ink-800">
          {money(summary.total_value, summary.currency)}
        </span>
        <span className="text-sm text-ink-500">
          {summary.risk_appetite} profile
          {model ? ` · measured against ${model.model_id}` : ""}
        </span>
      </div>

      {model ? (
        <>
          <p className="text-sm text-ink-600">
            {under.length > 0 ? (
              <>
                Short of{" "}
                <span className="font-medium text-regblue-800">
                  {under.map((g) => ASSET_CLASS_LABEL[g.asset_class]).join(", ")}
                </span>
                .{" "}
              </>
            ) : (
              <>Every asset class is inside its band. </>
            )}
            {over.length > 0 ? (
              <>
                Heavy in{" "}
                <span className="font-medium text-amber-800">
                  {over.map((g) => ASSET_CLASS_LABEL[g.asset_class]).join(", ")}
                </span>
                .
              </>
            ) : null}
          </p>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] border-collapse">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-ink-500">
                  <th className="pb-1 pr-3 font-semibold">Asset class</th>
                  <th className="pb-1 pr-3 text-right font-semibold">Holds</th>
                  <th className="pb-1 pr-3 text-right font-semibold">Target</th>
                  <th className="pb-1 pr-3 font-semibold">Band</th>
                  <th className="pb-1 pr-3 font-semibold">Status</th>
                  <th className="pb-1 text-right font-semibold">To target</th>
                </tr>
              </thead>
              <tbody>
                {summary.allocation_gaps.map((gap) => (
                  <GapRow key={gap.asset_class} gap={gap} currency={summary.currency} />
                ))}
              </tbody>
            </table>
          </div>
          {model.source ? (
            <p className="text-[11px] text-ink-400">
              Target allocation: {model.source}
              {model.effective_from ? `, effective ${model.effective_from}` : ""}.
            </p>
          ) : null}
        </>
      ) : (
        <p className="text-sm text-ink-500">
          No model portfolio is published for this risk profile, so no allocation gaps are
          computed. The holdings below are shown without a target to measure them against.
        </p>
      )}

      <div className="overflow-x-auto">
        <table className="w-full min-w-[30rem] border-collapse">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-ink-500">
              <th className="pb-1 pr-3 font-semibold">Holding</th>
              <th className="pb-1 pr-3 font-semibold">Asset class</th>
              <th className="pb-1 pr-3 text-right font-semibold">Weight</th>
              <th className="pb-1 text-right font-semibold">Value</th>
            </tr>
          </thead>
          <tbody>
            {summary.holdings.map((holding) => (
              <tr key={holding.instrument_id || holding.instrument} className="border-t border-ink-100">
                <td className="py-1.5 pr-3 text-sm text-ink-800">
                  {holding.instrument}
                  {holding.tags.length > 0 ? (
                    <span className="ml-2 text-[11px] text-ink-400">
                      {holding.tags.join(" · ")}
                    </span>
                  ) : null}
                </td>
                <td className="py-1.5 pr-3 text-sm text-ink-500">
                  {ASSET_CLASS_LABEL[holding.asset_class] ?? holding.asset_class}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono text-sm text-ink-800">
                  {pct(holding.weight)}
                </td>
                <td className="py-1.5 text-right font-mono text-sm text-ink-600">
                  {money(holding.value, holding.currency)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
