from collections.abc import Iterator
from uuid import uuid4

import pytest
from core_runtime import TEST_RESEARCHER, stop_internal_api_servers

from thesistrace._postgres import PostgresDatabase
from thesistrace.entrypoints.runtime import CoreSettings
from thesistrace.researcher.quota import QuotaPolicy


@pytest.fixture(autouse=True)
def isolate_internal_strategy_metric_server() -> Iterator[None]:
    try:
        yield
    finally:
        stop_internal_api_servers()


@pytest.fixture
def pro_quota_policy(monkeypatch: pytest.MonkeyPatch) -> QuotaPolicy:
    """Multi-track execution fixtures buy capacity explicitly; Free stays at one."""
    policy = QuotaPolicy(
        timezone="Asia/Shanghai",
        daily_model_budget_nanodollars=1_000_000_000,
        daily_run_limit=100,
        active_daily_track_limit=10,
    )
    monkeypatch.setattr(
        "thesistrace.entrypoints.runtime.quota_policy_lookup",
        lambda _origin: lambda _researcher_id: policy,
    )
    return policy


@pytest.fixture
def paid_pro_quota() -> Iterator[None]:
    """Real Auth grants reach MCP subprocesses as well as the in-process API."""
    database = PostgresDatabase(CoreSettings.from_environment().database_url)
    database.open()
    transaction_id = f"fixture_pro_{uuid4()}"
    created_user = False
    try:
        with database.transaction() as transaction:
            created_user = transaction.execute(
                '''INSERT INTO auth."user" (id, name, email, "emailVerified", active)
                   VALUES (%s, 'Quota fixture', %s, true, true)
                   ON CONFLICT (id) DO NOTHING RETURNING id''',
                (TEST_RESEARCHER.researcher_id,
                 f"quota-{TEST_RESEARCHER.researcher_id}@fixture.test"),
            ).fetchone() is not None
            transaction.execute(
                """INSERT INTO auth.billing_payment
                   (transaction_id, researcher_id, subscription_id, plan_key,
                    starts_at, ends_at, amount)
                   VALUES (%s, %s, %s, 'pro', now() - interval '1 hour',
                           now() + interval '1 day', 2000)""",
                (transaction_id, TEST_RESEARCHER.researcher_id, transaction_id),
            )
        yield
    finally:
        with database.transaction() as transaction:
            transaction.execute(
                "DELETE FROM auth.billing_payment WHERE transaction_id = %s",
                (transaction_id,),
            )
            if created_user:
                transaction.execute(
                    'DELETE FROM auth."user" WHERE id = %s',
                    (TEST_RESEARCHER.researcher_id,),
                )
        database.close()
