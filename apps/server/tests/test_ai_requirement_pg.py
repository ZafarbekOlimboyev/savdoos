"""Real PostgreSQL concurrency and HTTP contract tests; synthetic data only.

Set P0C_TEST_POSTGRES to the dedicated local p0c_tests database. No fallback
DB, no production URL, no external provider transport. Fixtures never use the
repository-wide client/initdb fixture.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from threading import Event
import os
import time
import uuid

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

import app.models
from app.db.base import Base
from app.db.session import get_db
from app.core.config import settings
from app.core.deps import get_current_employee
from app.models.ai_requirement import AiRequirement
from app.models.org import Company
from app.models.settings import Setting
from app.services import ai_consent as AC, ai_requirement as AR, receiving_ai as RA
from app.api.v1.receiving import router


@pytest.fixture(scope='module')
def pgengine():
    url = os.environ.get('P0C_TEST_POSTGRES')
    if not url:
        pytest.skip('Dedicated real PostgreSQL unavailable; concurrency NOT VERIFIED')
    parsed = make_url(url)
    assert (parsed.host, parsed.port, parsed.username, parsed.database) == (
        '127.0.0.1', 55483, 'p0c_local', 'p0c_tests'), 'Only isolated local test DB allowed'
    eng = create_engine(url, connect_args={'options': '-c statement_timeout=8000 -c lock_timeout=4000'})
    Base.metadata.create_all(eng)
    migration = Path(__file__).parents[1] / 'app/db/migrations/m2026_10_17_ai_requirement.sql'
    with eng.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        conn.exec_driver_sql(migration.read_text(encoding='utf-8-sig'))
    yield eng
    eng.dispose()


@pytest.fixture()
def case(pgengine, monkeypatch):
    with pgengine.begin() as conn:
        conn.execute(text('TRUNCATE ' + ','.join('"'+t.name+'"' for t in Base.metadata.tables.values()) + ' CASCADE'))
    monkeypatch.setattr(settings, 'gemini_api_key', 'synthetic-gemini')
    monkeypatch.setattr(settings, 'anthropic_api_key', 'synthetic-anthropic')
    with Session(pgengine) as db:
        a, b = Company(name='Synthetic A'), Company(name='Synthetic B')
        db.add_all([a, b]); db.flush()
        ids = a.id, b.id
        db.add(AiRequirement(id=1, revision=1, mode='active', provider='gemini', model='synthetic-model',
                            disclosure_version=1, disclosure_id=AR.DISCLOSURE_ID,
                            protocol_version=2, dispatch_id=AR.DISPATCH_ID, activated_by='test'))
        db.commit()
    return SimpleNamespace(engine=pgengine, company=ids[0], other=ids[1],
                           emp=SimpleNamespace(id=None, company_id=ids[0], role=SimpleNamespace(code='ega')))


def approved(case):
    with Session(case.engine) as db:
        return AC.status(db, case.company)


def grant(case, value=None):
    value = value or approved(case)
    with Session(case.engine) as db:
        result = AC.grant(db, case.emp, value); db.commit()
        return result


def activate(case, **changes):
    args = dict(expected_revision=1, mode='active', provider='anthropic', model='synthetic-model', actor='test')
    args.update(changes)
    with Session(case.engine) as db:
        revision = AR.activate(db, **args); db.commit()
        return revision


def count(case):
    with Session(case.engine) as db:
        return len(db.scalars(select(Setting).where(Setting.key == AC.CONSENT_KEY)).all())


def test_exact_grant_and_immutable_dispatch(case, monkeypatch):
    result = grant(case)
    assert result['granted'] and result['revision'] == 1
    seen = []
    monkeypatch.setattr(RA, '_read_gemini', lambda *a: seen.append(a[3]) or [])
    monkeypatch.setattr(RA, '_read_claude', lambda *a: pytest.fail('wrong provider'))
    with Session(case.engine) as db:
        target = AC.require_consent(db, case.company, 1)
        monkeypatch.setattr(settings, 'gemini_api_key', '')
        monkeypatch.setattr(settings, 'gemini_model', 'changed-after-check')
        assert RA.read_invoice('synthetic', 'image/jpeg', [], target)[1] == 'ai'
        assert seen == [target] and target.model == 'synthetic-model'
        with pytest.raises(FrozenInstanceError):
            target.provider = 'anthropic'
        assert 'synthetic-gemini' not in repr(target)


@pytest.mark.parametrize('key,value', [('provider','anthropic'), ('revision',2),
    ('disclosure_id','other'), ('disclosure_version',2), ('revision',True), ('provider',None)])
def test_mismatch_never_persists(case, key, value):
    value_map = approved(case); value_map[key] = value
    with Session(case.engine) as db, pytest.raises(HTTPException) as err:
        AC.grant(db, case.emp, value_map)
    assert err.value.status_code == 409 and count(case) == 0


def test_old_consent_is_not_promoted(case):
    with Session(case.engine) as db:
        db.add(Setting(company_id=case.company, key=AC.CONSENT_KEY,
                       value={'provider':'gemini','disclosure_version':1})); db.commit()
    assert not approved(case)['granted']
    with Session(case.engine) as db, pytest.raises(HTTPException) as err:
        AC.require_consent(db, case.company, 1)
    assert err.value.status_code == 403


def test_activation_before_grant_rejects_without_write(case):
    old = approved(case); activate(case)
    with Session(case.engine) as db, pytest.raises(HTTPException):
        AC.grant(db, case.emp, old)
    assert count(case) == 0


def wait_for_lock(engine, pid):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with engine.connect() as conn:
            waiting = conn.scalar(text("SELECT wait_event_type = 'Lock' FROM pg_stat_activity WHERE pid=:p"), {'p':pid})
        if waiting:
            return
        time.sleep(.01)
    pytest.fail('concurrent operation did not reach a PostgreSQL lock wait')


def test_grant_blocks_activation_until_commit(case):
    value = approved(case)
    with Session(case.engine) as first, ThreadPoolExecutor() as pool:
        AC.grant(first, case.emp, value)
        ready = Event(); pid = []
        def change():
            with Session(case.engine) as db:
                pid.append(db.scalar(text('SELECT pg_backend_pid()'))); ready.set()
                revision = AR.activate(db, expected_revision=1, mode='active', provider='anthropic',
                                       model='synthetic-model', actor='test'); db.commit()
                return revision
        future = pool.submit(change)
        assert ready.wait(2)
        try:
            wait_for_lock(case.engine, pid[0]); assert not future.done()
        finally:
            first.commit()
        assert future.result(5) == 2
    assert not approved(case)['granted']


def test_activation_holding_lock_rejects_waiting_stale_grant(case):
    old = approved(case)
    with Session(case.engine) as first, ThreadPoolExecutor() as pool:
        AR.activate(first, expected_revision=1, mode='active', provider='anthropic', model='synthetic-model', actor='test')
        ready = Event(); pid = []
        def stale_grant():
            with Session(case.engine) as db:
                pid.append(db.scalar(text('SELECT pg_backend_pid()'))); ready.set()
                with pytest.raises(HTTPException) as err:
                    AC.grant(db, case.emp, old)
                db.rollback(); return err.value.status_code
        future = pool.submit(stale_grant); assert ready.wait(2)
        try:
            wait_for_lock(case.engine, pid[0])
        finally:
            first.commit()
        assert future.result(5) == 409
    assert count(case) == 0


@pytest.mark.parametrize('operation', ['activation', 'revocation'])
def test_inflight_scan_blocks_policy_change_and_revoke(case, operation):
    grant(case)
    with Session(case.engine) as scan, ThreadPoolExecutor() as pool:
        target = AC.require_consent(scan, case.company, 1)
        ready = Event(); pid=[]
        def change():
            with Session(case.engine) as db:
                pid.append(db.scalar(text('SELECT pg_backend_pid()'))); ready.set()
                if operation == 'activation':
                    AR.activate(db, expected_revision=1, mode='active', provider='anthropic', model='synthetic-model', actor='test')
                else:
                    AC.revoke(db, case.emp)
                db.commit()
        future = pool.submit(change); assert ready.wait(2)
        try:
            wait_for_lock(case.engine, pid[0]); assert target.provider == 'gemini'
        finally:
            scan.rollback()
        future.result(5)
    assert not approved(case)['granted']


def test_two_first_grants_serialize_to_one_record(case):
    value = approved(case)
    with ThreadPoolExecutor() as pool:
        results = list(pool.map(lambda _: grant(case, value), range(2)))
    assert all(x['granted'] for x in results) and count(case) == 1


@pytest.mark.parametrize('change', [dict(protocol_version=3), dict(dispatch_id='unknown'),
    dict(disclosure_id='unknown'), dict(disclosure_version=2)])
def test_stale_worker_rejected(case, change):
    activate(case, **change)
    with Session(case.engine) as db, pytest.raises(HTTPException) as err:
        AC.require_consent(db, case.company, 2)
    assert err.value.headers['X-Error-Code'] == 'AI_WORKER_FENCED'


def test_missing_credential_does_not_become_demo(case, monkeypatch):
    monkeypatch.setattr(settings,'gemini_api_key','')
    with Session(case.engine) as db, pytest.raises(HTTPException) as err:
        AC.require_consent(db, case.company, 1)
    assert err.value.status_code == 503


def test_database_failure_is_closed(case):
    class Broken:
        def scalar(self,*a):
            raise DBAPIError('synthetic',{},Exception(),False)
    with pytest.raises(HTTPException) as err:
        AC.require_consent(Broken(), case.company, 1)
    assert err.value.status_code == 503


def test_missing_requirement_is_closed(case):
    with case.engine.begin() as conn:
        conn.execute(text('TRUNCATE ai_requirement'))
    with Session(case.engine) as db, pytest.raises(HTTPException) as err:
        AC.require_consent(db,case.company,1)
    assert err.value.status_code == 503


def test_explicit_demo_never_invokes_provider(case, monkeypatch):
    activate(case,mode='demo',provider=None,model=None)
    monkeypatch.setattr(settings,'gemini_api_key','')
    monkeypatch.setattr(RA,'_read_gemini',lambda *a: pytest.fail('demo sent data'))
    monkeypatch.setattr(RA,'_read_claude',lambda *a: pytest.fail('demo sent data'))
    with Session(case.engine) as db:
        target = AC.require_consent(db,case.company,2)
        assert RA.read_invoice('synthetic','image/jpeg',[],target)[1] == 'demo'


def test_activation_between_grant_and_scan_rejects(case):
    grant(case); activate(case)
    with Session(case.engine) as db, pytest.raises(HTTPException) as err:
        AC.require_consent(db,case.company,1)
    assert err.value.status_code == 409


def test_company_isolation(case):
    grant(case)
    with Session(case.engine) as db, pytest.raises(HTTPException) as err:
        AC.require_consent(db,case.other,1)
    assert err.value.status_code == 403


def test_duplicate_consent_fails_closed(case):
    grant(case)
    with Session(case.engine) as db:
        db.add(Setting(company_id=case.company,key=AC.CONSENT_KEY,value={})); db.commit()
    with pytest.raises(HTTPException) as err:
        approved(case)
    assert err.value.headers['X-Error-Code'] == 'AI_CONSENT_INTEGRITY'


def test_rollback_is_new_revision_and_revokes_old_approval(case):
    grant(case); activate(case)
    assert activate(case,expected_revision=2,provider='gemini') == 3
    assert not approved(case)['granted']


def test_sql_revision_cannot_go_backwards(case):
    with case.engine.begin() as conn, pytest.raises(DBAPIError):
        conn.execute(text('UPDATE ai_requirement SET revision=revision-1'))


def test_revoke_available_when_paused_or_no_credentials(case,monkeypatch):
    grant(case); activate(case,mode='paused',provider=None,model=None)
    monkeypatch.setattr(settings,'gemini_api_key','')
    with Session(case.engine) as db:
        assert AC.revoke(db,case.emp)['ok']; db.commit()
    with Session(case.engine) as db:
        assert 'revoked_at' in db.scalar(select(Setting)).value


@pytest.fixture()
def httpcase(case):
    app = FastAPI(); app.include_router(router)
    def session():
        with Session(case.engine) as db:
            yield db
    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_employee] = lambda: case.emp
    with TestClient(app) as api:
        yield api


def test_http_grant_exact_ack_and_legacy_rejected(case,httpcase):
    st=httpcase.get('/receiving/ai-consent').json()
    payload={k:st[k] for k in ('revision','provider','disclosure_id','disclosure_version')}
    assert httpcase.post('/receiving/ai-consent',json={'disclosure_version':1}).status_code == 422
    response=httpcase.post('/receiving/ai-consent',json=payload)
    assert response.status_code == 200 and response.json()['granted']
    assert response.json()['revision'] == st['revision']


def test_http_warehouse_grant_denied(case,httpcase):
    case.emp.role=SimpleNamespace(code='omborchi',permissions=[SimpleNamespace(code='xaridlar.edit')])
    st=httpcase.get('/receiving/ai-consent'); assert st.status_code == 200
    response=httpcase.post('/receiving/ai-consent',json=st.json())
    assert response.status_code == 403 and response.headers['X-Error-Code'] == 'PERMISSION_DENIED'
    assert count(case) == 0


def test_http_scan_gate_and_real_dispatch_snapshot(case,httpcase,monkeypatch):
    from tests.test_ch16_ai_rozilik_va_rasm import _jpeg
    seen=[]
    monkeypatch.setattr(RA,'_read_gemini',lambda *args: seen.append(args[3]) or [])
    payload={'image_b64':base64.b64encode(_jpeg()).decode(), 'revision':1}
    assert httpcase.post('/receiving/scan',json=payload).status_code == 403
    assert not seen
    grant(case)
    response=httpcase.post('/receiving/scan',json=payload)
    assert response.status_code == 200 and len(seen)==1
    assert seen[0].provider == 'gemini'
    activate(case)
    assert httpcase.post('/receiving/scan',json=payload).status_code == 409
    assert len(seen)==1


@pytest.mark.parametrize('failure',[RuntimeError('synthetic'),TimeoutError('synthetic')])
def test_provider_failure_releases_locks(case,monkeypatch,failure):
    grant(case)
    def fail(*a): raise failure
    monkeypatch.setattr(RA,'_read_gemini',fail)
    with Session(case.engine) as db:
        target=AC.require_consent(db,case.company,1)
        assert RA.read_invoice('synthetic','image/jpeg',[],target)[1].startswith('error:')
    assert activate(case) == 2

@pytest.mark.parametrize('operation',['activation','revocation'])
def test_http_inflight_provider_holds_locks(case,httpcase,monkeypatch,operation):
    from tests.test_ch16_ai_rozilik_va_rasm import _jpeg
    grant(case)
    entered, finish, changing = Event(), Event(), Event()
    pid=[]
    def provider(*args):
        entered.set()
        assert finish.wait(6)
        return []
    monkeypatch.setattr(RA,'_read_gemini',provider)
    def change():
        with Session(case.engine) as db:
            pid.append(db.scalar(text('SELECT pg_backend_pid()'))); changing.set()
            if operation == 'activation':
                AR.activate(db,expected_revision=1,mode='active',provider='anthropic',model='synthetic-model',actor='test')
            else:
                AC.revoke(db,case.emp)
            db.commit()
    with ThreadPoolExecutor() as pool:
        request=pool.submit(httpcase.post,'/receiving/scan',json={
            'revision':1,'image_b64':base64.b64encode(_jpeg()).decode()})
        assert entered.wait(3)
        mutation=pool.submit(change); assert changing.wait(2)
        try:
            wait_for_lock(case.engine,pid[0]); assert not mutation.done()
        finally:
            finish.set()
        assert request.result(5).status_code == 200
        mutation.result(5)
    assert not approved(case)['granted']


def test_migration_reapply_preserves_active_revision(case):
    grant(case); activate(case)
    migration=Path(__file__).parents[1]/'app/db/migrations/m2026_10_17_ai_requirement.sql'
    with case.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as conn:
        conn.exec_driver_sql(migration.read_text(encoding='utf-8-sig'))
    st=approved(case)
    assert st['revision']==2 and st['provider']=='anthropic'


def test_activation_compare_and_swap_and_pause(case):
    assert activate(case,mode='paused',provider=None,model=None)==2
    with pytest.raises(HTTPException) as err:
        activate(case)
    assert err.value.status_code==409
    with Session(case.engine) as db, pytest.raises(HTTPException) as err:
        AC.require_consent(db,case.company,2)
    assert err.value.headers['X-Error-Code']=='AI_REQUIREMENT_PAUSED'


def test_failed_grant_transaction_persists_no_consent_or_ack(case):
    with Session(case.engine) as db:
        AC.grant(db,case.emp,approved(case))
        db.rollback()
    assert count(case)==0


def test_scan_exception_cleanup_allows_activation(case):
    grant(case)
    with pytest.raises(RuntimeError):
        with Session(case.engine) as db:
            AC.require_consent(db,case.company,1)
            raise RuntimeError('synthetic canceled request')
    assert activate(case)==2

@pytest.mark.parametrize('scenario',['rehearse','commit','wrong_cluster','wrong_database'])
def test_activation_cli_identity_and_explicit_commit(case,scenario):
    import subprocess
    import sys
    with case.engine.connect() as conn:
        identity=conn.scalar(text('SELECT system_identifier::text FROM pg_control_system()'))
    env=dict(os.environ,DATABASE_URL=os.environ['P0C_TEST_POSTGRES'],APP_ENV='test',
             GEMINI_API_KEY='',ANTHROPIC_API_KEY='')
    args=[sys.executable,'-m','app.tools.ai_requirement','--expected-revision','1',
          '--expect-system-identifier',identity if scenario!='wrong_cluster' else '0',
          '--expect-database','p0c_tests' if scenario!='wrong_database' else 'wrong',
          '--mode','demo','--actor','synthetic-test','--confirm-fenced-workers-only']
    if scenario=='commit': args.append('--commit')
    result=subprocess.run(args,env=env,capture_output=True,text=True,timeout=15)
    assert result.returncode==(1 if scenario.startswith('wrong') else 0)
    with Session(case.engine) as db:
        row=db.get(AiRequirement,1)
        assert row.revision==(2 if scenario=='commit' else 1)
    assert 'postgresql' not in result.stdout and 'synthetic-gemini' not in result.stdout
