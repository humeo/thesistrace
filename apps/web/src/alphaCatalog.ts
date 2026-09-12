export type AlphaCatalogField = {
  identifier: string;
  field_id: string;
  value_type: "numeric_series";
  description: string;
  unit: string;
  family_id: string;
  research_category: "market" | "financial";
  display_name: string;
  research_purpose: string;
  source_unit: string;
  source_endpoint: string;
  source_column: string;
  source_lineage: string;
  reporting_scope: string;
  availability: string;
  report_period_selection: string;
  applicable_company_types: string[];
  missingness: string;
  example: string;
};

export type AlphaCatalog = {
  generation_manifest_sha256: string | null;
  fields: AlphaCatalogField[];
  builtins: Array<{
    identifier: string;
    parameters: Array<{
      name: string;
      value_type: string;
      minimum: number | null;
      maximum: number | null;
    }>;
    result_type: string;
    description: string;
    examples: string[];
    missing_value_behavior: string;
    numeric_behavior: string;
  }>;
};
