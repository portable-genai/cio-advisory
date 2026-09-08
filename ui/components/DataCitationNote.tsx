/**
 * The rows behind one figure, and the read they came from.
 *
 * A briefing already cites the DOCUMENTS behind its narrative, and a reader can open each
 * one. Every allocation figure beside it is arithmetic over a client's book instead, and
 * until now nothing on the page said so: `Equity 31%` looked exactly the same whether it
 * was summed from three positions or produced by a model. This is the same affordance
 * pointed at a table — which store answered, which rows, and as of when.
 *
 * It looks the rows up by `instrument_id` from the summary's `holdings` and never
 * recomputes the figure from them. That distinction is the whole point: the money on screen
 * stays the money the engine computed, and what this adds is the ability to see which
 * positions produced it. A total rendered here would be a second calculation that agrees
 * today and diverges the first time rounding changes.
 */

import type { DataCitation, HoldingOut } from "@/lib/types";

/** `store` as a reader-facing name. An unknown store is shown verbatim, never relabelled. */
const STORE_LABEL: Record<string, string> = {
  duckdb: "DuckDB (on this laptop)",
  bigquery: "BigQuery",
  "in-process": "in-process",
};

export function storeLabel(store: string): string {
  return STORE_LABEL[store] ?? store;
}

/**
 * The one-line provenance stamp: what answered, how many rows, as of when.
 *
 * The single most load-bearing sentence in a data demo, and it costs one query. Rendered
 * as text rather than a badge because it is meant to be read, not noticed.
 */
export function ProvenanceLine({ cite }: { cite: DataCitation | null }) {
  if (!cite) return null;
  const rows = `${cite.row_count} ${cite.row_count === 1 ? "row" : "rows"}`;
  return (
    <p className="text-xs text-ink-500">
      Computed from {rows} in{" "}
      <code className="rounded bg-ink-50 px-1 py-0.5 text-ink-600">
        {cite.dataset}.{cite.table}
      </code>{" "}
      via {storeLabel(cite.store)}
      {cite.as_of ? `, as of ${cite.as_of}` : ", date not stated by the store"}.
    </p>
  );
}

export function DataCitationNote({
  cite,
  contributors,
  holdings,
  currency,
}: {
  cite: DataCitation | null;
  contributors: string[];
  holdings: HoldingOut[];
  currency: string;
}) {
  if (!cite) return null;
  const byId = new Map(holdings.map((h) => [h.instrument_id, h]));
  // Only ids this client's book actually carries. An id with no row is dropped rather than
  // rendered as a blank line: the list is evidence, and a row that cannot be shown is not.
  const rows = contributors.map((id) => byId.get(id)).filter((h): h is HoldingOut => !!h);

  return (
    <details className="mt-2 text-xs">
      <summary className="cursor-pointer text-ink-500 hover:text-ink-700">
        {rows.length > 0
          ? `Show the ${rows.length} ${rows.length === 1 ? "position" : "positions"} behind this`
          : "Show the read behind this"}
      </summary>
      <div className="mt-2 space-y-2 rounded-lg bg-ink-50 p-3">
        <p className="font-mono text-[11px] leading-relaxed text-ink-600">
          {storeLabel(cite.store)} &middot; {cite.dataset}.{cite.table}
          <br />
          WHERE {cite.predicate}
        </p>
        {rows.length > 0 ? (
          <div className="overflow-x-auto">
          <table className="w-full min-w-[18rem] text-left">
            <thead className="text-ink-500">
              <tr>
                <th className="py-1 font-medium">Instrument</th>
                <th className="py-1 pl-3 text-right font-medium">Value</th>
                <th className="py-1 pl-3 text-right font-medium">Weight</th>
              </tr>
            </thead>
            <tbody className="text-ink-700">
              {rows.map((h) => (
                <tr key={h.instrument_id} className="border-t border-ink-200">
                  <td className="py-1">
                    {h.instrument}{" "}
                    <span className="text-ink-400">{h.instrument_id}</span>
                  </td>
                  <td className="whitespace-nowrap py-1 pl-3 text-right tabular-nums">
                    {h.value.toLocaleString(undefined, { maximumFractionDigits: 0 })}{" "}
                    {h.currency || currency}
                  </td>
                  <td className="whitespace-nowrap py-1 pl-3 text-right tabular-nums">
                    {(h.weight * 100).toFixed(1)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        ) : (
          // Not an error and not an empty table: a class the client holds nothing in is a
          // real, and often the most interesting, answer. Saying so beats rendering a
          // header row over nothing.
          <p className="text-ink-500">
            No positions in this class: the read returned {cite.row_count} rows.
          </p>
        )}
      </div>
    </details>
  );
}
