from pathlib import Path

from thesistrace.bounded_research import load_columnar_research_window
from thesistrace.datasets import DatasetPublisher
from thesistrace.fixture import build_fixture
from thesistrace.objects import ImmutableObjectStore
from thesistrace.research_runs import (
    calculate_bounded_research,
    calculate_research,
    research_input_history,
)
from thesistrace.storage import MetadataStore


def test_columnar_research_is_exactly_equivalent_to_legacy_calculation(
    tmp_path: Path,
) -> None:
    metadata = MetadataStore(tmp_path / "metadata.sqlite3")
    metadata.initialize()
    objects = ImmutableObjectStore(tmp_path / "objects")
    datasets = DatasetPublisher(metadata, objects)
    source, canonical = build_fixture()
    release, _created = datasets.bootstrap_documents(
        "root",
        source=source,
        canonical=canonical,
        source_kind="source_fixture",
        source_schema="tushare-fixture-v1",
    )
    definition = {
        "universe": "top300",
        "alpha": {"expression": "pct_change($close_adj, 20)"},
        "neutralization": "industry",
        "strategy": {
            "holdings_count": 30,
            "rebalance_interval": 5,
            "initial_cash_cny": "10000000",
            "execution": "next_open_full_fill",
        },
        "costs": {
            "commission_rate_all_in": "0.0003",
            "commission_min_cny": "5",
            "stamp_duty_sell_rate": "0.0005",
            "transfer_fee_rate": "0.00001",
        },
        "risk_free_rate": "0",
    }

    legacy = calculate_research(research_input_history(canonical), definition)
    bounded = calculate_bounded_research(
        load_columnar_research_window(objects, release, definition),
        definition,
    )

    assert bounded == legacy

    normalized_definition = {
        **definition,
        "alpha": {
            "expression": {
                "operator_id": "pct_change",
                "operands": [
                    {"field_id": "snapshot.price.close"},
                    {"literal": 20},
                ],
            }
        },
        "field_bindings": [{"field_id": "snapshot.price.close", "name": "close_adj"}],
    }
    normalized_legacy = calculate_research(
        research_input_history(canonical),
        normalized_definition,
    )
    normalized_bounded = calculate_bounded_research(
        load_columnar_research_window(objects, release, normalized_definition),
        normalized_definition,
    )

    assert normalized_bounded == normalized_legacy
    assert normalized_bounded["alpha_matrix"]["checksum"] == legacy["alpha_matrix"]["checksum"]
