from datetime import UTC, datetime

from thesistrace.data.financial_collection import RawFinancialBatchStore
from thesistrace.data.financial_indicator_candidate import FinancialIndicatorCandidateStore
from thesistrace.data.financial_indicator_evidence import FinancialIndicatorObservationStore
from thesistrace.data.financial_indicator_series import FinancialIndicatorSeriesResolver
from thesistrace.data.financial_indicator_source import FINANCIAL_INDICATOR_SOURCE_FIELDS
from thesistrace.data.source import RawSourceResponse


def test_candidate_reopens_and_reads_selected_indicator_columns(tmp_path):
    source = {
        "ts_code": "000001.SZ",
        "ann_date": "20200420",
        "end_date": "20191231",
        "eps": 2.5,
        "roe": 15.0,
        "update_flag": "1",
    }
    evidence = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    receipt = evidence.save(
        RawSourceResponse(
            fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
            items=(tuple(source.get(f) for f in FINANCIAL_INDICATOR_SOURCE_FIELDS),),
        ),
        observed_at=datetime(2020, 5, 1, tzinfo=UTC),
    )
    store = FinancialIndicatorCandidateStore(tmp_path)
    from thesistrace.data.io_metrics import measure_data_io

    collection = _collection_evidence(tmp_path, receipt)
    args = dict(collection_evidence_sha256s=(collection,),
                instrument_ids={"000001.SZ": "stock-1"},
                sessions=("2020-04-20", "2020-04-21", "2020-05-04"))
    with measure_data_io() as coverage_io:
        assert store.available_sessions(**args) == args["sessions"]
    with measure_data_io() as build_io:
        digest = store.build(**args)
    # Build needs the same coverage evidence plus one observation for projection.
    assert build_io.raw_financial_batch_opens == coverage_io.raw_financial_batch_opens + 1

    with measure_data_io() as separate:
        expected_manifest = store.validate(digest)
        expected_reference = store.family_reference(digest)
    with measure_data_io() as combined:
        manifest, reference = store.validate_with_reference(digest)
    assert manifest == expected_manifest
    assert reference == expected_reference
    assert combined.bytes_read < separate.bytes_read
    assert combined.raw_financial_batch_opens < separate.raw_financial_batch_opens
    assert reference["family_id"] == "equity.financial_indicator"
    assert {
        "financial.indicator.eps", "financial.indicator.bps",
        "financial.indicator.current_ratio", "financial.indicator.roe",
        "financial.indicator.q_roe", "financial.indicator.netprofit_yoy",
        "financial.indicator.gross_profit", "financial.indicator.impai_ttm",
        "financial.indicator.q_impair_to_gr_ttm",
    }.issubset(reference["field_ids"])
    assert len(reference["field_ids"]) == len(set(reference["field_ids"]))
    assert reference["dataset_coverage"]["start"] == "2020-04-20"
    assert reference["dataset_coverage"]["end"] == "2020-05-04"
    reopened = FinancialIndicatorCandidateStore(tmp_path)
    table = reopened.read_table(
        digest,
        columns={"eps", "instrument_id"},
        instrument_ids=frozenset({"stock-1"}),
        through="2020-05-04",
    )
    assert table.column_names == ["eps", "instrument_id"]
    assert table.to_pylist() == [{"eps": "2.5", "instrument_id": "stock-1"}]
    reader = FinancialIndicatorSeriesResolver(
        digest,
        lambda cols, ids, through: reopened.read_table(
            digest, columns=cols, instrument_ids=ids, through=through
        ),
    )
    result = reader.resolve_table(
        manifest_sha256=digest,
        field_ids=("financial.indicator.roe",),
        sessions=("2020-04-20", "2020-04-21"),
        instrument_ids=("stock-1",),
    )
    assert result.column("financial.indicator.roe").to_pylist() == [None, 0.15]
    assert (
        store.build(
            collection_evidence_sha256s=(_collection_evidence(tmp_path, receipt),),
            instrument_ids={"000001.SZ": "stock-1"},
            sessions=("2020-04-20", "2020-04-21", "2020-05-04"),
        )
        == digest
    )


