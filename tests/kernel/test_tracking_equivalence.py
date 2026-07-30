import math
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from thesistrace.api import create_app
from thesistrace.config import Settings
from thesistrace.tracking import (
    DailyTrackingService,
    EquivalenceError,
    equivalence_bytes,
    first_divergence,
)


def test_equivalence_encoding_is_exact_for_numeric_contracts() -> None:
    assert equivalence_bytes(1) != equivalence_bytes(1.0)
    assert equivalence_bytes(Decimal("1.0")) == equivalence_bytes(
        Decimal("1.00")
    )
    assert first_divergence(1.0, math.nextafter(1.0, 2.0)) == "$"
    with pytest.raises(
        EquivalenceError,
        match=r"^EQUIVALENCE_MISMATCH at \$\.factor\.ic$",
    ):
        DailyTrackingService._assert_equivalent(
            {"factor": {"ic": 1.0}},
            {"factor": {"ic": math.nextafter(1.0, 2.0)}},
            "$",
        )


def test_equivalence_mismatch_has_stable_public_reason(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def mismatch(
        _service: DailyTrackingService,
        _track_id: str,
    ) -> dict[str, object]:
        raise EquivalenceError(
            "EQUIVALENCE_MISMATCH at $.checkpoints.checkpoint_1.strategy.daily[0]"
        )

    monkeypatch.setattr(DailyTrackingService, "verify_equivalence", mismatch)
    settings = Settings(
        metadata_path=tmp_path / "metadata.sqlite3",
        object_root=tmp_path / "objects",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/daily-tracks/track_missing/verify-equivalence"
        )
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "reason_code": "EQUIVALENCE_MISMATCH",
        "message": (
            "EQUIVALENCE_MISMATCH at "
            "$.checkpoints.checkpoint_1.strategy.daily[0]"
        ),
    }
