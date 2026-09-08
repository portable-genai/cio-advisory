/** Renders a full AdvisoryBriefing: the portfolio, the report, and the points between them. */

import type { AdvisoryBriefing } from "@/lib/types";
import { AlignmentPanel } from "./AlignmentPanel";
import { CioViewsPanel } from "./CioViewsPanel";
import { PortfolioSummaryPanel } from "./PortfolioSummaryPanel";
import { TalkingPointView } from "./TalkingPointView";
import { Empty, NotAdviceBanner, Panel, Pill } from "./ui";

export function BriefingView({ briefing }: { briefing: AdvisoryBriefing }) {
  return (
    <div className="space-y-4">
      <NotAdviceBanner disclaimer={briefing.not_advice_disclaimer} />

      {/* The portfolio comes first on purpose. A talking point read before the gaps is a
          theme; read after them it is a theme that closes a shortfall the reader has seen. */}
      {briefing.portfolio_summary ? (
        <Panel title="Portfolio against the client's risk profile">
          <PortfolioSummaryPanel summary={briefing.portfolio_summary} />
        </Panel>
      ) : null}

      {briefing.house_views_considered.length > 0 ? (
        <Panel title="CIO house view: opportunities and threats for this portfolio">
          <CioViewsPanel links={briefing.house_views_considered} />
        </Panel>
      ) : null}

      <Panel
        title={`Talking points (client ${briefing.client_id})`}
        right={
          briefing.requires_human_review ? (
            <Pill tone="warn">requires human review</Pill>
          ) : null
        }
      >
        {briefing.talking_points.length ? (
          <div className="space-y-3">
            {briefing.talking_points.map((p, i) => (
              <TalkingPointView key={`${p.house_view_theme}-${i}`} point={p} />
            ))}
          </div>
        ) : (
          <Empty>
            No suitable talking points for this client. Unsuitable themes are never
            presented as a recommendation.
          </Empty>
        )}
      </Panel>

      <Panel title="Theme by theme">
        <AlignmentPanel alignment={briefing.alignment} />
      </Panel>
    </div>
  );
}