def test_candidate_rejects_source_identity_outside_history(tmp_path):
    import pytest

    source = {"ts_code": "UNKNOWN.SZ", "ann_date": "20200420", "end_date": "20191231"}
    evidence = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    receipt = evidence.save(
        RawSourceResponse(
            fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
            items=(tuple(source.get(f) for f in FINANCIAL_INDICATOR_SOURCE_FIELDS),),
        ),
        observed_at=datetime(2020, 5, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="identity"):
        FinancialIndicatorCandidateStore(tmp_path).build(
            collection_evidence_sha256s=(_collection_evidence(tmp_path, receipt),),
            instrument_ids={"000001.SZ": "stock-1"},
            sessions=("2020-04-21",),
        )


def test_candidate_validation_rejects_invalid_manifest_references(tmp_path):
    import copy
    import hashlib

    import pytest

    from thesistrace.data.generation_files import AddressedFileStore
    from thesistrace.publication.serialization import canonical_json_bytes

    source = {"ts_code": "000001.SZ", "ann_date": "20200420", "end_date": "20191231", "eps": 2}
    receipt = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path)).save(
        RawSourceResponse(
            fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
            items=(tuple(source.get(f) for f in FINANCIAL_INDICATOR_SOURCE_FIELDS),),
        ),
        observed_at=datetime(2020, 5, 1, tzinfo=UTC),
    )
    store = FinancialIndicatorCandidateStore(tmp_path)
    digest = store.build(
        collection_evidence_sha256s=(_collection_evidence(tmp_path, receipt),),
        instrument_ids={"000001.SZ": "stock-1"},
        sessions=("2020-04-21",),
    )
    store.validate(digest)
    original = store.reopen(digest)
    published = store.family_reference(digest)
    # A valid addressed Parquet file can still be the wrong source projection.
    alternate_source = {**source, "eps": 999}
    alternate_receipt = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path)).save(
        RawSourceResponse(
            fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
            items=(tuple(alternate_source.get(f) for f in FINANCIAL_INDICATOR_SOURCE_FIELDS),),
        ), observed_at=datetime(2020, 5, 1, tzinfo=UTC),
    )
    alternate = store.build(
        collection_evidence_sha256s=(_collection_evidence(tmp_path, alternate_receipt),),
        instrument_ids={"000001.SZ": "stock-1"}, sessions=("2020-04-21",),
    )
    alternate_partitions = store.validate(alternate)["partitions"]
    for fault in (
        "wrong_projection",
        "duplicate_partition",
        "foreign_partition",
        "wrong_count",
        "missing_observation",
        "dropped_partition",
    ):
        manifest = copy.deepcopy(original)
        if fault == "wrong_projection":
            manifest["partitions"] = alternate_partitions
        elif fault == "duplicate_partition":
            manifest["partitions"].append(manifest["partitions"][0])
        elif fault == "foreign_partition":
            manifest["partitions"][0]["instrument_id"] = "other"
        elif fault == "dropped_partition":
            manifest["partitions"] = []
        elif fault == "wrong_count":
            manifest["partitions"][0]["row_count"] = 99
        else:
            manifest["observation_sha256s"] = ["f" * 64]
        content = canonical_json_bytes(manifest)
        altered = hashlib.sha256(content).hexdigest()
        path = tmp_path / "manifests" / "sha256" / altered[:2] / f"{altered}.json"
        AddressedFileStore(tmp_path).store(path, altered, content)
        for validate in (
            store.validate, store.validate_with_reference,
            lambda address: store.validate_incremental_with_reference(
                address, published_base_reference=published,
            ),
        ):
            with pytest.raises(ValueError):
                validate(altered)

    # Previously returned mutable metadata cannot authorize a later read.
    manifest, reference = store.validate_with_reference(digest)
    manifest["partitions"].clear()
    reference["validation_summary"]["status"] = "tampered"
    assert store.validate_with_reference(digest)[0] == original
    partition = original["partitions"][0]
    address = partition["sha256"]
    path = tmp_path / "objects" / "sha256" / address[:2] / f"{address}.parquet"
    path.write_bytes(b"corrupted after validation")
    with pytest.raises(ValueError):
        store.validate_with_reference(digest)


