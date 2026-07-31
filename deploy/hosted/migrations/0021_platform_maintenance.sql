CREATE TABLE thesistrace_control.platform_maintenance (
    singleton smallint PRIMARY KEY CHECK (singleton = 1),
    enabled boolean NOT NULL,
    changed_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO thesistrace_control.platform_maintenance (singleton, enabled)
VALUES (1, false);

REVOKE ALL ON thesistrace_control.platform_maintenance FROM PUBLIC;
REVOKE ALL ON thesistrace_control.platform_maintenance
FROM thesistrace_api, thesistrace_relay, thesistrace_data,
     thesistrace_compute, thesistrace_health;

CREATE FUNCTION thesistrace_control.maintenance_enabled()
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
    SELECT enabled
    FROM thesistrace_control.platform_maintenance
    WHERE singleton = 1
$$;

CREATE FUNCTION thesistrace_control.set_platform_maintenance(
    requested_enabled boolean
)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
    UPDATE thesistrace_control.platform_maintenance
    SET enabled = requested_enabled,
        changed_at = clock_timestamp()
    WHERE singleton = 1
$$;

REVOKE ALL ON FUNCTION thesistrace_control.maintenance_enabled() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION thesistrace_control.maintenance_enabled()
TO thesistrace_api, thesistrace_relay, thesistrace_data, thesistrace_health;

REVOKE ALL ON FUNCTION thesistrace_control.set_platform_maintenance(boolean)
FROM PUBLIC, thesistrace_api, thesistrace_relay, thesistrace_data,
     thesistrace_compute, thesistrace_health;

CREATE FUNCTION thesistrace_control.reject_scheduled_work_during_maintenance()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
BEGIN
    IF NEW.trigger_kind = 'schedule'
       AND thesistrace_control.maintenance_enabled()
    THEN
        RAISE EXCEPTION 'scheduled work is paused for maintenance';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION
thesistrace_control.reject_scheduled_work_during_maintenance()
FROM PUBLIC, thesistrace_api, thesistrace_relay, thesistrace_data,
     thesistrace_compute, thesistrace_health;

CREATE TRIGGER reject_scheduled_work_during_maintenance
BEFORE INSERT ON thesistrace_product.dataset_publications
FOR EACH ROW EXECUTE FUNCTION
thesistrace_control.reject_scheduled_work_during_maintenance();
