"""Explicit privileged AI activation. No public API or startup auto-activation.

Rehearses unless --commit. Deployment must first drain all pre-fence binaries.
The confirmation is operator evidence, not remote enforcement of old binaries.

Two modes, both rehearse unless --commit:

  --provision   Install the DB-level revision guard and seed the `paused` policy
                row. NEVER activates AI. Needed because the boot path creates the
                table but not the trigger or the row, and without a row activation
                is impossible (see services/ai_requirement.provision).
  (default)     Activate / pause / demote the policy via CAS on --expected-revision.
"""
import argparse
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.ai_requirement import activate, provision


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--provision', action='store_true',
                   help='Install the DB guard and seed the paused row; never activates.')
    p.add_argument('--expected-revision', type=int)
    p.add_argument('--expect-system-identifier', required=True)
    p.add_argument('--expect-database', required=True)
    p.add_argument('--mode', choices=['active', 'paused', 'demo'])
    p.add_argument('--provider', choices=['gemini', 'anthropic'])
    p.add_argument('--model')
    p.add_argument('--actor', required=True)
    p.add_argument('--confirm-fenced-workers-only', action='store_true')
    p.add_argument('--commit', action='store_true')
    args = p.parse_args()
    # Mode gates stay explicit: --provision must not be able to carry a policy, and
    # activation keeps every argument it required before --provision existed.
    policy = (('--expected-revision', args.expected_revision), ('--mode', args.mode),
              ('--provider', args.provider), ('--model', args.model))
    if args.provision:
        given = [name for name, value in policy if value is not None]
        if args.confirm_fenced_workers_only:
            given.append('--confirm-fenced-workers-only')
        if given:
            p.error('--provision never sets a policy; drop: ' + ', '.join(given))
    else:
        absent = [name for name, value in policy[:2] if value is None]
        if not args.confirm_fenced_workers_only:
            absent.append('--confirm-fenced-workers-only')
        if absent:
            p.error('activation needs: ' + ', '.join(absent))
    # Never print connection URLs or driver error text.
    url = os.environ.get('DATABASE_URL', '')
    for prefix in ('postgres://', 'postgresql://'):
        if url.startswith(prefix):
            url = 'postgresql+psycopg://' + url[len(prefix):]
            break
    if not url.startswith('postgresql+psycopg://'):
        p.error('Explicit PostgreSQL DATABASE_URL required')
    engine = None
    try:
        engine = create_engine(url)
        with Session(engine) as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            db.execute(text("SET LOCAL statement_timeout = '10s'"))
            identity = db.scalar(text('SELECT system_identifier::text FROM pg_control_system()'))
            database = db.scalar(text('SELECT current_database()'))
            if identity != args.expect_system_identifier or database != args.expect_database:
                raise ValueError('database identity mismatch')
            if args.provision:
                out = provision(db, actor=args.actor)
            else:
                out = {'revision': activate(
                    db, expected_revision=args.expected_revision, mode=args.mode,
                    provider=args.provider, model=args.model, actor=args.actor)}
            if args.commit:
                db.commit()
            else:
                db.rollback()
            if args.provision:
                print(('PROVISIONED' if args.commit else 'REHEARSED')
                      + f" guard={out['guard']} row={out['row']}"
                      + f" revision={out['revision']} mode={out['mode']}"
                      + f" canonical={out['canonical']}")
            else:
                print(('ACTIVATED' if args.commit else 'REHEARSED')
                      + f" revision={out['revision']}")
    except Exception:
        print('REJECTED: activation not confirmed; inspect safe diagnostics locally')
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
