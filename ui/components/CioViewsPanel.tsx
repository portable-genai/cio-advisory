/**
 * The CIO report as it stands against this portfolio: opportunities and threats.
 *
 * Every theme the briefing weighed appears here, not only the ones that survived
 * suitability, so a relationship manager reads the house view rather than a version of it
 * edited down for one client. What each row adds is the part that is about THIS portfolio:
 * the gap an opportunity would close, the position a threat bears on, and the holdings the
 * theme actually touches, matched by tag rather than by a model's opinion.
 *
 * The signal is derived server-side from the published stance, so an overweight can never
 * render as a threat here however the wording is changed.
 */

import type { AllocationGap, ThemeAlignment, ThemeSignal } from "@/lib/types";
import { ASSET_CLASS_LABEL } from "@/lib/types";
import { Empty } from "./ui";

const SIGNAL_TONE: Record<ThemeSignal, string> = {
  opportunity: "bg-emerald-100 text-emerald-800",
  threat: "bg-amber-100 text-amber-800",
  watch: "bg-ink-100 text-ink-600",
};

const SIGNAL_TEXT: Record<ThemeSignal, string> = {
  opportunity: "Opportunity",
  threat: "Threat",
  watch: "Watch",
};

function money(value: number): string {
  return Math.round(Math.abs(value)).toLocaleString("en-US");
}

/** What this theme means for this portfolio, in one line, or nothing when it means little. */
function Implication({ link }: { link: ThemeAlignment }) {
  const gap: AllocationGap | null = link.addresses ?? link.exposure;
  const assetClass = ASSET_CLASS_LABEL[link.asset_class] ?? link.asset_class;
  if (!gap) {
    // Nothing to close and nothing to flag. Two different reasons, and saying the wrong one
    // is a visible error: a client holding 35 percent of an asset class inside its band was
    // being told they had "no position" in it. `related_holdings` is what tells them apart.
    return link.related_holdings.length > 0 ? (
      <span className="text-ink-500">Held, and {assetClass} is inside its band</span>
    ) : (
      <span className="text-ink-400">No position in {assetClass}</span>
    );
  }
  if (link.addresses) {
    return (
      <span className="text-regblue-800">
        Closes a {Math.round(Math.abs(gap.drift) * 100)} point shortfall in {assetClass}, about{" "}
        {money(gap.value_gap)} to target
      </span>
    );
  }
  return (
    <span className="text-amber-800">
      Bears on {Math.round(gap.current_weight * 100)}% held in {assetClass}
      {gap.status === "over" ? ", above its band" : ""}
    </span>
  );
}

export function CioViewsPanel({ links }: { links?: ThemeAlignment[] }) {
  if (!links || links.length === 0) return <Empty>No CIO house views retrieved.</Empty>;
  const opportunities = links.filter((l) => l.signal === "opportunity");
  const threats = links.filter((l) => l.signal !== "opportunity");

  function Group({ title, rows }: { title: string; rows: ThemeAlignment[] }) {
    if (rows.length === 0) return null;
    return (
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-ink-500">{title}</h4>
        <ul className="mt-1 space-y-2">
          {rows.map((link) => (
            <li key={link.theme} className="rounded-lg border border-ink-100 p-2">
              <div className="flex flex-wrap items-baseline gap-2">
                <span
                  className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${SIGNAL_TONE[link.signal]}`}
                >
                  {SIGNAL_TEXT[link.signal]}
                </span>
                <span className="text-sm font-medium text-ink-800">{link.theme}</span>
              </div>
              <p className="mt-1 text-xs">
                <Implication link={link} />
              </p>
              {link.related_holdings.length > 0 ? (
                <p className="mt-1 text-[11px] text-ink-500">
                  Touches: {link.related_holdings.join(", ")}
                </p>
              ) : null}
              {link.citation ? (
                <p className="mt-1 text-[11px] text-ink-400">
                  Source: {link.citation.title || link.citation.source_id}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Group title="Opportunities" rows={opportunities} />
      <Group title="Threats and watch items" rows={threats} />
    </div>
  );
}
