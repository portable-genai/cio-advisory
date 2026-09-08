/**
 * Renders a full AdvisoryBriefing: the report and the points, WITHOUT the portfolio.
 *
 * The portfolio used to be rendered here, first, so a talking point was read after the
 * gaps it closes. It is now a peer stage above this one (`app/page.tsx`), which keeps that
 * reading order and stops the same table being on the page twice: once as the stage a
 * reader can reopen, and once inside the briefing. Two copies of the evidence is the
 * length problem the stage stack exists to solve, arriving from the other direction.
 */

import type { AdvisoryBriefing } from "@/lib/types";
import { AlignmentPanel } from "./AlignmentPanel";
import { CioViewsPanel } from "./CioViewsPanel";
import { TalkingPointView } from "./TalkingPointView";
import { Empty, NotAdviceBanner, Panel, Pill } from "./ui";

export function BriefingView({ briefing }: { briefing: AdvisoryBriefing }) {
  return (
    <div className="space-y-4">
      <NotAdviceBanner disclaimer={briefing.not_advice_disclaimer} />

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
