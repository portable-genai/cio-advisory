/**
 * TypeScript mirrors of the B3 domain dataclasses.
 *
 * Source of truth: `src/cio_advisory/domain/models.py`.
 * The backend serialises dataclasses with `domain/serialization.to_jsonable` (SPEC §5):
 * dataclass field names are preserved (snake_case) and every enum is rendered as its
 * `.value` string. These types follow that contract exactly.
 *
 * B3 is decision-support, NOT financial advice. Every talking point is `is_advice: false`
 * and every briefing carries a non-advice disclaimer and `requires_human_review`.
 */

// --------------------------------------------------------------------------- //
// Suitability taxonomy
// --------------------------------------------------------------------------- //
export type RiskAppetite = "conservative" | "balanced" | "aggressive";

export type AssetClass =
  | "equity"
  | "fixed_income"
  | "cash"
  | "alternatives"
  | "real_assets"
  | "multi_asset";

export type Stance = "overweight" | "neutral" | "underweight";

export type SuitabilityVerdict = "suitable" | "review" | "unsuitable";

export type SourceType = "house_view" | "portfolio";

export const VERDICT_LABEL: Record<SuitabilityVerdict, string> = {
  suitable: "Suitable",
  review: "Review",
  unsuitable: "Unsuitable",
};

// --------------------------------------------------------------------------- //
// Citation
// --------------------------------------------------------------------------- //
export interface Citation {
  source_id: string;
  source_type: SourceType;
  title: string;
  url: string;
  page: number | null;
  snippet: string;
  score: number | null;
}

// --------------------------------------------------------------------------- //
// Suitability
// --------------------------------------------------------------------------- //
export interface SuitabilityFactor {
  name: string;
  weight: number;
  present: boolean;
  detail: string;
}

export interface SuitabilityAssessment {
  theme: string;
  verdict: SuitabilityVerdict;
  factors: SuitabilityFactor[];
  rationale: string;
  citations: Citation[];
}

// --------------------------------------------------------------------------- //
// Artifacts
// --------------------------------------------------------------------------- //
export interface TalkingPoint {
  headline: string;
  body: string;
  house_view_theme: string;
  linked_holdings: string[];
  suitability: SuitabilityAssessment | null;
  citations: Citation[];
  is_advice: boolean;
}

export interface PortfolioAlignment {
  themes_in_line: string[];
  gaps: string[];
  overweights: string[];
}

export interface AdvisoryBriefing {
  client_id: string;
  talking_points: TalkingPoint[];
  alignment: PortfolioAlignment;
  not_advice_disclaimer: string;
  requires_human_review: boolean;
  generated_at: string;
}

export interface TalkingPointsResponse {
  client_id: string;
  talking_points: TalkingPoint[];
  not_advice_disclaimer: string;
  requires_human_review: boolean;
}

// --------------------------------------------------------------------------- //
// Health
// --------------------------------------------------------------------------- //
export interface HealthResponse {
  status: string;
  profile: string;
  region: string;
}

export type ArtifactKind = "briefing" | "talking_points" | "suitability";
