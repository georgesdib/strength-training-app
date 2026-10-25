-- 0032_clean_set_supersedes_index — make the append-only leaf lookup fast.
--
-- clean_sets() excludes any row that has a correction pointing at it. Without an index on
-- supersedes_id, SQLite scans the whole clean_set table for every row (O(n^2)); the history
-- passed ~7,900 rows and requests started taking tens of seconds. The index changes no data.

CREATE INDEX idx_clean_set_supersedes
    ON clean_set(supersedes_id)
    WHERE supersedes_id IS NOT NULL;
