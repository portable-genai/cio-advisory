/** Renders one personalised, suitability-checked talking point (never advice). */

import type { TalkingPoint } from "@/lib/types";
import { CitationList } from "./CitationCard";
import { SuitabilityBadge } from "./SuitabilityBadge";
import { Pill } from "./ui";

export function TalkingPointView({ point }: { point: TalkingPoint }) {
  return (
    <article className="rounded-lg border border-ink-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-semibold text-ink-800">{point.headline}</h3>
        <Pill tone="info">not advice</Pill>
      </div>
      <p className="mt-1 text-sm text-ink-600">{point.body}</p>

      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-500">
        <span className="font-medium text-ink-600">theme:</span>
        <span>{point.house_view_theme}</span>
        {point.linked_holdings.length > 0 && (
          <>
            <span className="font-medium text-ink-600">holdings:</span>
            <span>{point.linked_holdings.join(", ")}</span>
          </>
        )}
      </div>

      <SuitabilityBadge assessment={point.suitability} />

      <details className="mt-2">
        <summary className="cursor-pointer text-xs font-medium text-regblue-600">
          Citations
        </summary>
        <CitationList citations={point.citations} />
      </details>
    </article>
  );
}