def _collection_evidence(root, observation_sha256):
    from thesistrace.publication.serialization import canonical_json_bytes

    store = RawFinancialBatchStore(root)
    observation = FinancialIndicatorObservationStore(store).read(observation_sha256)
    code = observation["items"][0][observation["fields"].index("ts_code")]
    return store.store(
        canonical_json_bytes(
            {
                "source": "fina_indicator",
                "collection_key": "candidate-fixture",
                "instrument_id": "stock-1",
                "ts_code": code,
                "start_date": "19900101",
                "end_date": "20200504",
                "checked_through": "2020-05-04",
                "completed_requests": [
                    {
                        "request": {
                            "api_name": "fina_indicator",
                            "params": {
                                "ts_code": code,
                                "start_date": "19900101",
                                "end_date": "20200504",
                            },
                            "fields": list(FINANCIAL_INDICATOR_SOURCE_FIELDS),
                        },
                        "observation_sha256": observation_sha256,
                    }
                ],
            }
        )
    )


def test_candidate_rejects_history_seed_gap_or_coverage_beyond_collection(tmp_path):
    import pytest

    from thesistrace.publication.serialization import canonical_json_bytes

    raw_store = RawFinancialBatchStore(tmp_path)
    source = {"ts_code": "000001.SZ", "ann_date": "20200420", "end_date": "20191231", "eps": 2}
    receipt = FinancialIndicatorObservationStore(raw_store).save(
        RawSourceResponse(
            fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
            items=(tuple(source.get(f) for f in FINANCIAL_INDICATOR_SOURCE_FIELDS),),
        ),
        observed_at=datetime(2020, 5, 1, tzinfo=UTC),
    )
    original = raw_store.read(_collection_evidence(tmp_path, receipt))
    for key, value in (("start_date", "20100101"), ("end_date", "20200421")):
        import copy

        changed = copy.deepcopy(original)
        changed[key] = value
        changed["completed_requests"][0]["request"]["params"][key] = value
        evidence = raw_store.store(canonical_json_bytes(changed))
        with pytest.raises(ValueError, match="coverage"):
            FinancialIndicatorCandidateStore(tmp_path).build(
                collection_evidence_sha256s=(evidence,),
                instrument_ids={"000001.SZ": "stock-1"},
                sessions=("2020-04-21", "2020-05-04"),
            )


def test_candidate_uses_only_common_verified_session_coverage(tmp_path):
    raw = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    digest = raw.save(
        RawSourceResponse(
            fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
            items=(
                tuple(
                    {"ts_code": "000001.SZ", "end_date": "20191231", "ann_date": "20200420"}.get(
                        field
                    )
                    for field in FINANCIAL_INDICATOR_SOURCE_FIELDS
                ),
            ),
        ),
        observed_at=datetime(2020, 5, 4, tzinfo=UTC),
    )
    evidence = _collection_evidence(tmp_path, digest)
    store = FinancialIndicatorCandidateStore(tmp_path)
    assert store.available_sessions(
        collection_evidence_sha256s=(evidence,),
        instrument_ids={"000001.SZ": "stock-1"},
        sessions=("2020-04-21", "2020-05-04", "2020-05-05"),
    ) == ("2020-04-21", "2020-05-04")
    assert (
        store.available_sessions(
            collection_evidence_sha256s=(evidence,),
            instrument_ids={"000001.SZ": "stock-1", "000002.SZ": "stock-2"},
            sessions=("2020-04-21", "2020-05-04"),
        )
        == ()
    )


def test_indicator_projection_identity_ignores_repeated_evidence_and_pending(tmp_path):
    evidence = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    candidates = FinancialIndicatorCandidateStore(tmp_path)
    source = {"ts_code": "000001.SZ", "ann_date": "20200420", "end_date": "20191231", "eps": 2}

    def observe(day, value):
        row = dict(source, eps=value)
        receipt = evidence.save(
            RawSourceResponse(
                fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
                items=(tuple(row.get(field) for field in FINANCIAL_INDICATOR_SOURCE_FIELDS),),
            ),
            observed_at=datetime(2020, 5, day, tzinfo=UTC),
        )
        return _collection_evidence(tmp_path, receipt)

    def build(references, pending=None):
        return candidates.build(
            collection_evidence_sha256s=references,
            instrument_ids={"000001.SZ": "stock-1"},
            sessions=("2020-04-21", "2020-05-04"),
            unresolved_sources=pending,
        )

    first = observe(1, 2)
    repeated = observe(2, 2)
    changed = observe(3, 3)
    original = build((first,))
    replay = build((first, repeated))
    pending = build((first,), {"stock-1": "2020-05-01"})
    revised = build((first, repeated, changed))
    assert original != replay
    assert candidates.canonical_projection_sha256(
        original
    ) == candidates.canonical_projection_sha256(replay)
    assert candidates.canonical_projection_sha256(
        original
    ) == candidates.canonical_projection_sha256(pending)
    assert candidates.canonical_projection_sha256(
        original
    ) != candidates.canonical_projection_sha256(revised)


