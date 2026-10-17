"""Explicit privileged AI activation. No public API or startup auto-activation.

Rehearses unless --commit. Deployment must first drain all pre-fence binaries.
The confirmation is operator evidence, not remote enforcement of old binaries.
"""
import argparse
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.services.ai_requirement import activate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--expected-revision', type=int, required=True)
    p.add_argument('--expect-system-identifier', required=True)
    p.add_argument('--expect-database', required=True)
    p.add_argument('--mode', choices=['active', 'paused', 'demo'], required=True)
    p.add_argument('--provider', choices=['gemini', 'anthropic'])
    p.add_argument('--model')
    p.add_argument('--actor', required=True)
    p.add_argument('--confirm-fenced-workers-only', action='store_true', required=True)
    p.add_argument('--commit', action='store_true')
    args = p.parse_args()
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
            revision = activate(db, expected_revision=args.expected_revision,
                                mode=args.mode, provider=args.provider, model=args.model,
                                actor=args.actor)
            if args.commit:
                db.commit()
            else:
                db.rollback()
            print(('ACTIVATED' if args.commit else 'REHEARSED') + f' revision={revision}')
    except Exception:
        print('REJECTED: activation not confirmed; inspect safe diagnostics locally')
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
