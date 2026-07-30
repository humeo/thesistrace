CREATE TABLE IF NOT EXISTS thesistrace_control.release_bootstrap (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    release_version text NOT NULL,
    bootstrapped_at timestamptz NOT NULL DEFAULT now()
);
