ALTER TABLE agent.model_charge
ADD COLUMN run_id text,
ADD COLUMN settlement_state text DEFAULT 'reserved' NOT NULL CHECK (settlement_state IN ('reserved','settled','absorbed')),
ADD COLUMN finished_at timestamp with time zone;
UPDATE agent.model_charge SET settlement_state='settled',finished_at=created_at WHERE actual_nanodollars IS NOT NULL;
