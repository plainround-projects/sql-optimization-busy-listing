-- Undo the expand step: drop the covering index. Run it after the down script of 002, so one ordering index
-- always exists. Safe to run twice.
BEGIN;
DROP INDEX IF EXISTS idx_orders_listing;
COMMIT;
