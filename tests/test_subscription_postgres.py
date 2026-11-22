import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from time import monotonic, sleep
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
PREEXISTING_USER = "11111111-1111-4111-a111-111111111111"


@pytest.fixture(scope="module")
def postgres():
    dsn = os.environ.get("KROPPI_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("KROPPI_TEST_POSTGRES_DSN requiere un PostgreSQL desechable para integración")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql

    name = f"kroppi_subscription_test_{uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("create database {}").format(sql.Identifier(name)))

        def connect():
            return psycopg.connect(dsn, dbname=name, autocommit=True)

        try:
            with connect() as conn:
                conn.execute((ROOT / "tests/subscription_schema.sql").read_text(encoding="utf-8"))
                for pattern in ("003_*", "004_*", "005_*"):
                    migration = next((ROOT / "migrations").glob(pattern))
                    conn.execute(migration.read_text(encoding="utf-8"))
                conn.execute("grant select on public.care_activities to authenticated")
                conn.execute("insert into auth.users values (%s)", (PREEXISTING_USER,))
                conn.execute("insert into diagnostics (user_id) values (%s)", (PREEXISTING_USER,))
                conn.execute((ROOT / "migrations/006_subscription_limits.sql").read_text(encoding="utf-8"))
                conn.execute((ROOT / "migrations/007_serialize_subscription_changes.sql").read_text(encoding="utf-8"))
            yield connect
        finally:
            admin.execute(sql.SQL("drop database {}").format(sql.Identifier(name)))


def scalar(conn, statement, *params):
    return conn.execute(statement, params).fetchone()[0]


def account(conn, plan="free", lifetime="1 day"):
    user = uuid4()
    conn.execute("insert into auth.users values (%s)", (user,))
    conn.execute(
        "insert into profiles (id, plan_type, premium_until) "
        "values (%s, %s, case when %s = 'premium' then now() + %s::interval end)",
        (user, plan, plan, lifetime),
    )
    return user


def assert_sqlstate(conn, code, statement, *params):
    import psycopg

    with pytest.raises(psycopg.Error) as error:
        conn.execute(statement, params)
    assert error.value.sqlstate == code


def authenticate(conn, user):
    conn.execute("set role authenticated")
    conn.execute("select set_config('request.jwt.claim.sub', %s, false)", (str(user),))
    conn.execute("set request.jwt.claim.role = 'authenticated'")


def resource_ids(conn, table):
    from psycopg import sql

    return {row[0] for row in conn.execute(sql.SQL("select id from {}").format(sql.Identifier(table)))}


@pytest.mark.parametrize("downgrade", [
    "premium_until = now()",
    "plan_type = 'free', premium_until = null",
], ids=["expiration", "plan-change"])
def test_downgrade_preserves_over_limit_resources_and_reactivation(postgres, downgrade):
    with postgres() as admin, postgres() as client:
        user = account(admin, "premium")
        outsider = account(admin)
        outsider_farm = scalar(admin, "insert into farms (owner_id) values (%s) returning id", outsider)
        farms = [scalar(admin, "insert into farms (owner_id) values (%s) returning id", user)
                 for _ in range(10)]
        crops = [scalar(admin, "insert into crops (farm_id) values (%s) returning id", farm)
                 for farm in farms[:8]]
        plots = [scalar(admin, "insert into plots (crop_id) values (%s) returning id", crops[i % 8])
                 for i in range(12)]
        sample = scalar(admin, "insert into plot_samples (plot_id) values (%s) returning id", plots[0])
        harvest = scalar(admin, "insert into harvests (plot_id) values (%s) returning id", plots[0])
        care = scalar(admin, "insert into care_activities (plot_id, created_by, applied_at, activity_type) "
                      "values (%s, %s, current_date, 'IRRIGATION') returning id", plots[0], user)
        old_diagnosis = scalar(admin, "insert into diagnostics (user_id, plot_samples_id, created_at) "
                               "values (%s, %s, now() - interval '2 months') returning id", user, sample)
        admin.execute("update diagnosis_quota_usage set period_start = period_start - interval '2 months' "
                      "where diagnosis_id = %s", (old_diagnosis,))
        current_diagnoses = {scalar(admin, "insert into diagnostics (user_id, plot_samples_id) "
                                   "values (%s, %s) returning id", user, sample) for _ in range(4)}
        expected = {"farms": set(farms), "crops": set(crops), "plots": set(plots)}
        authenticate(client, user)
        assert resource_ids(client, "diagnostics") == current_diagnoses | {old_diagnosis}
        usage = {"farms": 10, "crops": 8, "plots": 12, "diagnoses": 4}
        assert scalar(admin, "select subscription_status(%s)", user)["usage"] == usage

        admin.execute(f"update profiles set {downgrade} where id = %s", (user,))
        free = scalar(admin, "select subscription_status(%s)", user)
        assert free["plan_type"] == "free" and free["usage"] == usage
        assert free["limits"] == {"farms": 1, "crops": 2, "plots": 5, "diagnoses": 3}
        assert {table: resource_ids(client, table) for table in expected} == expected
        assert resource_ids(client, "diagnostics") == current_diagnoses
        assert scalar(admin, "select count(*) from diagnostics where user_id = %s", user) == 5
        assert scalar(admin, "select exists(select 1 from plot_samples where id = %s)", sample)
        assert scalar(admin, "select exists(select 1 from harvests where id = %s)", harvest)
        assert scalar(admin, "select exists(select 1 from care_activities where id = %s)", care)

        for table, identifier in (("farms", farms[0]), ("crops", crops[0]), ("plots", plots[0])):
            assert scalar(client, f"update {table} set name = 'Editado' where id = %s returning name",
                          identifier) == "Editado"
        assert client.execute("update farms set name = 'Intruso' where id = %s", (outsider_farm,)).rowcount == 0
        assert_sqlstate(client, "23514", "update farms set owner_id = %s where id = %s", outsider, farms[0])
        assert_sqlstate(client, "23514", "update crops set farm_id = %s where id = %s", farms[9], crops[0])
        assert_sqlstate(client, "23514", "update plots set crop_id = %s where id = %s", crops[1], plots[0])
        assert_sqlstate(client, "PT409", "insert into farms (owner_id) values (%s)", user)
        assert_sqlstate(client, "PT409", "insert into crops (farm_id) values (%s)", farms[0])
        assert_sqlstate(client, "PT409", "insert into plots (crop_id) values (%s)", crops[0])
        assert_sqlstate(admin, "PT429", "select consume_diagnosis_quota(%s,%s)", user, uuid4())

        admin.execute("update profiles set plan_type = 'premium', premium_until = now() + interval '1 day' "
                      "where id = %s", (user,))
        premium = scalar(admin, "select subscription_status(%s)", user)
        assert premium["plan_type"] == "premium" and premium["usage"] == usage
        assert resource_ids(client, "diagnostics") == current_diagnoses | {old_diagnosis}
        assert harvest in resource_ids(client, "harvests")
        assert care in resource_ids(client, "care_activities")
        farm = scalar(client, "insert into farms (owner_id) values (%s) returning id", user)
        crop = scalar(client, "insert into crops (farm_id) values (%s) returning id", farm)
        plot = scalar(client, "insert into plots (crop_id) values (%s) returning id", crop)
        assert resource_ids(client, "farms") == expected["farms"] | {farm}
        assert resource_ids(client, "crops") == expected["crops"] | {crop}
        assert resource_ids(client, "plots") == expected["plots"] | {plot}
        assert scalar(admin, "select consume_diagnosis_quota(%s,%s)", user, uuid4())
        assert scalar(admin, "select subscription_status(%s)", user)["usage"] == {
            "farms": 11, "crops": 9, "plots": 13, "diagnoses": 5,
        }


def test_free_slots_reopen_only_after_real_deletions(postgres):
    with postgres() as admin, postgres() as client:
        user = account(admin, "premium")
        authenticate(client, user)
        farm = scalar(client, "insert into farms (owner_id) values (%s) returning id", user)
        extra_farm = scalar(client, "insert into farms (owner_id) values (%s) returning id", user)
        crop = scalar(client, "insert into crops (farm_id) values (%s) returning id", farm)
        extra_crop = scalar(client, "insert into crops (farm_id) values (%s) returning id", farm)
        plots = [row[0] for row in client.execute(
            "insert into plots (crop_id) select %s from generate_series(1,6) returning id", (crop,),
        )]
        admin.execute("update profiles set plan_type = 'free' where id = %s", (user,))
        client.execute("update crops set is_active = false where id = %s", (extra_crop,))
        assert_sqlstate(client, "PT409", "insert into crops (farm_id) values (%s)", farm)

        client.execute("delete from plots where id = %s", (plots[0],))
        assert_sqlstate(client, "PT409", "insert into plots (crop_id) values (%s)", crop)
        client.execute("delete from plots where id = %s", (plots[1],))
        client.execute("insert into plots (crop_id) values (%s)", (crop,))
        assert_sqlstate(client, "PT409", "insert into plots (crop_id) values (%s)", crop)

        client.execute("delete from crops where id = %s", (extra_crop,))
        client.execute("insert into crops (farm_id) values (%s)", (farm,))
        assert_sqlstate(client, "PT409", "insert into crops (farm_id) values (%s)", farm)
        client.execute("delete from farms where id = %s", (extra_farm,))
        assert_sqlstate(client, "PT409", "insert into farms (owner_id) values (%s)", user)
        client.execute("delete from plots where crop_id = %s", (crop,))
        client.execute("delete from crops where farm_id = %s", (farm,))
        client.execute("delete from farms where id = %s", (farm,))
        client.execute("insert into farms (owner_id) values (%s)", (user,))
        assert_sqlstate(client, "PT409", "insert into farms (owner_id) values (%s)", user)


@pytest.mark.parametrize(("statement", "expected"), [
    ("insert into farms (owner_id) values (%s)", "PT409"),
    ("select consume_diagnosis_quota(%s, gen_random_uuid())", "PT429"),
])
def test_concurrent_write_waits_for_downgrade(postgres, statement, expected):
    import psycopg

    started = Event()
    with postgres() as admin, postgres() as writer, ThreadPoolExecutor(max_workers=1) as executor:
        user = account(admin, "premium")
        admin.execute("insert into farms (owner_id) values (%s)", (user,))
        for _ in range(3):
            scalar(admin, "select consume_diagnosis_quota(%s,%s)", user, uuid4())

        def attempt():
            started.set()
            try:
                writer.execute(statement, (user,))
            except psycopg.Error as error:
                return error.sqlstate

        pid = writer.info.backend_pid
        with admin.transaction():
            admin.execute("update profiles set plan_type = 'free' where id = %s", (user,))
            result = executor.submit(attempt)
            assert started.wait(5)
            deadline = monotonic() + 5
            while not scalar(admin, "select cardinality(pg_blocking_pids(%s)) > 0", pid):
                assert not result.done(), "The write finished before the downgrade committed"
                assert monotonic() < deadline, "The concurrent write never waited for the downgrade"
                sleep(0.01)
        assert result.result(timeout=5) == expected


def test_global_resource_limits_and_archived_crops(postgres):
    with postgres() as conn:
        user = account(conn)
        farm = scalar(conn, "insert into farms (owner_id) values (%s) returning id", user)
        assert_sqlstate(conn, "PT409", "insert into farms (owner_id) values (%s)", user)
        crop_a = scalar(conn, "insert into crops (farm_id, is_active) values (%s, false) returning id", farm)
        crop_b = scalar(conn, "insert into crops (farm_id) values (%s) returning id", farm)
        assert_sqlstate(conn, "PT409", "insert into crops (farm_id) values (%s)", farm)
        for crop in (crop_a, crop_a, crop_b, crop_b, crop_b):
            conn.execute("insert into plots (crop_id) values (%s)", (crop,))
        assert_sqlstate(conn, "PT409", "insert into plots (crop_id) values (%s)", crop_a)
        assert scalar(conn, "select subscription_status(%s)", user)["usage"] == {
            "farms": 1, "crops": 2, "plots": 5, "diagnoses": 0,
        }


def test_premium_payment_expiration_and_existing_resources(postgres):
    with postgres() as conn:
        user = account(conn)
        reference, transaction = str(uuid4()), str(uuid4())
        conn.execute(
            "insert into payments (user_id, reference, provider, amount_in_cents, currency, status) "
            "values (%s, %s, 'wompi', 1990000, 'COP', 'pending')", (user, reference),
        )
        conn.execute("set role service_role")
        conn.execute("set request.jwt.claim.role = 'service_role'")
        assert scalar(conn, "select confirm_wompi_payment(%s,%s,1990000,'COP','approved')",
                      reference, transaction) == {"result": "processed"}
        conn.execute("reset role")
        for _ in range(3):
            farm = scalar(conn, "insert into farms (owner_id) values (%s) returning id", user)
            crop = scalar(conn, "insert into crops (farm_id) values (%s) returning id", farm)
            conn.execute("insert into plots (crop_id) select %s from generate_series(1, 6)", (crop,))
        premium = scalar(conn, "select subscription_status(%s)", user)
        assert premium["limits"] == {"farms": None, "crops": None, "plots": None, "diagnoses": 30}
        assert premium["usage"] == {"farms": 3, "crops": 3, "plots": 18, "diagnoses": 0}
        for _ in range(4):
            assert scalar(conn, "select consume_diagnosis_quota(%s,%s)", user, uuid4())

        conn.execute("update profiles set premium_until = now() where id = %s", (user,))
        free = scalar(conn, "select subscription_status(%s)", user)
        assert free["plan_type"] == "free"
        assert free["usage"] == {"farms": 3, "crops": 3, "plots": 18, "diagnoses": 4}
        assert_sqlstate(conn, "PT409", "insert into farms (owner_id) values (%s)", user)
        assert_sqlstate(conn, "PT409", "insert into crops (farm_id) values (%s)", farm)
        assert_sqlstate(conn, "PT409", "insert into plots (crop_id) values (%s)", crop)
        assert_sqlstate(conn, "PT429", "select consume_diagnosis_quota(%s,%s)", user, uuid4())


@pytest.mark.parametrize(("plan", "limit"), [("free", 3), ("premium", 30)])
def test_monthly_quota_idempotency_and_reset(postgres, plan, limit):
    with postgres() as conn:
        user = account(conn, plan)
        diagnosis = uuid4()
        assert scalar(conn, "select consume_diagnosis_quota(%s,%s)", user, diagnosis)
        assert not scalar(conn, "select consume_diagnosis_quota(%s,%s)", user, diagnosis)
        conn.execute("insert into diagnostics (id, user_id) values (%s, %s)", (diagnosis, user))
        conn.execute("delete from diagnostics where id = %s", (diagnosis,))
        for _ in range(limit - 1):
            assert scalar(conn, "select consume_diagnosis_quota(%s,%s)", user, uuid4())
        assert_sqlstate(conn, "PT429", "select consume_diagnosis_quota(%s,%s)", user, uuid4())
        status = scalar(conn, "select subscription_status(%s)", user)
        assert status["usage"]["diagnoses"] == limit
        period = status["diagnosis_period"]
        assert period["timezone"] == "America/Bogota"
        assert scalar(conn, "select (%s::timestamptz at time zone 'America/Bogota')::time = time '00:00'",
                      period["renews_at"])
        conn.execute("update diagnosis_quota_usage set period_start = period_start - interval '1 month' "
                     "where user_id = %s", (user,))
        assert scalar(conn, "select subscription_status(%s)", user)["usage"]["diagnoses"] == 0
        assert scalar(conn, "select consume_diagnosis_quota(%s,%s)", user, uuid4())


def test_migration_counts_existing_diagnosis(postgres):
    with postgres() as conn:
        assert scalar(conn, "select subscription_status(%s)", PREEXISTING_USER)["usage"]["diagnoses"] == 1


def test_direct_client_cannot_change_plan_or_read_premium_data(postgres):
    with postgres() as conn:
        user = account(conn, "premium", "-1 day")
        another_user = account(conn)
        conn.execute("insert into loss_estimations default values")
        conn.execute("insert into harvests default values")
        old_diagnosis = scalar(conn, "insert into diagnostics (user_id, created_at) "
                               "values (%s, now() - interval '2 months') returning id", user)
        conn.execute("insert into diagnostics (user_id) values (%s)", (user,))
        conn.execute("set role authenticated")
        conn.execute("select set_config('request.jwt.claim.sub', %s, false)", (str(user),))
        conn.execute("set request.jwt.claim.role = 'authenticated'")
        assert not scalar(conn, "select my_subscription_is_premium()")
        assert_sqlstate(conn, "42501", "insert into farms (owner_id) values (%s)", another_user)
        conn.execute("insert into farms (owner_id) values (%s)", (user,))
        assert_sqlstate(conn, "PT409", "insert into farms (owner_id) values (%s)", user)
        conn.execute("update profiles set full_name = 'Demo' where id = %s", (user,))
        assert_sqlstate(conn, "42501", "update profiles set premium_until = now() + interval '30 days'")
        assert_sqlstate(conn, "42501", "update profiles set plan_type = 'free'")
        assert_sqlstate(conn, "42501", "select consume_diagnosis_quota(%s,%s)", user, uuid4())
        assert_sqlstate(conn, "42501", "insert into diagnostics (user_id) values (%s)", user)
        assert_sqlstate(conn, "42501", "update payments set status = 'approved'")
        assert_sqlstate(conn, "42501", "delete from profiles where id = %s", user)
        assert scalar(conn, "select count(*) from loss_estimations") == 0
        assert scalar(conn, "select count(*) from harvests") == 0
        assert scalar(conn, "select count(*) from diagnostics") == 1
        assert scalar(conn, "select count(*) from diagnostics where id = %s", old_diagnosis) == 0
        conn.execute("reset role")
        conn.execute("reset request.jwt.claim.role")
        conn.execute("update profiles set premium_until = now() + interval '1 day' where id = %s",
                     (user,))
        conn.execute("set role authenticated")
        assert scalar(conn, "select my_subscription_is_premium()")
        assert scalar(conn, "select count(*) from loss_estimations") == 1
        assert scalar(conn, "select count(*) from diagnostics where id = %s", old_diagnosis) == 1


@pytest.mark.parametrize("resource", [
    "farms", "crops", "plots", "diagnoses", "premium_diagnoses", "same_diagnosis",
])
def test_concurrent_requests_cannot_overrun_or_double_charge(postgres, resource):
    import psycopg

    with postgres() as conn:
        user = account(conn, "premium" if resource == "premium_diagnoses" else "free")
        if resource in {"crops", "plots"}:
            farm = scalar(conn, "insert into farms (owner_id) values (%s) returning id", user)
            crop = scalar(conn, "insert into crops (farm_id) values (%s) returning id", farm)
        if resource == "farms":
            stmt, target = "insert into farms (owner_id) values (%s)", user
        elif resource == "crops":
            stmt, target = "insert into crops (farm_id) values (%s)", farm
        elif resource == "plots":
            conn.execute("insert into plots (crop_id) select %s from generate_series(1, 4)", (crop,))
            stmt, target = "insert into plots (crop_id) values (%s)", crop
        else:
            for _ in range(29 if resource == "premium_diagnoses" else 2):
                scalar(conn, "select consume_diagnosis_quota(%s,%s)", user, uuid4())
            stmt, target = "select consume_diagnosis_quota(%s,%s)", user

    barrier = Barrier(6)
    shared_key = uuid4()

    def attempt():
        with postgres() as conn:
            params = (target,)
            if resource in {"diagnoses", "premium_diagnoses", "same_diagnosis"}:
                params += (shared_key if resource == "same_diagnosis" else uuid4(),)
            barrier.wait(timeout=10)
            try:
                result = conn.execute(stmt, params)
                return result.description is None or result.fetchone()[0]
            except psycopg.Error as error:
                return error.sqlstate

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _: attempt(), range(6)))
    rejection = {"diagnoses": "PT429", "premium_diagnoses": "PT429",
                 "same_diagnosis": False}.get(resource, "PT409")
    assert results.count(True) == 1
    assert results.count(rejection) == 5
