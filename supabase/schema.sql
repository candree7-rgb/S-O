-- =============================================================================
-- S-O Trading System - Supabase Schema
-- =============================================================================
-- Run this in Supabase SQL Editor to create the trades table.
-- This replaces the old sysv1/SMC schema.
--
-- Usage:
--   1. Go to Supabase Dashboard -> SQL Editor
--   2. Paste this entire file
--   3. Click "Run"
-- =============================================================================

-- Drop old table (sysv1 schema is incompatible - different columns)
DROP TABLE IF EXISTS trades;

-- Create trades table with new S-O schema
CREATE TABLE trades (
    -- Primary key
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- === BASICS ===
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('long', 'short')),

    -- === ENTRY ===
    entry_price DOUBLE PRECISION NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    qty DOUBLE PRECISION NOT NULL,
    leverage INTEGER NOT NULL DEFAULT 20,
    margin_used DOUBLE PRECISION,
    equity_at_entry DOUBLE PRECISION,

    -- === TP/SL ===
    sl_price DOUBLE PRECISION NOT NULL,
    tp_price DOUBLE PRECISION NOT NULL,

    -- === ORDER TRACKING ===
    order_id TEXT,

    -- === EXIT (filled when trade closes) ===
    exit_price DOUBLE PRECISION,
    exit_time TIMESTAMPTZ,
    exit_reason TEXT,  -- 'tp', 'sl', 'manual', 'be'
    duration_minutes INTEGER,

    -- === PnL ===
    realized_pnl DOUBLE PRECISION,
    pnl_pct DOUBLE PRECISION,          -- PnL as % of margin
    pnl_pct_equity DOUBLE PRECISION,   -- PnL as % of equity
    equity_at_close DOUBLE PRECISION,
    is_win BOOLEAN,
    total_fees DOUBLE PRECISION DEFAULT 0,
    net_pnl DOUBLE PRECISION,

    -- === RISK ===
    risk_pct DOUBLE PRECISION,
    risk_amount DOUBLE PRECISION,

    -- === RZ/ATR FEATURES (for ML) ===
    atr_value DOUBLE PRECISION,
    zone_width DOUBLE PRECISION,
    bars_in_ready INTEGER,

    -- === SESSION CONTEXT ===
    hour_utc INTEGER,
    day_of_week INTEGER,
    is_asian_session BOOLEAN,
    is_london_session BOOLEAN,
    is_ny_session BOOLEAN
);

-- =============================================================================
-- INDEXES for performance
-- =============================================================================
CREATE INDEX idx_trades_symbol ON trades(symbol);
CREATE INDEX idx_trades_exit_time ON trades(exit_time);
CREATE INDEX idx_trades_direction ON trades(direction);
CREATE INDEX idx_trades_is_win ON trades(is_win);
CREATE INDEX idx_trades_entry_time ON trades(entry_time);

-- =============================================================================
-- ROW LEVEL SECURITY (optional - enable if using anon key from frontend)
-- =============================================================================
-- ALTER TABLE trades ENABLE ROW LEVEL SECURITY;
--
-- -- Allow read access for dashboard (anon key)
-- CREATE POLICY "Allow read access" ON trades
--     FOR SELECT USING (true);
--
-- -- Allow insert/update for server (service role key)
-- CREATE POLICY "Allow insert for service" ON trades
--     FOR INSERT WITH CHECK (true);
--
-- CREATE POLICY "Allow update for service" ON trades
--     FOR UPDATE USING (true);

-- =============================================================================
-- COMMENTS
-- =============================================================================
COMMENT ON TABLE trades IS 'S-O Trading System - All trade records';
COMMENT ON COLUMN trades.direction IS 'long or short';
COMMENT ON COLUMN trades.exit_reason IS 'tp=take profit, sl=stop loss, manual, be=break even';
COMMENT ON COLUMN trades.pnl_pct IS 'PnL as percentage of margin used';
COMMENT ON COLUMN trades.pnl_pct_equity IS 'PnL as percentage of total equity';
COMMENT ON COLUMN trades.atr_value IS 'ATR value at entry (from Universal Backtester)';
COMMENT ON COLUMN trades.zone_width IS 'Reversal Zone width (S1-S3 or R1-R3 distance)';
COMMENT ON COLUMN trades.bars_in_ready IS 'Number of bars in READY state before triggering';


-- =============================================================================
-- SHADOW TRADES TABLE (for ML data collection)
-- =============================================================================
-- Shadow trades are signals we didn't execute (max positions reached, etc.)
-- but we track their theoretical outcomes for ML training.
-- This helps us learn which signals we should prioritize.
-- =============================================================================

DROP TABLE IF EXISTS shadow_trades;

CREATE TABLE shadow_trades (
    -- Primary key
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),

    -- Shadow trade ID (from webhook server)
    shadow_id TEXT UNIQUE NOT NULL,

    -- === BASICS ===
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('long', 'short')),

    -- === ENTRY/EXIT LEVELS ===
    entry_price DOUBLE PRECISION NOT NULL,
    tp_price DOUBLE PRECISION NOT NULL,
    sl_price DOUBLE PRECISION NOT NULL,

    -- === WHY NOT EXECUTED ===
    reason TEXT NOT NULL,  -- 'max_longs_reached', 'max_shorts_reached', 'duplicate_position'

    -- === ML FEATURES (at signal time) ===
    rsi DOUBLE PRECISION,
    volume_ratio DOUBLE PRECISION,
    atr_percent DOUBLE PRECISION,
    score DOUBLE PRECISION,  -- ML score at signal time

    -- === OUTCOME (filled when TP/SL hit) ===
    status TEXT DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'WIN', 'LOSS')),
    outcome TEXT CHECK (outcome IN ('WIN', 'LOSS')),
    exit_price DOUBLE PRECISION,
    exit_time TIMESTAMPTZ
);

-- Indexes
CREATE INDEX idx_shadow_symbol ON shadow_trades(symbol);
CREATE INDEX idx_shadow_status ON shadow_trades(status);
CREATE INDEX idx_shadow_outcome ON shadow_trades(outcome);
CREATE INDEX idx_shadow_created ON shadow_trades(created_at);

COMMENT ON TABLE shadow_trades IS 'Shadow trades - signals not executed but tracked for ML';
COMMENT ON COLUMN shadow_trades.reason IS 'Why this trade was not executed';
COMMENT ON COLUMN shadow_trades.score IS 'ML score at signal time (for comparing with actual outcomes)';
