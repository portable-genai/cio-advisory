/**
 * How the client's portfolio lines up with the current CIO house views.
 *
 * One row per theme, saying what that theme is to this portfolio and which of the client's
 * holdings it touches. It replaces three columns of bare theme names, which could say that a
 * theme was a "gap" but never how large a gap, in what, or worth how much.
 *
 * The last block is the honest one: the asset classes this client is short of that today's
 * report says nothing about. Naming them is how the briefing declines to invent a theme
 * rather than quietly omitting the gap.
 */

import type { PortfolioAlignment, ThemeSignal } from "@/lib/types";
import { ASSET_CLASS_LABEL } from "@/lib/types";
import { Empty } from "./ui";

const SIGNAL_TONE: Record<ThemeSignal, string> = {
  opportunity: "bg-emerald-100 text-emerald-800",
  threat: "bg-amber-100 text-amber-800",
  watch: "bg-ink-100 text-ink-600",
};

export function AlignmentPanel({ alignment }: { alignment?: PortfolioAlignment }) {
  if (!alignment) return <Empty>No alignment computed.</Empty>;
  const links = alignment.theme_links ?? [];

  if (links.length === 0) {
    // A briefing built with no model portfolio published: the names are all there is.
    return (
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {(
          [
            ["In line", alignment.themes_in_line, "text-emerald-700"],
            ["Gaps", alignment.gaps, "text-regblue-700"],
            ["Overweights", alignment.overweights, "text-amber-700"],
          ] as const
        ).map(([title, items, tone]) => (
          <div key={title}>
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
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[32rem] border-collapse">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-ink-500">
              <th className="pb-1 pr-3 font-semibold">Theme</th>
              <th className="pb-1 pr-3 font-semibold">Signal</th>
              <th className="pb-1 pr-3 font-semibold">For this portfolio</th>
              <th className="pb-1 font-semibold">Touches</th>
            </tr>
          </thead>
          <tbody>
            {links.map((link) => {
              const gap = link.addresses ?? link.exposure;
              return (
                <tr key={link.theme} className="border-t border-ink-100 align-top">
                  <td className="py-2 pr-3 text-sm text-ink-800">{link.theme}</td>
                  <td className="py-2 pr-3">
                    <span
                      className={`rounded px-1.5 py-0.5 text-[11px] font-medium ${SIGNAL_TONE[link.signal]}`}
                    >
                      {link.signal}
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-xs">
                    {link.addresses ? (
                      <span className="text-regblue-800">
                        Closes {Math.round(Math.abs(link.addresses.drift) * 100)} points in{" "}
                        {ASSET_CLASS_LABEL[link.addresses.asset_class]}
                      </span>
                    ) : link.exposure ? (
                      <span className="text-amber-800">
                        {Math.round(link.exposure.current_weight * 100)}% held in{" "}
                        {ASSET_CLASS_LABEL[link.exposure.asset_class]}
                      </span>
                    ) : (
                      <span className="text-ink-400">In range, nothing to close</span>
                    )}
                    {gap && gap.status === "over" ? (
                      <span className="ml-1 text-amber-700">(above band)</span>
                    ) : null}
                  </td>
                  <td className="py-2 text-xs text-ink-600">
                    {link.related_holdings.length > 0 ? (
                      link.related_holdings.join(", ")
                    ) : (
                      <span className="text-ink-300">nothing held</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {alignment.uncovered_gaps.length > 0 ? (
        <p className="rounded-lg bg-ink-50 p-2 text-xs text-ink-600">
          <span className="font-medium text-ink-800">Not covered by this report: </span>
          the portfolio is short of{" "}
          {alignment.uncovered_gaps
            .map((c) => ASSET_CLASS_LABEL[c as keyof typeof ASSET_CLASS_LABEL] ?? c)
            .join(", ")}
          , and today&apos;s house views offer nothing that addresses it.
        </p>
      ) : null}
    </div>
  );
}
