from thesistrace._postgres import Migration, MigrationPlan

CUTOVER_MIGRATIONS = MigrationPlan(
    schema="core_cutovers",
    ledger_table="schema_migrations",
    lock_name="thesistrace-core-cutover-migrations",
    migrations=(
        Migration(
            name="0001_move_start_tracking_receipts_to_research_runs",
            statement="""
                INSERT INTO research_runs.start_tracking_receipts (
                    request_id, request_fingerprint, seed_run_id,
                    track_id, outcome, created_at
                )
                SELECT
                    receipt.request_id,
                    receipt.request_fingerprint,
                    track.seed_run_id,
                    receipt.track_id,
                    receipt.outcome,
                    receipt.created_at
                FROM daily_tracks.activation_receipts AS receipt
                JOIN daily_tracks.tracks AS track
                    ON track.id = receipt.track_id;

                DELETE FROM daily_tracks.activation_receipts;
            """,
        ),
    ),
)
