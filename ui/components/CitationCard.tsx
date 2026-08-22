/** Renders a single Citation with its source type and a link when present. */

import type { Citation } from "@/lib/types";

export function CitationCard({ citation }: { citation: Citation }) {
  const page = citation.page != null ? ` p.${citation.page}` : "";
  return (
    <li className="rounded-md border border-ink-100 bg-ink-50 px-3 py-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-ink-600">
          [{citation.source_id}
          {page}]
        </span>
        <span className="rounded bg-regblue-100 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-regblue-700">
          {citation.source_type === "house_view" ? "house view" : "portfolio"}
        </span>
      </div>
      <p className="mt-1 text-ink-700">{citation.title}</p>
      {citation.snippet && (
        <p className="mt-1 italic text-ink-400">{citation.snippet}</p>
      )}
      {citation.url && (
        <a
          href={citation.url}
          target="_blank"
          rel="noreferrer"
          className="mt-1 inline-block text-regblue-600 hover:underline"
        >
          {citation.url}
        </a>
      )}
    </li>
  );
}

export function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations.length) {
    return <p className="text-xs text-ink-400">(no citations)</p>;
  }
  return (
    <ul className="mt-2 space-y-2">
      {citations.map((c, i) => (
        <CitationCard key={`${c.source_id}-${i}`} citation={c} />
      ))}
    </ul>
  );
}
