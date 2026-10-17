-- Reviewed additive migration. Explicit execution only; never activates AI.
-- No credentials or legacy consent conversion. Run after draining pre-fence binaries.
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
