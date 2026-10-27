-- Step 5, expand: build the covering index next to the old one, so the listing never runs without an index.
-- INCLUDE keeps the listed columns in the leaf pages; the key stays (created_at DESC, id DESC).
-- In production on a live table this would be CREATE INDEX CONCURRENTLY (see project 3 of this track).
-- Safe to run twice. Undo: down/001_expand_covering_listing_index.down.sql.
BEGIN;
CREATE INDEX IF NOT EXISTS idx_orders_listing ON orders (created_at DESC, id DESC) INCLUDE (customer_id, status, total);
COMMIT;
-- An index-only scan needs the visibility map to mark pages all-visible (VACUUM cannot run in a transaction).
VACUUM orders;
