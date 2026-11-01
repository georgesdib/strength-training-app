-- 0048_resolver_provenance — identify the blueprint, policy and generated session.
--
-- The resolver is Step 1: storage only, no generator. These columns are nullable so every
-- historical prescription and the fixed-template path remain valid without a backfill. A null
-- means "not recorded", not "use the current policy". Digests are SHA-256 of the shipped
-- blueprint file and the resolver policy file; input_hash is the canonical state/config hash
-- for the generation (filled by the generator in a later step).
--
-- No template_version or resolver_policy_version table is added: the shipped YAML remains the
-- blueprint source of truth and the policy is a versioned file (DEC-RESOLVER-06).

ALTER TABLE prescription ADD COLUMN template_digest TEXT;
ALTER TABLE prescription ADD COLUMN policy_digest TEXT;
ALTER TABLE prescription ADD COLUMN input_hash TEXT;
ALTER TABLE prescription ADD COLUMN generated_session_json TEXT;
