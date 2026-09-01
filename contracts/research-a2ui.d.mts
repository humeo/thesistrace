export const RESEARCH_A2UI_ACTIVITY_TYPE: "a2ui-surface";
export const RESEARCH_A2UI_CATALOG_ID: "urn:thesistrace:a2ui:research:v0.9";
export const RESEARCH_A2UI_PROTOCOL_VERSION: "v0.9";
export const RESEARCH_A2UI_MAX_BYTES: number;
export const RESEARCH_A2UI_MAX_COMPONENTS: number;
export const RESEARCH_A2UI_MAX_DEPTH: number;

export const RESEARCH_A2UI_INLINE_CATALOG: Readonly<{
  catalogId: typeof RESEARCH_A2UI_CATALOG_ID;
  components: Readonly<Record<string, Readonly<{
    additionalProperties: false;
    description: string;
    properties: Readonly<Record<string, Record<string, unknown>>>;
    required?: readonly string[];
    type: "object";
  }>>>;
}>;

export type ResearchA2UIProjection = Readonly<{
  content: Record<string, unknown>;
  kind: "error" | "loading" | "ready";
  valid: boolean;
}>;

export function safeResearchA2UIErrorContent(): Record<string, unknown>;
export function isResearchA2UIMessageId(value: unknown): value is string;
export function parseResearchA2UINavigationHref(value: unknown): string | null;
export function projectResearchA2UIContent(value: unknown): ResearchA2UIProjection;
