ALTER TABLE thesistrace_product.execution_outbox
DROP CONSTRAINT execution_outbox_resource_kind_check;

ALTER TABLE thesistrace_product.execution_outbox
ADD CONSTRAINT execution_outbox_resource_kind_check
CHECK (resource_kind IN ('research_run', 'research_run_cancel'));
