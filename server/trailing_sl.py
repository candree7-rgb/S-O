"""
S-O Trading System - Trailing SL Monitor
==========================================
Monitors open positions via Bybit websocket and moves SL to profit
when price reaches a configurable % of the entry-to-TP distance.

Example (defaults):
  Entry=100, TP=110 (distance=10)
  85% threshold = 108.5
  When price hits 108.5 → move SL to 103.0 (30% of distance above entry)

Config via env vars:
  TRAIL_ENABLED=true
  TRAIL_TP_THRESHOLD_PCT=85
  TRAIL_SL_MOVE_PCT=30
"""

import threading
import time
import json
from datetime import datetime
from typing import Dict, Optional

from pybit.unified_trading import WebSocket

from config import config
import telegram_alerts


class TrailingSLMonitor:
    """
    Monitors positions via Bybit websocket ticker stream.
    When price reaches threshold % of TP distance, moves SL to lock in profit.
    """

    def __init__(self, executor):
        self.executor = executor
        self.enabled = config.risk.trail_enabled
        self.threshold_pct = config.risk.trail_tp_threshold_pct / 100  # e.g. 0.85
        self.sl_move_pct = config.risk.trail_sl_move_pct / 100  # e.g. 0.30

        # Tracked positions: symbol -> {direction, entry, tp, sl, original_sl, trail_activated}
        self.tracked: Dict[str, Dict] = {}
        self._lock = threading.Lock()

        # Websocket
        self.ws = None
        self._running = False

        print(f"[TRAILING SL] Initialized (enabled={self.enabled}, "
              f"threshold={self.threshold_pct*100}%, move={self.sl_move_pct*100}%)")

    def track_position(self, symbol: str, direction: str, entry: float, tp: float, sl: float):
        """Start tracking a position for trailing SL."""
        if not self.enabled:
            return

        with self._lock:
            self.tracked[symbol] = {
                'direction': direction,
                'entry': entry,
                'tp': tp,
                'sl': sl,
                'original_sl': sl,
                'trail_activated': False,
            }

        print(f"[TRAILING SL] Tracking {direction.upper()} {symbol} "
              f"entry={entry}, tp={tp}, sl={sl}")

        # Subscribe to ticker if websocket is running
        if self._running and self.ws:
            self._subscribe(symbol)

    def untrack_position(self, symbol: str):
        """Stop tracking a position."""
        with self._lock:
            self.tracked.pop(symbol, None)
        print(f"[TRAILING SL] Untracked {symbol}")

    def start(self):
        """Start the websocket monitor in a background thread."""
        if not self.enabled:
            print("[TRAILING SL] Disabled, not starting")
            return

        self._running = True
        thread = threading.Thread(target=self._run_ws, daemon=True)
        thread.start()
        print("[TRAILING SL] Websocket monitor started")

    def stop(self):
        """Stop the websocket monitor."""
        self._running = False
        if self.ws:
            try:
                self.ws.exit()
            except Exception:
                pass
        print("[TRAILING SL] Stopped")

    def _run_ws(self):
        """Run websocket connection with auto-reconnect."""
        while self._running:
            try:
                self.ws = WebSocket(
                    testnet=config.api.testnet,
                    channel_type="linear",
                )

                # Subscribe to all currently tracked symbols
                with self._lock:
                    symbols = list(self.tracked.keys())

                for symbol in symbols:
                    self._subscribe(symbol)

                print(f"[TRAILING SL] Websocket connected, watching {len(symbols)} symbols")

                # Keep alive
                while self._running:
                    time.sleep(1)

            except Exception as e:
                print(f"[TRAILING SL] Websocket error: {e}, reconnecting in 5s...")
                time.sleep(5)

    def _subscribe(self, symbol: str):
        """Subscribe to ticker for a symbol."""
        try:
            self.ws.ticker_stream(
                symbol=symbol,
                callback=self._on_ticker,
            )
        except Exception as e:
            print(f"[TRAILING SL] Subscribe error for {symbol}: {e}")

    def _on_ticker(self, message: dict):
        """Handle ticker update — check if trailing SL should activate."""
        try:
            data = message.get('data', {})
            symbol = data.get('symbol', '')
            last_price = float(data.get('lastPrice', 0))

            if not symbol or not last_price:
                return

            with self._lock:
                pos = self.tracked.get(symbol)
                if not pos or pos['trail_activated']:
                    return

                entry = pos['entry']
                tp = pos['tp']
                direction = pos['direction']

                # Calculate threshold price
                if direction == 'long':
                    tp_distance = tp - entry
                    threshold_price = entry + tp_distance * self.threshold_pct
                    should_activate = last_price >= threshold_price
                else:
                    tp_distance = entry - tp
                    threshold_price = entry - tp_distance * self.threshold_pct
                    should_activate = last_price <= threshold_price

                if not should_activate:
                    return

                # Calculate new SL
                if direction == 'long':
                    new_sl = entry + tp_distance * self.sl_move_pct
                else:
                    new_sl = entry - tp_distance * self.sl_move_pct

                old_sl = pos['sl']
                pos['trail_activated'] = True
                pos['sl'] = new_sl

            # Move SL on exchange (outside lock)
            print(f"[TRAILING SL] {symbol} hit {self.threshold_pct*100}% "
                  f"(price={last_price}, threshold={threshold_price:.6f})")
            print(f"[TRAILING SL] Moving SL: {old_sl} -> {new_sl}")

            side = "Buy" if direction == 'long' else "Sell"
            symbol_info = self.executor.get_symbol_info(symbol)
            success = self.executor.update_stop_loss(symbol, side, new_sl, symbol_info)

            if success:
                telegram_alerts.send_trailing_sl_moved(
                    symbol=symbol,
                    direction=direction,
                    old_sl=old_sl,
                    new_sl=new_sl,
                    entry=entry,
                )
            else:
                # Revert state so it tries again
                with self._lock:
                    if symbol in self.tracked:
                        self.tracked[symbol]['trail_activated'] = False
                        self.tracked[symbol]['sl'] = old_sl

        except Exception as e:
            print(f"[TRAILING SL] Ticker error: {e}")
