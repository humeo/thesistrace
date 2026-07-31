DROP TRIGGER reject_scheduled_work_during_maintenance
ON thesistrace_product.dataset_publications;

DROP FUNCTION thesistrace_control.reject_scheduled_work_during_maintenance();

CREATE FUNCTION thesistrace_control.reject_dataset_publication_during_maintenance()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, thesistrace_control
AS $$
BEGIN
    IF thesistrace_control.maintenance_enabled() THEN
        RAISE EXCEPTION 'new Dataset Publication is paused for maintenance';
    END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION
thesistrace_control.reject_dataset_publication_during_maintenance()
FROM PUBLIC, thesistrace_api, thesistrace_relay, thesistrace_data,
     thesistrace_compute, thesistrace_health;

CREATE TRIGGER reject_dataset_publication_during_maintenance
BEFORE INSERT ON thesistrace_product.dataset_publications
FOR EACH ROW EXECUTE FUNCTION
thesistrace_control.reject_dataset_publication_during_maintenance();
