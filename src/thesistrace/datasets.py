import hashlib
import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from thesistrace.canonical_objects import (
    CanonicalObjectError,
    canonical_schema_entries,
    materialize_partitioned_canonical,
    materialize_partitioned_canonical_tail,
    materialize_partitioned_canonical_window,
    partitioned_liquidity_universe_membership,
    partitioned_research_calendar_neighborhood,
    partitioned_research_calendar_range,
    partitioned_research_calendar_window,
    update_canonical_partitions,
    write_full_canonical,
)
from thesistrace.fixture import (
    adjustment_factor,
    build_fixture,
    decimal_string,
    liquidity_universes,
    price_rows,
)
from thesistrace.objects import canonical_json_bytes
from thesistrace.ports import ControlMetadataPort, ObjectStorePort
from thesistrace.storage_admission import publication_storage_objects


class InvalidFixtureError(ValueError):
    pass


class DatasetPublisher:
    def __init__(
        self,
        metadata: ControlMetadataPort,
        objects: ObjectStorePort,
        *,
        release_committer: Callable[
            [dict[str, object], str],
            tuple[dict[str, object], bool],
        ]
        | None = None,
    ) -> None:
        self.metadata = metadata
        self.objects = objects
        self.release_committer = release_committer

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
        if self.release_committer is not None:
            return self._bootstrap_documents(
                idempotency_key,
                source=source,
                canonical=canonical,
                source_kind=source_kind,
                source_schema=source_schema,
            )
        with self.metadata.storage_mutation_fence():
            return self._bootstrap_documents(
                idempotency_key,
                source=source,
                canonical=canonical,
                source_kind=source_kind,
                source_schema=source_schema,
            )

    def _bootstrap_documents(
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
        object_entries = [
            {"kind": source_kind, **source_object},
            *write_full_canonical(self.objects, canonical),
        ]
        manifest_core: dict[str, object] = {
            "predecessor_id": None,
            "created_at": datetime.now(UTC).isoformat(),
            "appended_session_range": {"start": sessions[0], "end": sessions[-1]},
            "session_count": len(sessions),
            "instrument_count": len(instruments),
            "correction_change_set": [],
            "canonical_schema_version": canonical.get(
                "schema_version",
                "canonical-eod-v1",
            ),
            "canonical_tables": sorted(
                key for key in canonical if key != "schema_version"
            ),
            "schemas": [
                {"family": source_kind, "version": source_schema},
                *canonical_schema_entries(),
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
        return self._commit_release(release, idempotency_key)

    def data_contract(self, release: dict[str, object]) -> dict[str, object]:
        canonical = self.materialize_canonical(release)
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

    def publish_fixture_increment(
        self,
        idempotency_key: str,
        *,
        new_sessions: int,
        corrections: list[dict[str, str]],
    ) -> tuple[dict[str, object], bool]:
        if self.release_committer is not None:
            return self._publish_fixture_increment(
                idempotency_key,
                new_sessions=new_sessions,
                corrections=corrections,
            )
        with self.metadata.storage_mutation_fence():
            return self._publish_fixture_increment(
                idempotency_key,
                new_sessions=new_sessions,
                corrections=corrections,
            )

    def _publish_fixture_increment(
        self,
        idempotency_key: str,
        *,
        new_sessions: int,
        corrections: list[dict[str, str]],
    ) -> tuple[dict[str, object], bool]:
        existing = self.metadata.dataset_release_for_idempotency_key(idempotency_key)
        if existing is not None:
            return existing, False
        predecessor = self.metadata.latest_dataset_release()
        if predecessor is None:
            raise InvalidFixtureError("bootstrap must be published first")
        if new_sessions < 1:
            raise InvalidFixtureError("incremental publication requires at least one new session")
        if new_sessions > 20:
            raise InvalidFixtureError("fixture catch-up is limited to 20 sessions per request")

        canonical = self.materialize_canonical(predecessor)
        calendar = canonical["research_calendar"]
        instruments = canonical["instruments"]
        prices = canonical["prices"]
        states = canonical["trading_states"]
        anchors = {
            str(item["instrument_id"]): Decimal(str(item["anchor_factor"]))
            for item in canonical["adjustment_anchors"]
        }
        if not all(isinstance(value, list) for value in (calendar, instruments, prices, states)):
            raise InvalidFixtureError("predecessor canonical data is incomplete")

        corrected_prices = [dict(row) for row in prices if isinstance(row, dict)]
        price_by_position = {
            (str(row["session"]), str(row["instrument_id"])): row for row in corrected_prices
        }
        allowed_correction_fields = {
            "open_raw",
            "high_raw",
            "low_raw",
            "close_raw",
            "pre_close_raw",
            "volume_shares",
            "turnover_cny",
        }
        canonical_corrections: list[dict[str, str]] = []
        corrected_positions: set[tuple[str, str]] = set()
        for correction in corrections:
            position = (correction["session"], correction["instrument_id"])
            target = price_by_position.get(position)
            if target is None or correction["field"] not in allowed_correction_fields:
                raise InvalidFixtureError("correction target is not a source canonical field")
            value = Decimal(correction["value"])
            if not value.is_finite():
                raise InvalidFixtureError("correction value must be finite")
            if value < 0:
                raise InvalidFixtureError("correction value must be non-negative")
            field = correction["field"]
            places = 0 if field == "volume_shares" else 2 if field == "turnover_cny" else 4
            normalized_value = decimal_string(value, places)
            target[field] = normalized_value
            corrected_positions.add(position)
            canonical_corrections.append({**correction, "value": normalized_value})

            if field in {"open_raw", "high_raw", "low_raw", "close_raw"}:
                scale = Decimal(str(target["adjustment_factor"])) / Decimal(
                    str(target["adjustment_anchor_factor"])
                )
                adjusted_field = field.removesuffix("_raw") + "_adj"
                adjusted_value = decimal_string(value * scale, 8)
                target[adjusted_field] = adjusted_value
                canonical_corrections.append(
                    {
                        "session": correction["session"],
                        "instrument_id": correction["instrument_id"],
                        "field": adjusted_field,
                        "value": adjusted_value,
                    }
                )
            if field in {"close_raw", "pre_close_raw"}:
                close = Decimal(str(target["close_raw"]))
                pre_close = Decimal(str(target["pre_close_raw"]))
                if pre_close == 0:
                    raise InvalidFixtureError("pre_close_raw must be non-zero")
                change = decimal_string(close - pre_close, 4)
                pct_change = decimal_string((close - pre_close) / pre_close * 100, 6)
                target["change_raw"] = change
                target["pct_change_raw"] = pct_change
                canonical_corrections.extend(
                    [
                        {
                            "session": correction["session"],
                            "instrument_id": correction["instrument_id"],
                            "field": "change_raw",
                            "value": change,
                        },
                        {
                            "session": correction["session"],
                            "instrument_id": correction["instrument_id"],
                            "field": "pct_change_raw",
                            "value": pct_change,
                        },
                    ]
                )
        for position in corrected_positions:
            target = price_by_position[position]
            open_price = Decimal(str(target["open_raw"]))
            high = Decimal(str(target["high_raw"]))
            low = Decimal(str(target["low_raw"]))
            close = Decimal(str(target["close_raw"]))
            pre_close = Decimal(str(target["pre_close_raw"]))
            volume = Decimal(str(target["volume_shares"]))
            turnover = Decimal(str(target["turnover_cny"]))
            if (
                min(open_price, close) < low
                or max(open_price, close) > high
                or low > high
                or min(open_price, high, low, close, pre_close) <= 0
                or volume < 0
                or turnover < 0
            ):
                raise InvalidFixtureError("correction produces an invalid canonical price row")

        appended_sessions = next_business_sessions(str(calendar[-1]), new_sessions)
        source_daily: list[dict[str, str]] = []
        source_adjustments: list[dict[str, str]] = []
        appended_prices: list[dict[str, str]] = []
        appended_states: list[dict[str, str]] = []
        appended_limits: list[dict[str, str]] = []
        for offset, session in enumerate(appended_sessions):
            session_index = len(calendar) + offset
            factor = adjustment_factor(session_index)
            for instrument_index, instrument_value in enumerate(instruments):
                if not isinstance(instrument_value, dict):
                    raise InvalidFixtureError("invalid instrument reference")
                instrument = {str(key): str(value) for key, value in instrument_value.items()}
                instrument_id = instrument["instrument_id"]
                anchor = anchors.get(instrument_id)
                if anchor is None:
                    raise InvalidFixtureError("missing adjustment anchor")
                source_row, canonical_row = price_rows(
                    session=session,
                    session_index=session_index,
                    instrument=instrument,
                    instrument_index=instrument_index,
                    factor=factor,
                    anchor_factor=anchor,
                    state="normal",
                )
                source_daily.append(source_row)
                source_adjustments.append(
                    {
                        "trade_date": session,
                        "ts_code": instrument["ts_code"],
                        "adj_factor": decimal_string(factor, 6),
                    }
                )
                appended_prices.append(canonical_row)
                appended_states.append(
                    {
                        "session": session,
                        "instrument_id": instrument_id,
                        "state": "normal",
                    }
                )
                appended_limits.append(
                    {
                        "session": session,
                        "instrument_id": instrument_id,
                        "upper": decimal_string(
                            Decimal(source_row["pre_close"]) * Decimal("1.10"), 4
                        ),
                        "lower": decimal_string(
                            Decimal(source_row["pre_close"]) * Decimal("0.90"), 4
                        ),
                    }
                )

        all_sessions = [*calendar, *appended_sessions]
        all_prices = [*corrected_prices, *appended_prices]
        all_states = [*states, *appended_states]
        all_universes = liquidity_universes(
            all_sessions,
            instruments,
            all_prices,
            all_states,
        )
        source_delta = {
            "source": "deterministic-fixture",
            "sessions": appended_sessions,
            "daily": source_daily,
            "adjustments": source_adjustments,
            "corrections": corrections,
        }
        universe_replacements: dict[str, list[dict[str, object]]] = {}
        turnover_correction_sessions = [
            correction["session"]
            for correction in corrections
            if correction["field"] == "turnover_cny"
        ]
        if turnover_correction_sessions:
            replacement_start = min(turnover_correction_sessions)
            universe_replacements = {
                name: [
                    snapshot
                    for snapshot in snapshots
                    if str(snapshot["session"]) >= replacement_start
                ]
                for name, snapshots in all_universes.items()
            }
        canonical_delta = {
            "research_calendar_append": appended_sessions,
            "prices_append": appended_prices,
            "trading_states_append": appended_states,
            "price_limits_append": appended_limits,
            "base_pool_append": [
                {
                    "session": session,
                    "instrument_ids": [item["instrument_id"] for item in instruments],
                }
                for session in appended_sessions
            ],
            "liquidity_universes_append": {
                name: snapshots[-new_sessions:] for name, snapshots in all_universes.items()
            },
            "liquidity_universes_replace": universe_replacements,
            "price_corrections": canonical_corrections,
        }
        materialized = json.loads(
            json.dumps(canonical, ensure_ascii=False, allow_nan=False)
        )
        apply_canonical_delta(materialized, canonical_delta)
        source_object = self.objects.put_json(source_delta)
        predecessor_objects = predecessor.get("objects")
        if not isinstance(predecessor_objects, list):
            raise InvalidFixtureError("predecessor object manifest is invalid")
        canonical_entries = update_canonical_partitions(
            self.objects,
            canonical_partition_entries(predecessor_objects),
            materialized,
            canonical_delta,
        )
        objects = [
            *noncanonical_object_entries(predecessor_objects),
            {"kind": "source_delta", **source_object},
            *canonical_entries,
        ]
        manifest_core: dict[str, object] = {
            "predecessor_id": predecessor["id"],
            "created_at": datetime.now(UTC).isoformat(),
            "appended_session_range": {
                "start": appended_sessions[0],
                "end": appended_sessions[-1],
            },
            "session_count": len(all_sessions),
            "instrument_count": len(instruments),
            "correction_change_set": corrections,
            "canonical_schema_version": materialized.get(
                "schema_version",
                "canonical-eod-v1",
            ),
            "canonical_tables": sorted(
                key for key in materialized if key != "schema_version"
            ),
            "schemas": schemas_with_canonical(predecessor["schemas"]),
            "objects": objects,
        }
        release_digest = hashlib.sha256(canonical_json_bytes(manifest_core)).hexdigest()
        release = {
            "id": f"dsr_{release_digest[:20]}",
            **manifest_core,
            "manifest_sha256": release_digest,
        }
        self.objects.put_manifest(str(release["id"]), release)
        return self._commit_release(release, idempotency_key)

    def publish_increment_documents(
        self,
        idempotency_key: str,
        *,
        source: dict[str, object],
        canonical_delta: dict[str, object],
        source_schema: str,
    ) -> tuple[dict[str, object], bool]:
        if self.release_committer is not None:
            return self._publish_increment_documents(
                idempotency_key,
                source=source,
                canonical_delta=canonical_delta,
                source_schema=source_schema,
            )
        with self.metadata.storage_mutation_fence():
            return self._publish_increment_documents(
                idempotency_key,
                source=source,
                canonical_delta=canonical_delta,
                source_schema=source_schema,
            )

    def _publish_increment_documents(
        self,
        idempotency_key: str,
        *,
        source: dict[str, object],
        canonical_delta: dict[str, object],
        source_schema: str,
    ) -> tuple[dict[str, object], bool]:
        existing = self.metadata.dataset_release_for_idempotency_key(idempotency_key)
        if existing is not None:
            return existing, False
        predecessor = self.metadata.latest_dataset_release()
        if predecessor is None:
            raise InvalidFixtureError("live Bootstrap must be published first")
        appended = canonical_delta.get("research_calendar_append")
        if not isinstance(appended, list) or not appended:
            raise InvalidFixtureError("incremental publication has no new Research Session")
        predecessor_range = predecessor.get("appended_session_range")
        prior_final_session = (
            str(predecessor_range.get("end"))
            if isinstance(predecessor_range, dict)
            else ""
        )
        if not prior_final_session or str(appended[0]) <= prior_final_session:
            raise InvalidFixtureError("incremental sessions do not follow the latest Release")
        instruments = canonical_delta.get("instruments_replace")
        if not isinstance(instruments, list):
            raise InvalidFixtureError("incremental canonical data is incomplete")

        source_object = self.objects.put_json(source)
        predecessor_objects = predecessor.get("objects")
        if not isinstance(predecessor_objects, list):
            raise InvalidFixtureError("predecessor object manifest is invalid")
        corrections = canonical_delta.get("price_corrections", [])
        universe_replacements = canonical_delta.get(
            "liquidity_universes_replace",
            {},
        )
        if corrections or universe_replacements:
            raise InvalidFixtureError(
                "live incremental publication does not accept historical replacements"
            )
        canonical_entries = update_canonical_partitions(
            self.objects,
            canonical_partition_entries(predecessor_objects),
            {
                "instruments": instruments,
                "industry_membership": canonical_delta.get(
                    "industry_membership_replace",
                    [],
                ),
            },
            canonical_delta,
        )
        objects = [
            *noncanonical_object_entries(predecessor_objects),
            {"kind": "source_tushare_delta", **source_object},
            *canonical_entries,
        ]
        corrections = source.get("corrections", [])
        predecessor_session_count = int(predecessor.get("session_count", 0))
        canonical_tables = predecessor.get("canonical_tables")
        if not isinstance(canonical_tables, list):
            raise InvalidFixtureError("predecessor Canonical table manifest is invalid")
        manifest_core: dict[str, object] = {
            "predecessor_id": predecessor["id"],
            "created_at": datetime.now(UTC).isoformat(),
            "appended_session_range": {
                "start": appended[0],
                "end": appended[-1],
            },
            "session_count": predecessor_session_count + len(appended),
            "instrument_count": len(instruments),
            "correction_change_set": corrections,
            "canonical_schema_version": predecessor.get(
                "canonical_schema_version",
                "canonical-eod-v1",
            ),
            "canonical_tables": sorted(str(key) for key in canonical_tables),
            "schemas": [
                *[
                    item
                    for item in schemas_with_canonical(predecessor["schemas"])
                    if item.get("family") != "source_tushare_delta"
                ],
                {"family": "source_tushare_delta", "version": source_schema},
            ],
            "objects": objects,
        }
        release_digest = hashlib.sha256(canonical_json_bytes(manifest_core)).hexdigest()
        release = {
            "id": f"dsr_{release_digest[:20]}",
            **manifest_core,
            "manifest_sha256": release_digest,
        }
        self.objects.put_manifest(str(release["id"]), release)
        return self._commit_release(release, idempotency_key)

    def _commit_release(
        self,
        release: dict[str, object],
        idempotency_key: str,
    ) -> tuple[dict[str, object], bool]:
        if self.release_committer is not None:
            return self.release_committer(release, idempotency_key)
        return self.metadata.publish_dataset_release_with_storage(
            release,
            idempotency_key,
            publication_storage_objects(release),
        )

    def materialize_canonical(self, release: dict[str, object]) -> dict[str, object]:
        objects = release.get("objects")
        if not isinstance(objects, list):
            raise InvalidFixtureError("release has no object manifest")
        partition_entries = canonical_partition_entries(objects)
        if partition_entries:
            try:
                return materialize_partitioned_canonical(
                    self.objects,
                    release,
                    partition_entries,
                )
            except CanonicalObjectError as error:
                raise InvalidFixtureError(str(error)) from error
        canonical: dict[str, object] | None = None
        seen: set[str] = set()
        for entry in objects:
            if not isinstance(entry, dict) or "sha256" not in entry:
                continue
            digest = str(entry["sha256"])
            if digest in seen:
                continue
            seen.add(digest)
            kind = entry.get("kind")
            if kind == "canonical_fixture":
                value = self.objects.read_json(digest)
                if not isinstance(value, dict):
                    raise InvalidFixtureError("canonical object is invalid")
                canonical = value
            elif kind == "canonical_delta":
                if canonical is None:
                    raise InvalidFixtureError("canonical delta has no root")
                value = self.objects.read_json(digest)
                if not isinstance(value, dict):
                    raise InvalidFixtureError("canonical delta is invalid")
                apply_canonical_delta(canonical, value)
        if canonical is None:
            raise InvalidFixtureError("release has no canonical object")
        return canonical

    def materialize_canonical_tail(
        self,
        release: dict[str, object],
        session_count: int,
    ) -> dict[str, object]:
        if session_count < 1:
            raise InvalidFixtureError(
                "Canonical tail must contain at least one session"
            )
        objects = release.get("objects")
        if not isinstance(objects, list):
            raise InvalidFixtureError("release has no object manifest")
        partition_entries = canonical_partition_entries(objects)
        if partition_entries:
            try:
                return materialize_partitioned_canonical_tail(
                    self.objects,
                    release,
                    partition_entries,
                    session_count,
                )
            except CanonicalObjectError as error:
                raise InvalidFixtureError(str(error)) from error
        canonical = self.materialize_canonical(release)
        calendar = canonical.get("research_calendar")
        if not isinstance(calendar, list) or not calendar:
            raise InvalidFixtureError("canonical Research Calendar is missing")
        first_session = str(calendar[max(0, len(calendar) - session_count)])
        return canonical_window(canonical, first_session, str(calendar[-1]))

    def materialize_canonical_window(
        self,
        release: dict[str, object],
        first_session: str,
        final_session: str,
    ) -> dict[str, object]:
        if first_session > final_session:
            raise InvalidFixtureError("Canonical window is reversed")
        objects = release.get("objects")
        if not isinstance(objects, list):
            raise InvalidFixtureError("release has no object manifest")
        partition_entries = canonical_partition_entries(objects)
        if partition_entries:
            try:
                return materialize_partitioned_canonical_window(
                    self.objects,
                    release,
                    partition_entries,
                    first_session=first_session,
                    final_session=final_session,
                )
            except CanonicalObjectError as error:
                raise InvalidFixtureError(str(error)) from error
        return canonical_window(
            self.materialize_canonical(release),
            first_session,
            final_session,
        )

    def research_calendar_window(
        self,
        release: dict[str, object],
        *,
        final_session: str,
        session_count: int,
    ) -> list[str]:
        if session_count < 1:
            raise InvalidFixtureError(
                "Research Calendar window must contain at least one session"
            )
        objects = release.get("objects")
        if not isinstance(objects, list):
            raise InvalidFixtureError("release has no object manifest")
        partition_entries = canonical_partition_entries(objects)
        if partition_entries:
            try:
                return partitioned_research_calendar_window(
                    self.objects,
                    partition_entries,
                    final_session=final_session,
                    session_count=session_count,
                )
            except CanonicalObjectError as error:
                raise InvalidFixtureError(str(error)) from error
        canonical = self.materialize_canonical(release)
        calendar = canonical.get("research_calendar")
        if not isinstance(calendar, list):
            raise InvalidFixtureError("canonical Research Calendar is missing")
        eligible = [
            str(session)
            for session in calendar
            if str(session) <= final_session
        ]
        return eligible[-session_count:]

    def research_calendar_neighborhood(
        self,
        release: dict[str, object],
        *,
        center_session: str,
        preceding_sessions: int,
        following_sessions: int,
    ) -> list[str]:
        objects = release.get("objects")
        if not isinstance(objects, list):
            raise InvalidFixtureError("release has no object manifest")
        partition_entries = canonical_partition_entries(objects)
        if partition_entries:
            try:
                return partitioned_research_calendar_neighborhood(
                    self.objects,
                    partition_entries,
                    center_session=center_session,
                    preceding_sessions=preceding_sessions,
                    following_sessions=following_sessions,
                )
            except CanonicalObjectError as error:
                raise InvalidFixtureError(str(error)) from error
        canonical = self.materialize_canonical(release)
        calendar = canonical.get("research_calendar")
        if not isinstance(calendar, list):
            raise InvalidFixtureError("canonical Research Calendar is missing")
        sessions = [str(session) for session in calendar]
        try:
            center_index = sessions.index(center_session)
        except ValueError as error:
            raise InvalidFixtureError(
                "Research Calendar neighborhood center is missing"
            ) from error
        return sessions[
            max(0, center_index - preceding_sessions) :
            center_index + following_sessions + 1
        ]

    def research_calendar_range(
        self,
        release: dict[str, object],
        *,
        after_session: str,
        through_session: str,
    ) -> list[str]:
        objects = release.get("objects")
        if not isinstance(objects, list):
            raise InvalidFixtureError("release has no object manifest")
        partition_entries = canonical_partition_entries(objects)
        if partition_entries:
            try:
                return partitioned_research_calendar_range(
                    self.objects,
                    partition_entries,
                    after_session=after_session,
                    through_session=through_session,
                )
            except CanonicalObjectError as error:
                raise InvalidFixtureError(str(error)) from error
        canonical = self.materialize_canonical(release)
        calendar = canonical.get("research_calendar")
        if not isinstance(calendar, list):
            raise InvalidFixtureError("canonical Research Calendar is missing")
        return [
            str(session)
            for session in calendar
            if after_session < str(session) <= through_session
        ]

    def liquidity_universe_membership(
        self,
        release: dict[str, object],
        *,
        universe_name: str,
        sessions: list[str],
    ) -> dict[str, set[str]]:
        objects = release.get("objects")
        if not isinstance(objects, list):
            raise InvalidFixtureError("release has no object manifest")
        partition_entries = canonical_partition_entries(objects)
        if partition_entries:
            try:
                return partitioned_liquidity_universe_membership(
                    self.objects,
                    partition_entries,
                    universe_name=universe_name,
                    sessions=sessions,
                )
            except CanonicalObjectError as error:
                raise InvalidFixtureError(str(error)) from error
        canonical = self.materialize_canonical(release)
        universes = canonical.get("liquidity_universes")
        selected = (
            universes.get(universe_name)
            if isinstance(universes, dict)
            else None
        )
        if not isinstance(selected, list):
            raise InvalidFixtureError("Canonical Liquidity Universe is missing")
        requested = set(sessions)
        return {
            str(snapshot["session"]): {
                str(instrument_id)
                for instrument_id in snapshot["instrument_ids"]
            }
            for snapshot in selected
            if isinstance(snapshot, dict)
            and str(snapshot.get("session")) in requested
        }


def canonical_partition_entries(
    entries: list[object],
) -> list[dict[str, object]]:
    return [
        dict(entry)
        for entry in entries
        if isinstance(entry, dict) and entry.get("kind") == "canonical_partition"
    ]


def canonical_window(
    canonical: dict[str, object],
    first_session: str,
    final_session: str,
) -> dict[str, object]:
    window = dict(canonical)
    calendar = canonical.get("research_calendar")
    if not isinstance(calendar, list):
        raise InvalidFixtureError("canonical Research Calendar is missing")
    selected = [
        str(session)
        for session in calendar
        if first_session <= str(session) <= final_session
    ]
    selected_set = set(selected)
    window["research_calendar"] = selected
    for key in (
        "prices",
        "trading_states",
        "price_limits",
        "base_pool",
        "st_designations",
        "adjustment_anchors",
    ):
        rows = canonical.get(key)
        if not isinstance(rows, list):
            continue
        coordinate = "trade_date" if key == "st_designations" else (
            "anchor_session" if key == "adjustment_anchors" else "session"
        )
        window[key] = [
            dict(row)
            for row in rows
            if isinstance(row, dict)
            and str(row.get(coordinate)) in selected_set
        ]
    universes = canonical.get("liquidity_universes")
    if isinstance(universes, dict):
        window["liquidity_universes"] = {
            str(name): [
                dict(row)
                for row in rows
                if isinstance(row, dict)
                and str(row.get("session")) in selected_set
            ]
            for name, rows in universes.items()
            if isinstance(rows, list)
        }
    return window


def noncanonical_object_entries(
    entries: list[object],
) -> list[dict[str, object]]:
    return [
        dict(entry)
        for entry in entries
        if isinstance(entry, dict)
        and entry.get("kind")
        not in {"canonical_partition", "canonical_fixture", "canonical_delta"}
    ]


def schemas_with_canonical(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise InvalidFixtureError("predecessor schema manifest is invalid")
    canonical_schemas = canonical_schema_entries()
    canonical_families = {
        schema["family"] for schema in canonical_schemas
    } | {"canonical_eod"}
    retained = [
        {"family": str(item["family"]), "version": str(item["version"])}
        for item in value
        if isinstance(item, dict)
        and "family" in item
        and "version" in item
        and str(item["family"]) not in canonical_families
    ]
    return [*retained, *canonical_schemas]


def apply_canonical_delta(canonical: dict[str, object], delta: dict[str, object]) -> None:
    append_mappings = {
        "research_calendar_append": "research_calendar",
        "prices_append": "prices",
        "trading_states_append": "trading_states",
        "price_limits_append": "price_limits",
        "base_pool_append": "base_pool",
        "adjustment_anchors_append": "adjustment_anchors",
        "st_designations_append": "st_designations",
    }
    for delta_key, canonical_key in append_mappings.items():
        addition = delta.get(delta_key, [])
        target = canonical.get(canonical_key)
        if target is None and canonical_key == "st_designations":
            canonical[canonical_key] = []
            target = canonical[canonical_key]
        if not isinstance(addition, list) or not isinstance(target, list):
            raise InvalidFixtureError("canonical delta append is invalid")
        target.extend(addition)
    instrument_replacement = delta.get("instruments_replace")
    if instrument_replacement is not None:
        if not isinstance(instrument_replacement, list):
            raise InvalidFixtureError("canonical instrument replacement is invalid")
        canonical["instruments"] = instrument_replacement
    industry_replacement = delta.get("industry_membership_replace")
    if industry_replacement is not None:
        if not isinstance(industry_replacement, list):
            raise InvalidFixtureError("canonical industry replacement is invalid")
        canonical["industry_membership"] = industry_replacement
    universe_additions = delta.get("liquidity_universes_append", {})
    universes = canonical.get("liquidity_universes")
    if not isinstance(universe_additions, dict) or not isinstance(universes, dict):
        raise InvalidFixtureError("canonical universe delta is invalid")
    for name, addition in universe_additions.items():
        target = universes.get(name)
        if not isinstance(target, list) or not isinstance(addition, list):
            raise InvalidFixtureError("canonical universe append is invalid")
        target.extend(addition)
    universe_replacements = delta.get("liquidity_universes_replace", {})
    if not isinstance(universe_replacements, dict):
        raise InvalidFixtureError("canonical universe replacement is invalid")
    for name, replacement in universe_replacements.items():
        target = universes.get(name)
        if not isinstance(target, list) or not isinstance(replacement, list):
            raise InvalidFixtureError("canonical universe replacement is invalid")
        replacement_by_session = {
            str(snapshot["session"]): snapshot
            for snapshot in replacement
            if isinstance(snapshot, dict) and "session" in snapshot
        }
        target[:] = [
            replacement_by_session.get(str(snapshot.get("session")), snapshot)
            if isinstance(snapshot, dict)
            else snapshot
            for snapshot in target
        ]
    corrections = delta.get("price_corrections", [])
    prices = canonical.get("prices")
    if not isinstance(corrections, list) or not isinstance(prices, list):
        raise InvalidFixtureError("canonical corrections are invalid")
    price_by_position = {
        (str(row["session"]), str(row["instrument_id"])): row
        for row in prices
        if isinstance(row, dict)
    }
    for correction in corrections:
        if not isinstance(correction, dict):
            raise InvalidFixtureError("canonical correction is invalid")
        target = price_by_position.get(
            (str(correction["session"]), str(correction["instrument_id"]))
        )
        if target is None:
            raise InvalidFixtureError("canonical correction target is missing")
        target[str(correction["field"])] = str(correction["value"])


def next_business_sessions(last_session: str, count: int) -> list[str]:
    current = datetime.fromisoformat(last_session).date()
    sessions: list[str] = []
    while len(sessions) < count:
        current = current.fromordinal(current.toordinal() + 1)
        if current.weekday() < 5:
            sessions.append(current.isoformat())
    return sessions
