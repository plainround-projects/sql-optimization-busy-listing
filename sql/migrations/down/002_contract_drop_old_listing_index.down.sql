-- Undo the contract step: bring the old ordering index back (run this before undoing 001). Safe to run twice.
BEGIN;
CREATE INDEX IF NOT EXISTS idx_orders_created_id ON orders (created_at DESC, id DESC);
COMMIT;
