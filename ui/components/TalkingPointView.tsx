/** Renders one personalised, suitability-checked talking point (never advice). */

import type { TalkingPoint } from "@/lib/types";
import { ASSET_CLASS_LABEL } from "@/lib/types";
import { CitationList } from "./CitationCard";
import { SuitabilityBadge } from "./SuitabilityBadge";
import { Pill } from "./ui";

/**
 * What this point does for this portfolio, computed server-side.
 *
 * The chip is the answer to the question a relationship manager asks of any recommendation:
 * why this client. It is rendered from the engine's arithmetic rather than from the model's
 * prose, so it cannot claim a gap the portfolio does not have however the point is worded.
 */
function AlignmentChip({ point }: { point: TalkingPoint }) {
  const alignment = point.alignment;
  if (!alignment) return null;
  if (alignment.addresses) {
    const gap = alignment.addresses;
    return (
      <span className="rounded bg-regblue-100 px-1.5 py-0.5 text-[11px] font-medium text-regblue-800">
        Closes {Math.round(Math.abs(gap.drift) * 100)} points in{" "}
        {ASSET_CLASS_LABEL[gap.asset_class] ?? gap.asset_class} (
        {Math.round(Math.abs(gap.value_gap)).toLocaleString("en-US")} to target)
      </span>
    );
  }
  if (alignment.exposure) {
    const gap = alignment.exposure;
    return (
      <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-medium text-amber-800">
        Bears on {Math.round(gap.current_weight * 100)}% held in{" "}
        {ASSET_CLASS_LABEL[gap.asset_class] ?? gap.asset_class}
      </span>
    );
  }
  return null;
}

export function TalkingPointView({ point }: { point: TalkingPoint }) {
  return (
    <article className="rounded-lg border border-ink-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-sm font-semibold text-ink-800">{point.headline}</h3>
        <Pill tone="info">not advice</Pill>
      </div>
      <p className="mt-1 text-sm text-ink-600">{point.body}</p>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <AlignmentChip point={point} />
      </div>

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
