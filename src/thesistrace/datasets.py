import hashlib
from collections import Counter
from datetime import UTC, datetime

from thesistrace.fixture import build_fixture
from thesistrace.objects import ImmutableObjectStore, canonical_json_bytes
from thesistrace.storage import MetadataStore


class InvalidFixtureError(ValueError):
    pass


class DatasetPublisher:
    def __init__(self, metadata: MetadataStore, objects: ImmutableObjectStore) -> None:
        self.metadata = metadata
        self.objects = objects

    def bootstrap(self, idempotency_key: str, fixture: str) -> tuple[dict[str, object], bool]:
        existing = self.metadata.dataset_release_for_idempotency_key(idempotency_key)
        if existing is not None:
            return existing, False
        if fixture != "v1":
            raise InvalidFixtureError("fixture must be v1")
        if self.metadata.latest_dataset_release() is not None:
            raise InvalidFixtureError("a bootstrap root already exists")

        source, canonical = build_fixture()
        return self.bootstrap_documents(
            idempotency_key,
            source=source,
            canonical=canonical,
            source_kind="source_fixture",
            source_schema="tushare-fixture-v1",
        )

    def bootstrap_documents(
        self,
        idempotency_key: str,
        *,
        source: dict[str, object],
        canonical: dict[str, object],
        source_kind: str,
        source_schema: str,
    ) -> tuple[dict[str, object], bool]:
        existing = self.metadata.dataset_release_for_idempotency_key(idempotency_key)
        if existing is not None:
            return existing, False
        if self.metadata.latest_dataset_release() is not None:
            raise InvalidFixtureError("a bootstrap root already exists")
        sessions = canonical["research_calendar"]
        instruments = canonical["instruments"]
        if not isinstance(sessions, list) or len(sessions) != 756:
            raise InvalidFixtureError("fixture must contain exactly 756 sessions")
        if not isinstance(instruments, list) or len(instruments) < 30:
            raise InvalidFixtureError("fixture must contain at least 30 instruments")

        source_object = self.objects.put_json(source)
        canonical_object = self.objects.put_json(canonical)
        object_entries = [
            {"kind": source_kind, **source_object},
            {"kind": "canonical_fixture", **canonical_object},
        ]
        manifest_core: dict[str, object] = {
            "predecessor_id": None,
            "created_at": datetime.now(UTC).isoformat(),
            "appended_session_range": {"start": sessions[0], "end": sessions[-1]},
            "session_count": len(sessions),
            "instrument_count": len(instruments),
            "correction_change_set": [],
            "schemas": [
                {"family": source_kind, "version": source_schema},
                {"family": "canonical_eod", "version": "canonical-eod-v1"},
            ],
            "objects": object_entries,
        }
        release_digest = hashlib.sha256(canonical_json_bytes(manifest_core)).hexdigest()
        release = {
            "id": f"dsr_{release_digest[:20]}",
            **manifest_core,
            "manifest_sha256": release_digest,
        }
        self.objects.put_manifest(str(release["id"]), release)
        self.metadata.publish_dataset_release(release, idempotency_key)
        return release, True

    def data_contract(self, release: dict[str, object]) -> dict[str, object]:
        objects = release.get("objects")
        if not isinstance(objects, list):
            raise InvalidFixtureError("release has no object manifest")
        canonical_entry = next(
            (
                item
                for item in objects
                if isinstance(item, dict) and item.get("kind") == "canonical_fixture"
            ),
            None,
        )
        if canonical_entry is None:
            raise InvalidFixtureError("release has no canonical object")
        canonical = self.objects.read_json(str(canonical_entry["sha256"]))
        if not isinstance(canonical, dict):
            raise InvalidFixtureError("canonical object is invalid")
        calendar = canonical["research_calendar"]
        states = canonical["trading_states"]
        fields = canonical["field_catalog"]
        universes = canonical["liquidity_universes"]
        if not all(
            isinstance(value, list) for value in (calendar, states, fields)
        ) or not isinstance(universes, dict):
            raise InvalidFixtureError("canonical object is incomplete")
        state_counts = Counter(
            str(item["state"]) for item in states if isinstance(item, dict) and "state" in item
        )
        return {
            "release_id": release["id"],
            "calendar": {
                "session_count": len(calendar),
                "start": calendar[0],
                "end": calendar[-1],
                "rule": "SSE_SZSE_OPEN_DAY_INTERSECTION",
            },
            "fields": fields,
            "alpha_authorable_fields": [
                str(item["name"])
                for item in fields
                if isinstance(item, dict) and item.get("alpha_authorable") is True
            ],
            "universes": sorted(universes),
            "industry_levels": ["SW2021_L1", "SW2021_L2", "SW2021_L3"],
            "trading_state_counts": dict(state_counts),
        }