def test_candidate_projects_one_security_payload_at_a_time(tmp_path, monkeypatch):
    import weakref

    from thesistrace.publication.serialization import canonical_json_bytes

    raw = RawFinancialBatchStore(tmp_path)
    evidence = FinancialIndicatorObservationStore(raw)
    references, identities = [], {}
    for number in range(1, 5):
        code, instrument = f"{number:06d}.SZ", f"stock-{number}"
        identities[code] = instrument
        row = {"ts_code": code, "ann_date": "20200420", "end_date": "20191231", "eps": number}
        for observed_day in range(1, 5):
            receipt = evidence.save(
                RawSourceResponse(
                    fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
                    items=(tuple(row.get(field) for field in FINANCIAL_INDICATOR_SOURCE_FIELDS),),
                ),
                observed_at=datetime(2020, 5, observed_day, tzinfo=UTC),
            )
            ledger = raw.read(_collection_evidence(tmp_path, receipt))
            ledger["instrument_id"] = instrument
            references.append(raw.store(canonical_json_bytes(ledger)))

    class TrackedObservation(dict):
        pass

    live = weakref.WeakValueDictionary()
    read = FinancialIndicatorObservationStore.read
    peak_securities = 0
    peak_payloads = 0

    def tracked_read(self, digest):
        nonlocal peak_securities, peak_payloads
        observation = TrackedObservation(read(self, digest))
        live[id(observation)] = observation
        peak_payloads = max(peak_payloads, len(live))
        codes = {
            row[value["fields"].index("ts_code")]
            for value in live.values()
            for row in value["items"]
        }
        peak_securities = max(peak_securities, len(codes))
        return observation

    monkeypatch.setattr(FinancialIndicatorObservationStore, "read", tracked_read)
    candidates = FinancialIndicatorCandidateStore(tmp_path)
    digest = candidates.build(
        collection_evidence_sha256s=references,
        instrument_ids=identities,
        sessions=("2020-04-21", "2020-05-04"),
    )
    candidates.validate(digest)
    assert peak_securities == 1
    assert peak_payloads <= 2
    result = candidates.read_table(
        digest,
        columns={"instrument_id", "eps"},
        instrument_ids=frozenset(identities.values()),
        through="2020-05-04",
    )
    assert sorted(result.to_pylist(), key=lambda row: row["instrument_id"]) == [
        {"instrument_id": f"stock-{number}", "eps": str(number)} for number in range(1, 5)
    ]


