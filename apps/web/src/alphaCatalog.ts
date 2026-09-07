export type AlphaCatalogField = {
  identifier: string;
  field_id: string;
  value_type: "numeric_series";
  description: string;
  unit: string;
  family_id: string;
  availability: string;
  report_period_selection: string;
  applicable_company_types: string[];
  missingness: string;
  example: string;
};

export type AlphaCatalog = {
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
