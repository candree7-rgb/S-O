"""
S-O Trading System - Supabase Trade Logger
============================================
Logs all trades to Supabase for tracking and dashboard analytics.
"""

import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from dataclasses import dataclass

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    print("[WARN] supabase not installed - trade logging disabled")


@dataclass
class TradeRecord:
    """Complete trade record for logging"""
    # === BASICS ===
    symbol: str
    direction: str  # 'long' / 'short'

    # === ENTRY ===
    entry_price: float
    entry_time: datetime
    qty: float
    leverage: int
    margin_used: float
    equity_at_entry: float

    # === TP/SL ===
    sl_price: float
    tp_price: float

    # === ORDER IDs ===
    order_id: str = None

    # === RISK ===
    risk_pct: float = None
    risk_amount: float = None

    # === RZ/ATR FEATURES (for ML) ===
    atr_value: float = None
    zone_width: float = None
    bars_in_ready: int = None

    # === CONTEXT ===
    hour_utc: int = None
    day_of_week: int = None
    is_asian_session: bool = None
    is_london_session: bool = None
    is_ny_session: bool = None


class TradeLogger:
    """
    Logs trades to Supabase.

    Usage:
        logger = TradeLogger()
        trade_id = logger.log_entry(trade_record)
        logger.log_exit(trade_id, exit_data)
    """

    def __init__(self):
        self.client: Optional[Client] = None
        self.enabled = False

        if not SUPABASE_AVAILABLE:
            print("[TradeLogger] Supabase not available", flush=True)
            return

        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_KEY')

        if not url or not key:
            print("[TradeLogger] SUPABASE_URL or SUPABASE_KEY not set", flush=True)
            return

        try:
            self.client = create_client(url, key)
            self.enabled = True
            print("[TradeLogger] Connected to Supabase", flush=True)
        except Exception as e:
            print(f"[TradeLogger] Failed to connect: {e}", flush=True)

    def log_entry(self, trade: TradeRecord) -> Optional[str]:
        """Log trade entry. Returns trade ID for later update."""
        if not self.enabled:
            return None

        try:
            hour = trade.entry_time.hour
            is_asian = 0 <= hour < 8
            is_london = 8 <= hour < 16
            is_ny = 13 <= hour < 21

            data = {
                'symbol': trade.symbol,
                'direction': trade.direction,
                'entry_price': float(trade.entry_price),
                'entry_time': trade.entry_time.isoformat(),
                'qty': float(trade.qty),
                'leverage': trade.leverage,
                'margin_used': float(trade.margin_used),
                'equity_at_entry': float(trade.equity_at_entry),
                'sl_price': float(trade.sl_price),
                'tp_price': float(trade.tp_price),
                'order_id': trade.order_id,
                'risk_pct': trade.risk_pct,
                'risk_amount': trade.risk_amount,

                # RZ/ATR features
                'atr_value': trade.atr_value,
                'zone_width': trade.zone_width,
                'bars_in_ready': trade.bars_in_ready,

                # Session
                'hour_utc': hour,
                'day_of_week': trade.entry_time.weekday(),
                'is_asian_session': is_asian,
                'is_london_session': is_london,
                'is_ny_session': is_ny,
            }

            # Remove None values
            data = {k: v for k, v in data.items() if v is not None}

            result = self.client.table('trades').insert(data).execute()

            if result.data:
                trade_id = result.data[0]['id']
                print(f"  [DB] Trade logged: {trade_id[:8]}...", flush=True)
                return trade_id

        except Exception as e:
            print(f"  [DB ERR] Log entry: {str(e)[:80]}", flush=True)

        return None

    def log_exit(
        self,
        trade_id: str,
        exit_price: float,
        exit_time: datetime,
        exit_reason: str,
        realized_pnl: float,
        equity_at_close: float,
        is_win: bool,
        entry_time: datetime = None,
        margin_used: float = None,
        entry_fee: float = 0,
        exit_fee: float = 0,
    ) -> bool:
        """Update trade with exit data."""
        if not self.enabled or not trade_id:
            return False

        try:
            duration_minutes = None
            if entry_time:
                duration_minutes = int((exit_time - entry_time).total_seconds() / 60)

            total_fees = entry_fee + exit_fee
            net_pnl = realized_pnl - total_fees

            pnl_pct = None
            pnl_pct_equity = None
            if margin_used and margin_used > 0:
                pnl_pct = (realized_pnl / margin_used) * 100
            if equity_at_close and equity_at_close > 0:
                pnl_pct_equity = (realized_pnl / equity_at_close) * 100

            data = {
                'exit_price': float(exit_price),
                'exit_time': exit_time.isoformat(),
                'exit_reason': exit_reason,
                'duration_minutes': duration_minutes,
                'realized_pnl': float(realized_pnl),
                'pnl_pct': float(pnl_pct) if pnl_pct is not None else None,
                'pnl_pct_equity': float(pnl_pct_equity) if pnl_pct_equity is not None else None,
                'equity_at_close': float(equity_at_close),
                'is_win': bool(is_win),
                'total_fees': float(total_fees),
                'net_pnl': float(net_pnl),
            }

            data = {k: v for k, v in data.items() if v is not None}

            result = self.client.table('trades').update(data).eq('id', trade_id).execute()

            if result.data:
                pnl_str = f"+${realized_pnl:.2f}" if realized_pnl > 0 else f"-${abs(realized_pnl):.2f}"
                print(f"  [DB] Exit logged: {exit_reason} {pnl_str}", flush=True)
                return True

        except Exception as e:
            print(f"  [DB ERR] Log exit: {str(e)[:80]}", flush=True)

        return False

    def find_open_trade(self, symbol: str, direction: str) -> Optional[Dict]:
        """Find an open trade by symbol and direction (no exit yet)."""
        if not self.enabled:
            return None

        try:
            result = self.client.table('trades')\
                .select('*')\
                .eq('symbol', symbol)\
                .eq('direction', direction)\
                .is_('exit_time', 'null')\
                .order('entry_time', desc=True)\
                .limit(1)\
                .execute()

            if result.data:
                return result.data[0]

        except Exception as e:
            print(f"  [DB ERR] Find open trade: {str(e)[:80]}", flush=True)

        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get trading statistics"""
        if not self.enabled:
            return {}

        try:
            result = self.client.table('trades')\
                .select('*')\
                .not_.is_('exit_time', 'null')\
                .execute()

            trades = result.data
            if not trades:
                return {'total_trades': 0}

            wins = [t for t in trades if t.get('is_win')]
            losses = [t for t in trades if not t.get('is_win')]

            total_pnl = sum(t.get('net_pnl', 0) or t.get('realized_pnl', 0) for t in trades)

            return {
                'total_trades': len(trades),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': len(wins) / len(trades) * 100 if trades else 0,
                'total_pnl': total_pnl,
            }

        except Exception as e:
            print(f"  [DB ERR] Get stats: {e}", flush=True)
            return {}

    def get_symbol_winrate(self, symbol: str) -> Dict[str, Any]:
        """
        Get historical winrate for a specific symbol.
        Returns wins, losses, total, winrate, and confidence score.

        Confidence scoring: more trades = more confidence in winrate
        """
        if not self.enabled:
            return {'wins': 0, 'losses': 0, 'total': 0, 'winrate': 0.5, 'confidence': 0}

        try:
            result = self.client.table('trades')\
                .select('is_win')\
                .eq('symbol', symbol)\
                .not_.is_('exit_time', 'null')\
                .execute()

            trades = result.data
            if not trades:
                return {'wins': 0, 'losses': 0, 'total': 0, 'winrate': 0.5, 'confidence': 0}

            wins = sum(1 for t in trades if t.get('is_win'))
            losses = len(trades) - wins
            total = len(trades)

            # Wilson score lower bound for confidence
            # With few trades, we're less confident in the winrate
            winrate = wins / total if total > 0 else 0.5

            # Confidence: 0 to 1, based on number of trades
            # 10+ trades = full confidence
            confidence = min(total / 10, 1.0)

            return {
                'wins': wins,
                'losses': losses,
                'total': total,
                'winrate': winrate,
                'confidence': confidence
            }

        except Exception as e:
            print(f"  [DB ERR] Get symbol winrate: {e}", flush=True)
            return {'wins': 0, 'losses': 0, 'total': 0, 'winrate': 0.5, 'confidence': 0}

    def log_shadow_trade(self, shadow_data: Dict[str, Any]) -> Optional[str]:
        """Log a shadow trade (signal not executed but tracked for ML)"""
        if not self.enabled:
            return None

        try:
            data = {
                'shadow_id': shadow_data['id'],
                'symbol': shadow_data['symbol'],
                'direction': shadow_data['direction'],
                'entry_price': shadow_data['entry'],
                'tp_price': shadow_data['tp'],
                'sl_price': shadow_data['sl'],
                'reason': shadow_data['reason'],
                'rsi': shadow_data.get('rsi'),
                'volume_ratio': shadow_data.get('volume_ratio'),
                'atr_percent': shadow_data.get('atr_percent'),
                'score': shadow_data.get('score'),
                'created_at': shadow_data['created_at'].isoformat(),
                'status': 'ACTIVE',
            }

            data = {k: v for k, v in data.items() if v is not None}

            result = self.client.table('shadow_trades').insert(data).execute()

            if result.data:
                print(f"  [DB] Shadow trade logged: {shadow_data['id'][:20]}...", flush=True)
                return shadow_data['id']

        except Exception as e:
            print(f"  [DB ERR] Log shadow trade: {str(e)[:80]}", flush=True)

        return None

    def update_shadow_trade(self, shadow_id: str, outcome: str, exit_price: float) -> bool:
        """Update shadow trade with outcome (WIN/LOSS)"""
        if not self.enabled:
            return False

        try:
            from datetime import datetime

            data = {
                'status': outcome,
                'outcome': outcome,
                'exit_price': exit_price,
                'exit_time': datetime.utcnow().isoformat(),
            }

            result = self.client.table('shadow_trades')\
                .update(data)\
                .eq('shadow_id', shadow_id)\
                .execute()

            if result.data:
                print(f"  [DB] Shadow trade updated: {shadow_id[:20]}... -> {outcome}", flush=True)
                return True

        except Exception as e:
            print(f"  [DB ERR] Update shadow trade: {str(e)[:80]}", flush=True)

        return False

    def get_shadow_stats(self) -> Dict[str, Any]:
        """Get shadow trade statistics for ML analysis"""
        if not self.enabled:
            return {}

        try:
            result = self.client.table('shadow_trades')\
                .select('*')\
                .not_.is_('outcome', 'null')\
                .execute()

            shadows = result.data
            if not shadows:
                return {'total': 0}

            wins = [s for s in shadows if s.get('outcome') == 'WIN']
            losses = [s for s in shadows if s.get('outcome') == 'LOSS']

            return {
                'total': len(shadows),
                'wins': len(wins),
                'losses': len(losses),
                'winrate': len(wins) / len(shadows) * 100 if shadows else 0,
            }

        except Exception as e:
            print(f"  [DB ERR] Get shadow stats: {e}", flush=True)
            return {}


# Global instance
_logger: Optional[TradeLogger] = None

def get_trade_logger() -> TradeLogger:
    """Get or create global trade logger instance"""
    global _logger
    if _logger is None:
        _logger = TradeLogger()
    return _logger
