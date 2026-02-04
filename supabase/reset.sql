-- =============================================================================
-- S-O Trading System - RESET / CLEAN Database
-- =============================================================================
-- WARNING: This deletes ALL trade data! Use with caution.
--
-- Usage:
--   1. Go to Supabase Dashboard -> SQL Editor
--   2. Paste the command you need
--   3. Click "Run"
-- =============================================================================

-- ─────────────────────────────────────────────────────────────────────────────
-- OPTION 1: Delete all trades (keep table structure)
-- Use this to start fresh without losing the schema
-- ─────────────────────────────────────────────────────────────────────────────
DELETE FROM trades;

-- Verify:
-- SELECT COUNT(*) FROM trades;

-- ─────────────────────────────────────────────────────────────────────────────
-- OPTION 2: Drop and recreate (full reset)
-- Use this if you want to change the schema
-- ─────────────────────────────────────────────────────────────────────────────
-- DROP TABLE IF EXISTS trades;
-- Then run schema.sql to recreate

-- ─────────────────────────────────────────────────────────────────────────────
-- OPTION 3: Delete only old trades (keep recent)
-- ─────────────────────────────────────────────────────────────────────────────
-- DELETE FROM trades WHERE entry_time < NOW() - INTERVAL '30 days';

-- ─────────────────────────────────────────────────────────────────────────────
-- OPTION 4: Delete only open trades (no exit yet)
-- ─────────────────────────────────────────────────────────────────────────────
-- DELETE FROM trades WHERE exit_time IS NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- MIGRATE FROM sysv1: Drop old table and create new
-- ─────────────────────────────────────────────────────────────────────────────
-- DROP TABLE IF EXISTS trades;
-- Then run schema.sql
