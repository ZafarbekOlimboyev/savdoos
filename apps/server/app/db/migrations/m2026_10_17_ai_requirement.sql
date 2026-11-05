-- Reviewed additive migration. Explicit execution only; never activates AI.
-- No credentials or legacy consent conversion. Run after draining pre-fence binaries.
--
-- ⚠️  NOTHING IN THE DEPLOY PATH RUNS THIS FILE (measured R7.3). `start.sh` runs only
--     `app.initdb` + `app.seed`, and the `schema_migrate` registry
--     (`app/db/migrations/__init__.py`) imports only the uuid migration. The boot path
--     DOES create this table and its CHECK constraints, because `AiRequirement` is
--     registered in `app/models/__init__.py` and `initdb` calls
--     `Base.metadata.create_all` — but the TRIGGER and the seeded ROW below exist only
--     here. Without the row `activate()` raises 503, i.e. AI can never be switched on.
--
--     Prefer the operator CLI, which does exactly this, idempotently, with database
--     identity checks and a rehearsal unless --commit:
--
--         python -m app.tools.ai_requirement --provision --actor <who> \
--             --expect-system-identifier <sysid> --expect-database <db> [--commit]
--
--     The guard body is kept byte-identical to `services/ai_requirement._GUARD_FUNCTION_SQL`
--     by `tests/test_r74_ai_provision_pg.py::test_PROVISION_SQL_MIGRATSIYA_bilan_AYNI`.
BEGIN;
CREATE TABLE IF NOT EXISTS ai_requirement (
 id integer PRIMARY KEY CHECK (id = 1),
 revision bigint NOT NULL CHECK (revision > 0),
 mode varchar(10) NOT NULL CHECK (mode IN ('active','paused','demo')),
 provider varchar(20), model varchar(120),
 disclosure_version integer NOT NULL CHECK (disclosure_version > 0),
 disclosure_id varchar(100) NOT NULL,
 protocol_version integer NOT NULL CHECK (protocol_version > 0),
 dispatch_id varchar(100) NOT NULL,
 activated_by varchar(100) NOT NULL,
 activated_at timestamptz NOT NULL DEFAULT now(),
 CHECK ((mode = 'active' AND provider IS NOT NULL AND provider IN ('gemini','anthropic')
         AND model IS NOT NULL AND length(model) > 0)
        OR (mode IN ('paused','demo') AND provider IS NULL AND model IS NULL))
);
-- Enforce monotonic generations even for direct updates; no deletion/reuse.
CREATE OR REPLACE FUNCTION ai_requirement_revision_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 IF TG_OP = 'DELETE' THEN
   RAISE EXCEPTION 'ai requirement cannot be deleted';
 END IF;
 IF NEW.revision <> OLD.revision + 1 THEN
   RAISE EXCEPTION 'ai requirement revision must advance by one';
 END IF;
 RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS ai_requirement_revision_guard ON ai_requirement;
CREATE TRIGGER ai_requirement_revision_guard
 BEFORE UPDATE OR DELETE ON ai_requirement FOR EACH ROW
 EXECUTE FUNCTION ai_requirement_revision_guard();
INSERT INTO ai_requirement
 (id,revision,mode,provider,model,disclosure_version,disclosure_id,protocol_version,dispatch_id,activated_by)
 VALUES (1,1,'paused',NULL,NULL,1,'binos.receiving.ai.v1',2,'binos.receiving.dispatch.v2','migration')
 ON CONFLICT (id) DO NOTHING;
COMMIT;