def test_discovery_extends_coverage_without_claiming_another_raw_query(tmp_path):
    FINANCIAL_ANNOUNCEMENT_CATEGORIES = ("年报", "半年报", "一季报", "三季报", "补充更正")
    from thesistrace.publication.serialization import canonical_json_bytes

    raw = RawFinancialBatchStore(tmp_path)
    observation = FinancialIndicatorObservationStore(raw).save(
        RawSourceResponse(
            fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
            items=(tuple({"ts_code": "000001.SZ", "end_date": "20191231",
                          "ann_date": "20200420"}.get(field)
                         for field in FINANCIAL_INDICATOR_SOURCE_FIELDS),),
        ),
        observed_at=datetime(2020, 5, 4, tzinfo=UTC),
    )
    collected = _collection_evidence(tmp_path, observation)
    store = FinancialIndicatorCandidateStore(tmp_path)
    identities = {"000001.SZ": "stock-1"}
    sessions = ("2020-05-04", "2020-05-05", "2020-05-06")

    def receipt(start="2020-05-05", codes=None, completed=None, announcements=()):
        return raw.store(canonical_json_bytes({
            "source": "indicator-announcement-discovery",
            "instrument_ids": identities if codes is None else codes,
            "discovery": {
                "start_date": start, "end_date": "2020-05-06",
                "completed_categories": list(FINANCIAL_ANNOUNCEMENT_CATEGORIES)
                if completed is None else completed,
                "announcements": list(announcements), "gaps": [],
            },
            "source_lineage_sha256": "a" * 64,
        }))

    full = receipt()
    for receipts, expected in (
        ((full,), sessions),
        ((receipt(start="2020-05-06"),), sessions[:1]),
        ((receipt(codes={}),), sessions[:1]),
        ((receipt(completed=[]),), sessions[:1]),
    ):
        assert store.available_sessions(
            collection_evidence_sha256s=(collected,), instrument_ids=identities,
            sessions=sessions, discovery_evidence_sha256s=receipts,
        ) == expected
    candidate = store.build(
        collection_evidence_sha256s=(collected,), instrument_ids=identities,
        sessions=sessions, discovery_evidence_sha256s=(full,),
        unresolved_sources={"stock-1": "2020-05-05"},
    )
    manifest = store.validate(candidate)
    assert manifest["collection_evidence_sha256s"] == [collected]
    assert manifest["discovery_evidence_sha256s"] == [full]
    assert store.family_reference(candidate)["dataset_coverage"]["complete_through_session"] == (
        "2020-05-05"
    )
    assert store.available_sessions(
        collection_evidence_sha256s=(), instrument_ids=identities,
        sessions=sessions, discovery_evidence_sha256s=(full,),
    ) == ()

    missing = receipt(announcements=({
        "ts_code": "000001.SZ", "category": "一季报",
        "source_published_date": "2020-05-05", "report_period": "2020-03-31",
    },))
    absent = store.build(
        collection_evidence_sha256s=(collected,), instrument_ids=identities,
        sessions=sessions, discovery_evidence_sha256s=(missing,),
    )
    assert store.validate(absent)["unresolved_sources"] == {"stock-1": "2020-05-05"}
    matched = receipt(start="2020-04-20", announcements=({
        "ts_code": "000001.SZ", "category": "年报",
        "source_published_date": "2020-04-20", "report_period": "2019-12-31",
    },))
    resolved = store.build(
        collection_evidence_sha256s=(collected,), instrument_ids=identities,
        sessions=sessions, discovery_evidence_sha256s=(matched,),
    )
    assert store.validate(resolved)["unresolved_sources"] == {}

    import hashlib

    import pytest

    from thesistrace.data.generation_files import AddressedFileStore

    forged = store.reopen(absent)
    forged["unresolved_sources"] = {}
    content = canonical_json_bytes(forged)
    digest = hashlib.sha256(content).hexdigest()
    AddressedFileStore(tmp_path).store(
        tmp_path / "manifests" / "sha256" / digest[:2] / f"{digest}.json", digest, content,
    )
    with pytest.raises(ValueError, match="unresolved"):
        store.validate(digest)

    unknown = receipt(announcements=({
        "ts_code": "000001.SZ", "category": "补充更正",
        "source_published_date": "2020-05-05", "report_period": None,
    },))
    unknown_candidate = store.build(
        collection_evidence_sha256s=(collected,), instrument_ids=identities,
        sessions=sessions, discovery_evidence_sha256s=(unknown,),
    )
    assert store.validate(unknown_candidate)["unresolved_sources"] == {"stock-1": "2020-05-05"}

    def changed_observation(day, values):
        observed = FinancialIndicatorObservationStore(raw).save(
            RawSourceResponse(
                fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
                items=tuple(tuple({
                    "ts_code": "000001.SZ", "end_date": "20191231",
                    "ann_date": "20200420", "eps": eps,
                }.get(field) for field in FINANCIAL_INDICATOR_SOURCE_FIELDS) for eps in values),
            ), observed_at=datetime(2020, 5, day, tzinfo=UTC),
        )
        return _collection_evidence(tmp_path, observed)

    conflicting = changed_observation(5, [1, 2])
    ambiguous = store.build(
        collection_evidence_sha256s=(collected, conflicting), instrument_ids=identities,
        sessions=sessions, discovery_evidence_sha256s=(matched,),
    )
    assert store.validate(ambiguous)["unresolved_sources"] == {"stock-1": "2020-04-20"}
    corrected = changed_observation(6, [2])
    unambiguous = store.build(
        collection_evidence_sha256s=(collected, conflicting, corrected),
        instrument_ids=identities, sessions=sessions, discovery_evidence_sha256s=(matched,),
    )
    assert store.validate(unambiguous)["unresolved_sources"] == {}


