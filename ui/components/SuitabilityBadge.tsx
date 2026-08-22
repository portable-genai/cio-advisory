/** A coloured badge plus rationale for a SuitabilityAssessment verdict. */

import type { SuitabilityAssessment } from "@/lib/types";
import { VERDICT_LABEL } from "@/lib/types";
import { Pill } from "./ui";

export function SuitabilityBadge({
  assessment,
}: {
  assessment: SuitabilityAssessment | null;
}) {
  if (!assessment) return null;
  const tone =
    assessment.verdict === "suitable"
      ? "good"
      : assessment.verdict === "review"
        ? "warn"
        : "bad";
  return (
    <div className="mt-2">
      <Pill tone={tone}>{VERDICT_LABEL[assessment.verdict]}</Pill>
      {assessment.rationale && (
        <p className="mt-1 text-xs text-ink-500">{assessment.rationale}</p>
      )}
      {assessment.factors.length > 0 && (
        <ul className="mt-1 flex flex-wrap gap-1">
          {assessment.factors.map((f) => (
            <li
              key={f.name}
              className={`rounded px-1.5 py-0.5 text-[10px] ${
                f.present ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"
              }`}
              title={f.detail}
            >
              {f.name}
              {f.present ? " ok" : " flag"}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
