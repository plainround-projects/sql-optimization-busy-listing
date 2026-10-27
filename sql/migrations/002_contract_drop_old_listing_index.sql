-- Step 5, contract: the covering index has the same key, so the old narrow one only costs writes.
-- Safe to run twice. Undo: down/002_contract_drop_old_listing_index.down.sql.
BEGIN;
DROP INDEX IF EXISTS idx_orders_created_id;
COMMIT;