def test_candidate_rejects_invalid_authoring_numbers_before_publication(tmp_path):
    import pytest

    observations = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    store = FinancialIndicatorCandidateStore(tmp_path)
    for value in ("oops", "NaN", "Infinity", "1e10000"):
        source = {"ts_code": "000001.SZ", "ann_date": "20200420", "end_date": "20191231",
                  "eps": value}
        receipt = observations.save(
            RawSourceResponse(
                fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
                items=(tuple(source.get(f) for f in FINANCIAL_INDICATOR_SOURCE_FIELDS),),
            ), observed_at=datetime(2020, 5, 1, tzinfo=UTC),
        )
        with pytest.raises(ValueError, match="financial indicator"):
            store.build(
                collection_evidence_sha256s=(_collection_evidence(tmp_path, receipt),),
                instrument_ids={"000001.SZ": "stock-1"}, sessions=("2020-04-21",),
            )
        assert observations.read(receipt)["items"]


def test_incremental_build_matches_full_replay_across_calendar_and_revision(tmp_path):
    import pytest

    evidence = FinancialIndicatorObservationStore(RawFinancialBatchStore(tmp_path))
    store = FinancialIndicatorCandidateStore(tmp_path)

    def receipt(eps, observed):
        source = {"ts_code": "000001.SZ", "ann_date": "20200420",
                  "end_date": "20191231", "eps": eps}
        observation = evidence.save(RawSourceResponse(
            fields=FINANCIAL_INDICATOR_SOURCE_FIELDS,
            items=(tuple(source.get(f) for f in FINANCIAL_INDICATOR_SOURCE_FIELDS),),
        ), observed_at=observed)
        return _collection_evidence(tmp_path, observation)

    collections = [receipt(2, datetime(2020, 4, 20, tzinfo=UTC))]
    identities = {"000001.SZ": "stock-1"}
    previous = None
    for sessions, revision in (
        (("2020-04-20",), False),
        (("2020-04-20", "2020-04-21"), False),
        (("2020-04-20", "2020-04-21", "2020-05-04"), False),
        (("2020-04-20", "2020-04-21", "2020-05-04"), True),
    ):
        if revision:
            collections.append(receipt(3, datetime(2020, 5, 1, tzinfo=UTC)))
        args = dict(collection_evidence_sha256s=collections,
                    instrument_ids=identities, sessions=sessions)
        full = store.build(**args)
        incremental = store.build(**args, previous_candidate_sha256=previous)
        assert incremental == full
        if previous is not None:
            from thesistrace.data.io_metrics import measure_data_io

            published = store.family_reference(previous)
            with measure_data_io() as audited:
                store.build(**args, previous_candidate_sha256=previous)
            with measure_data_io() as reused:
                from_published = store.build(**args, published_base_reference=published)
            assert from_published == full
            assert reused.raw_financial_batch_opens < audited.raw_financial_batch_opens
            expected_projections = int(revision or len(sessions) == 2)
            assert reused.indicator_securities_projected == expected_projections
            assert audited.indicator_securities_projected == expected_projections + 1
            with measure_data_io() as verified:
                manifest, reference = store.validate_incremental_with_reference(
                    incremental, published_base_reference=published,
                )
            assert verified.indicator_securities_projected == expected_projections
            assert manifest == store.validate(incremental)
            assert reference == store.family_reference(incremental)
        store.validate(incremental)
        previous = incremental

    published = store.family_reference(previous)
    dropped = store.build(**{**args, "collection_evidence_sha256s": collections[-1:]})
    with pytest.raises(ValueError, match="drops retained evidence"):
        store.validate_incremental_with_reference(dropped, published_base_reference=published)
    wrong_reference = {**published, "manifest_byte_count": 1}
    with pytest.raises(ValueError, match="reference"):
        store.build(**args, published_base_reference=wrong_reference)
    observation = store.reopen(previous)["observation_sha256s"][0]
    evidence_path = (tmp_path / "financial" / "raw" / "sha256"
                     / observation[:2] / f"{observation}.json")
    saved = evidence_path.read_bytes()
    evidence_path.unlink()
    with pytest.raises(ValueError, match="evidence"):
        store.reopen_published(published)
    evidence_path.write_bytes(saved)
    partition = store.reopen(previous)["partitions"][0]
    address = partition["sha256"]
    path = tmp_path / "objects" / "sha256" / address[:2] / f"{address}.parquet"
    path.write_bytes(b"damaged base")
    with pytest.raises(ValueError):
        store.build(**args, previous_candidate_sha256=previous)

    with pytest.raises(ValueError):
        store.build(**args, published_base_reference=published)
