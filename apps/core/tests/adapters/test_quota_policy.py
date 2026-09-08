from uuid import uuid4

import httpx
import pytest

from thesistrace.entrypoints.quota_policy import quota_policy_lookup
from thesistrace.researcher.quota import QuotaPolicyUnavailable


def test_reads_the_complete_effective_policy_without_local_defaults(monkeypatch):
    value = {"timezone": "America/New_York", "daily_model_budget_nanodollars": 250_000_000,
             "daily_run_limit": 3, "active_daily_track_limit": 2}
    monkeypatch.setattr(httpx, "get", lambda url, **_kwargs:
                        httpx.Response(200, json=value, request=httpx.Request("GET", url)))
    assert quota_policy_lookup("http://auth.test")(uuid4()).model_dump() == value


@pytest.mark.parametrize("value", [
    {"unlimited": True},
    {"timezone": "Asia/Shanghai"},
    {"timezone": "invalid", "daily_model_budget_nanodollars": 1,
     "daily_run_limit": 1, "active_daily_track_limit": 1},
    {"timezone": "Asia/Shanghai", "daily_model_budget_nanodollars": 1,
     "daily_run_limit": True, "active_daily_track_limit": 1},
])
def test_rejects_malformed_policy(monkeypatch, value):
    monkeypatch.setattr(httpx, "get", lambda url, **_kwargs:
                        httpx.Response(200, json=value, request=httpx.Request("GET", url)))
    with pytest.raises(QuotaPolicyUnavailable):
        quota_policy_lookup("http://auth.test")(uuid4())


def test_missing_authority_never_implies_unlimited_access():
    with pytest.raises(QuotaPolicyUnavailable):
        quota_policy_lookup(None)(uuid4())
