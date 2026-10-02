import type { z } from "zod";
export const RESEARCH_A2UI_ACTIVITY_TYPE: "a2ui-surface";
export const RESEARCH_A2UI_CATALOG_ID: "urn:thesistrace:a2ui:research:v0.9";
export const RESEARCH_A2UI_PROTOCOL_VERSION: "v0.9";
export const RESEARCH_A2UI_MAX_COMPONENTS: number;

export type AlphaProposal = {
  explanation: string; formula: string; hypothesis: string; period: string;
  researchType: string; strategy: { label: string; value: string }[];
  title: string; universe: string;
};
export type ResearchA2UIViewInput =
  | { view: "research_runs"; runIds: string[] }
  | { view: "alpha_proposal"; proposal: AlphaProposal }
  | { view: "daily_track"; trackId: string };
export function createResearchA2UIView(input: ResearchA2UIViewInput, surfaceId: string): Record<string, unknown>;
export const RESEARCH_A2UI_VIEW_SCHEMA: z.ZodType<ResearchA2UIViewInput>;
export const RESEARCH_A2UI_VIEW_JSON_SCHEMA: {
  type: "object"; additionalProperties: false; required: string[];
  properties: Record<string, Record<string, unknown>>;
};

type Definition<T> = { description: string; props: z.ZodObject<{ [K in keyof T]-?: z.ZodType<T[K]> }, "strict"> };
type LayoutProps = { children: string[]; gap?: "compact" | "normal" | "wide"; align?: "start" | "center" | "end" | "stretch" };
export const RESEARCH_A2UI_DEFINITIONS: {
  Text: Definition<{ text: string; variant?: "body" | "caption" | "label" | "title" }>;
  Row: Definition<LayoutProps>;
  Column: Definition<LayoutProps>;
  Divider: Definition<Record<never, never>>;
  Formula: Definition<{ expression: string; label?: string }>;
  AlphaProposal: Definition<AlphaProposal>;
  ResearchRun: Definition<{ runId: string }>;
  ResearchComparison: Definition<{ runIds: string[] }>;
  DailyTrack: Definition<{ trackId: string }>;
  Table: Definition<{ caption: string; columns: string[]; initiallyExpanded?: boolean; rows: string[][]; summary: string }>;
  Navigation: Definition<{ href: string; label: string }>;
};

export const RESEARCH_A2UI_INLINE_CATALOG: Readonly<{
  catalogId: typeof RESEARCH_A2UI_CATALOG_ID;
  components: Readonly<Record<string, Readonly<{
    additionalProperties: false;
    description: string;
    properties: Readonly<Record<string, Record<string, unknown>>>;
    required?: string[];
    type: "object";
  }>>>;
}>;

export type ResearchA2UIProjection = Readonly<{
  content: Record<string, unknown>;
  kind: "error" | "loading" | "ready";
  valid: boolean;
}>;

export function safeResearchA2UIErrorContent(errorCode?: string): Record<string, unknown>;
export function isResearchA2UIMessageId(value: unknown): value is string;
export function parseResearchA2UINavigationHref(value: unknown): string | null;
export function projectResearchA2UIContent(value: unknown): ResearchA2UIProjection;
