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

/** What a CIO theme is to a portfolio. Derived from the stance by the server, never here. */
export type ThemeSignal = "opportunity" | "threat" | "watch";

/** Where one asset class sits against the model portfolio's published band. */
export type GapStatus = "under" | "in_range" | "over";

export const SIGNAL_LABEL: Record<ThemeSignal, string> = {
  opportunity: "Opportunity",
  threat: "Threat",
  watch: "Watch",
};

export const GAP_STATUS_LABEL: Record<GapStatus, string> = {
  under: "Under",
  in_range: "In range",
  over: "Over",
};

export const ASSET_CLASS_LABEL: Record<AssetClass, string> = {
  equity: "Equity",
  fixed_income: "Fixed income",
  cash: "Cash",
  alternatives: "Alternatives",
  real_assets: "Real assets",
  multi_asset: "Multi-asset",
};

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
  alignment: ThemeAlignment | null;
}

/**
 * One asset class against its band. Every figure here is computed server-side, including
 * `drift` and `value_gap`: the console renders them and never recomputes them, so the number
 * on screen is the number the engine used and a reviewer replays one calculation, not two.
 */
export interface AllocationGap {
  asset_class: AssetClass;
  current_weight: number;
  target_weight: number;
  min_weight: number;
  max_weight: number;
  status: GapStatus;
  current_value: number;
  total_value: number;
  drift: number;
  value_gap: number;
}

export interface AllocationTarget {
  asset_class: AssetClass;
  target_weight: number;
  min_weight: number;
  max_weight: number;
}

export interface ModelPortfolio {
  model_id: string;
  risk_appetite: RiskAppetite;
  jurisdiction: string;
  effective_from: string;
  source: string;
  targets: AllocationTarget[];
}

export interface HoldingOut {
  instrument: string;
  instrument_id: string;
  asset_class: AssetClass;
  value: number;
  weight: number;
  currency: string;
  tags: string[];
}

export interface PortfolioSummary {
  client_id: string;
  risk_appetite: RiskAppetite;
  total_value: number;
  currency: string;
  holdings: HoldingOut[];
  allocation_gaps: AllocationGap[];
  model_portfolio: ModelPortfolio | null;
}

export interface ThemeAlignment {
  theme: string;
  signal: ThemeSignal;
  asset_class: AssetClass;
  status: GapStatus;
  addresses: AllocationGap | null;
  exposure: AllocationGap | null;
  related_holdings: string[];
  citation: Citation | null;
}

export interface PortfolioAlignment {
  themes_in_line: string[];
  gaps: string[];
  overweights: string[];
  theme_links: ThemeAlignment[];
  allocation_gaps: AllocationGap[];
  uncovered_gaps: string[];
}

export interface AdvisoryBriefing {
  client_id: string;
  talking_points: TalkingPoint[];
  alignment: PortfolioAlignment;
  portfolio_summary: PortfolioSummary | null;
  house_views_considered: ThemeAlignment[];
  not_advice_disclaimer: string;
  requires_human_review: boolean;
  generated_at: string;
}

/** One client in the picker. The label is derived server-side from the profile. */
export interface ClientSummary {
  client_id: string;
  label: string;
  risk_appetite: RiskAppetite | "";
}

export interface ClientList {
  clients: string[];
  items: ClientSummary[];
  book_version: string;
  fictional: boolean;
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
  // Provenance the banner states on every page: where the runtime sits and which model
  // answers. Both come from the service; nothing in the console infers either.
  runtime: string;
  generator_model: string;
  region: string;
}

export type ArtifactKind = "briefing" | "talking_points" | "suitability";
