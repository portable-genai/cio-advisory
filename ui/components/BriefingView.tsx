/** Renders a full AdvisoryBriefing: the not-advice banner, points, and alignment. */

import type { AdvisoryBriefing } from "@/lib/types";
import { AlignmentPanel } from "./AlignmentPanel";
import { TalkingPointView } from "./TalkingPointView";
import { Empty, NotAdviceBanner, Panel, Pill } from "./ui";

export function BriefingView({ briefing }: { briefing: AdvisoryBriefing }) {
  return (
    <div className="space-y-4">
      <NotAdviceBanner disclaimer={briefing.not_advice_disclaimer} />

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

      <Panel title="Portfolio alignment">
        <AlignmentPanel alignment={briefing.alignment} />
      </Panel>
    </div>
  );
}
