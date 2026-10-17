ALTER TABLE research_runs.run_ownership
ADD COLUMN quota_started boolean DEFAULT false NOT NULL,
ADD COLUMN quota_state text DEFAULT 'reserved' NOT NULL CHECK (quota_state IN ('reserved','consumed','released'));
ALTER TABLE daily_tracks.tracks ADD COLUMN quota_selected boolean DEFAULT true NOT NULL;
UPDATE research_runs.run_ownership AS ownership SET
quota_started = run.id IS NULL OR run.status IN ('running','cancelling','succeeded') OR EXISTS (SELECT 1 FROM research_runs.attempts WHERE run_id=ownership.run_id),
quota_state = CASE
WHEN run.status='failed' THEN 'released'
WHEN run.status='cancelled' AND NOT EXISTS (SELECT 1 FROM research_runs.attempts WHERE run_id=ownership.run_id) THEN 'released'
WHEN run.id IS NULL OR run.status IN ('cancelled','succeeded') THEN 'consumed'
ELSE 'reserved' END
FROM (SELECT o.run_id, r.id, r.status FROM research_runs.run_ownership o LEFT JOIN research_runs.runs r ON r.id=o.run_id) AS run
WHERE ownership.run_id=run.run_id;
CREATE FUNCTION research_runs.settle_run_quota() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    UPDATE research_runs.run_ownership SET
        quota_started = quota_started OR NEW.status IN ('running','cancelling','succeeded'),
        quota_state = CASE
            WHEN NEW.status = 'failed' THEN 'released'
            WHEN NEW.status = 'cancelled' THEN
                CASE WHEN quota_started THEN 'consumed' ELSE 'released' END
            WHEN NEW.status = 'succeeded' THEN 'consumed'
            ELSE 'reserved'
        END
    WHERE run_id = NEW.id AND researcher_id = NEW.researcher_id;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION research_runs.settle_run_quota() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION research_runs.settle_run_quota() TO core_runtime;
CREATE TRIGGER settle_run_quota AFTER INSERT OR UPDATE OF status ON research_runs.runs
FOR EACH ROW EXECUTE FUNCTION research_runs.settle_run_quota();
