import os
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from thesistrace._postgres import PostgresDatabase, SchemaDefinition, initialize_schemas
from thesistrace.migrations.payload_retention_0003 import SOURCE, TARGET, migrate
from thesistrace.publication.serialization import canonical_json_bytes


@pytest.fixture
def source_database(core_settings):
    assert os.environ["THESISTRACE_TEST_PROJECT_NAME"].startswith("thesistrace-test-")
    admin = psycopg.connect(core_settings.database_url, autocommit=True)
    name = "event_retention_" + uuid4().hex
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    params = conninfo_to_dict(core_settings.database_url)
    params["dbname"] = name
    db = PostgresDatabase(make_conninfo(**params))
    db.open()
    with ZipFile(
        Path(__file__).parents[1] / "fixtures/historical-core-schema/event-retention-source.zip"
    ) as z:
        definitions = tuple(SchemaDefinition(n[:-4], z.read(n).decode()) for n in z.namelist())
    initialize_schemas(db, definitions)
    try:
        yield db
    finally:
        db.close()
        admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
        admin.close()


def test_explicit_upgrade_preserves_old_inventory_and_repeated_apply_does_not_renew(
    source_database,
):
    from hashlib import sha256

    db = source_database
    # Populate an actual old immutable inventory, including all recorded event streams.
    names = [
        "strategy_targets",
        "strategy_orders",
        "strategy_child_orders",
        "strategy_fills",
        "strategy_adjustments",
        "strategy_summary",
    ]
    objects = [
        dict(
            name=n,
            sha256=sha256(n.encode()).hexdigest(),
            bytes=2,
            media_type="application/json",
            serialization={"format": "canonical-json"},
        )
        for n in sorted(names)
    ]
    manifest = canonical_json_bytes(
        dict(schema_version=1, kind="research.result", provenance={}, objects=objects)
    )
    digest = sha256(manifest).hexdigest()
    with db.transaction() as tx:
        tx.execute(
            "INSERT INTO publication.manifests VALUES (%s, 1, 'research.result', %s, now())",
            (digest, manifest),
        )
        for ordinal, item in enumerate(objects):
            tx.execute(
                "INSERT INTO publication.objects(sha256, byte_size) VALUES (%s, 2)",
                (item["sha256"],),
            )
            tx.execute(
                "INSERT INTO publication.manifest_objects VALUES (%s, %s, %s, %s)",
                (digest, ordinal, item["name"], item["sha256"]),
            )
    assert migrate(db)["status"] == "validated"
    assert migrate(db, apply=True)["updated"] == 1
    with db.transaction() as tx:
        row = tx.execute("SELECT * FROM publication.payload_retention").fetchone()
        assert "strategy_summary" not in row["payload_names"]
        assert len(row["payload_names"]) == 5
        assert (
            bytes(
                tx.execute("SELECT manifest_bytes FROM publication.manifests").fetchone()[
                    "manifest_bytes"
                ]
            )
            == manifest
        )
        assert (
            tx.execute("SELECT count(*) n FROM publication.manifest_objects").fetchone()["n"] == 6
        )
    assert migrate(db, apply=True)["status"] == "already_current"
    with db.transaction() as tx:
        assert tx.execute("SELECT * FROM publication.payload_retention").fetchone() == row
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == TARGET
        )


def test_failed_upgrade_rolls_back_ddl_receipt_and_contract(source_database):
    db = source_database
    with db.transaction() as tx:
        tx.execute(
            "CREATE TABLE thesistrace_meta.migration_history (id text PRIMARY KEY, "
            "source_fingerprint text, target_fingerprint text, "
            "updated_rows integer CHECK (updated_rows < 0))"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        migrate(db, apply=True)
    with db.transaction() as tx:
        assert (
            tx.execute("SELECT to_regclass('publication.payload_retention') t").fetchone()["t"]
            is None
        )
        assert (
            tx.execute("SELECT fingerprint FROM thesistrace_meta.schema_contract").fetchone()[
                "fingerprint"
            ]
            == SOURCE
        )
        assert (
            tx.execute("SELECT count(*) n FROM thesistrace_meta.migration_history").fetchone()["n"]
            == 0
        )
