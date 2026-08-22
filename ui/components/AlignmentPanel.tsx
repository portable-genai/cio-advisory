/** Shows how the client's portfolio lines up with the current CIO house views. */

import type { PortfolioAlignment } from "@/lib/types";
import { Empty } from "./ui";

function Column({ title, items, tone }: { title: string; items: string[]; tone: string }) {
  return (
    <div>
      <h4 className={`text-xs font-semibold uppercase tracking-wide ${tone}`}>{title}</h4>
      {items.length ? (
        <ul className="mt-1 space-y-1">
          {items.map((t) => (
            <li key={t} className="text-sm text-ink-700">
              {t}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-sm text-ink-400">none</p>
      )}
    </div>
  );
}

export function AlignmentPanel({ alignment }: { alignment?: PortfolioAlignment }) {
  if (!alignment) return <Empty>No alignment computed.</Empty>;
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
      <Column title="In line" items={alignment.themes_in_line} tone="text-emerald-700" />
      <Column title="Gaps" items={alignment.gaps} tone="text-regblue-700" />
      <Column title="Overweights" items={alignment.overweights} tone="text-amber-700" />
    </div>
  );
}
