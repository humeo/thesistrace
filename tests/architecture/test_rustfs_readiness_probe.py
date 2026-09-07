from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

ROOT = Path(__file__).resolve().parents[2]


def _load_probe() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader(
        "thesistrace_rustfs_readiness_probe",
        str(ROOT / "scripts" / "probe-rustfs-ready"),
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _client_error(*, operation: str, status: int, code: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "sensitive upstream detail"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        operation,
    )


def test_rustfs_probe_only_classifies_startup_failures_as_transient() -> None:
    probe = _load_probe()

    assert probe.is_transient_s3_error(
        EndpointConnectionError(endpoint_url="http://private.invalid")
    )
    assert probe.is_transient_s3_error(
        _client_error(operation="ListBuckets", status=503, code="ServiceUnavailable")
    )
    assert probe.is_transient_s3_error(
        _client_error(operation="CreateBucket", status=404, code="NotFound")
    )
    assert probe.is_transient_s3_error(
        _client_error(operation="HeadBucket", status=404, code="NotFound")
    )
    assert not probe.is_transient_s3_error(
        _client_error(operation="ListBuckets", status=404, code="NotFound")
    )
    assert not probe.is_transient_s3_error(
        _client_error(operation="CreateBucket", status=403, code="AccessDenied")
    )


@pytest.mark.parametrize(
    ("error", "expected_exit", "expected_status"),
    [
        (
            _client_error(
                operation="ListBuckets",
                status=503,
                code="ServiceUnavailable",
            ),
            75,
            "rustfs_s3_readiness=transient\n",
        ),
        (
            _client_error(
                operation="ListBuckets",
                status=403,
                code="AccessDenied",
            ),
            2,
            "rustfs_s3_readiness=permanent\n",
        ),
    ],
)
def test_rustfs_probe_exits_with_a_sanitized_failure_class(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: ClientError,
    expected_exit: int,
    expected_status: str,
) -> None:
    probe = _load_probe()

    class FailingClient:
        closed = False

        def list_buckets(self) -> dict[str, object]:
            raise error

        def close(self) -> None:
            self.closed = True

    client = FailingClient()
    monkeypatch.setattr(probe.boto3, "client", lambda *args, **kwargs: client)
    monkeypatch.setattr(sys, "argv", ["probe-rustfs-ready"])
    monkeypatch.setenv("THESISTRACE_S3_ENDPOINT_URL", "http://private.invalid")
    monkeypatch.setenv("THESISTRACE_S3_ACCESS_KEY_ID", "private-access")
    monkeypatch.setenv("THESISTRACE_S3_SECRET_ACCESS_KEY", "private-secret")

    with pytest.raises(SystemExit) as raised:
        probe.main()

    assert raised.value.code == expected_exit
    assert capsys.readouterr().err == expected_status
    assert client.closed
