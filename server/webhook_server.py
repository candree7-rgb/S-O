"""
S-O Trading System - Webhook Server
=====================================
Receives alerts from TradingView Universal Backtester
and executes trades via Bybit API.

Alert Types from Universal Backtester:
  READY      - Step 1 triggered, watching for Step 2
  UPDATE     - Still in ready state, updated projected levels
  TRIGGERED  - Signal fired, place order now
  EXIT       - TP or SL hit
  CANCELLED  - Ready state expired without triggering

Shadow Trading (for ML):
  When at max positions, trades are tracked as "shadow" trades.
  Their theoretical outcomes (WIN/LOSS) are logged for ML training.

Usage:
    python webhook_server.py

Environment Variables:
    BYBIT_API_KEY, BYBIT_API_SECRET, BYBIT_TESTNET
    WEBHOOK_SECRET, PORT
    SUPABASE_URL, SUPABASE_KEY
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import os
import json
import hmac
import hashlib
import threading
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from flask import Flask, request, jsonify

from config import config
from executor import BybitExecutor
from trade_logger import get_trade_logger, TradeRecord
from trailing_sl import TrailingSLMonitor
import telegram_alerts

app = Flask(__name__)

# Global executor
executor: Optional[BybitExecutor] = None

# Trailing SL monitor
trailing_monitor: Optional[TrailingSLMonitor] = None

# Track pending orders for cancellation
pending_orders: Dict[str, Dict[str, Any]] = {}

# Track ready states (for context when TRIGGERED arrives)
ready_states: Dict[str, Dict[str, Any]] = {}  # key = "LONG_BTCUSDT"

# Shadow trades - trades not executed but tracked for ML
shadow_trades: Dict[str, Dict[str, Any]] = {}  # key = "LONG_BTCUSDT_timestamp"

# Pending signals queue (for scoring when multiple arrive)
pending_signals: List[Dict[str, Any]] = []
signal_batch_window_ms = 500  # Wait this long to collect signals before scoring
last_signal_time: Optional[float] = None
signal_processor_lock = threading.Lock()


def init_executor():
    """Initialize Bybit executor"""
    global executor, trailing_monitor
    if executor is None:
        executor = BybitExecutor()
    if trailing_monitor is None:
        trailing_monitor = TrailingSLMonitor(executor)
        trailing_monitor.start()
    return executor


def verify_webhook(payload: bytes, signature: str) -> bool:
    """Verify webhook signature (optional)"""
    if not config.webhook_secret:
        return True
    expected = hmac.new(
        config.webhook_secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)


def ensure_usdt_suffix(symbol: str) -> str:
    """Ensure symbol has USDT suffix for Bybit"""
    symbol = symbol.upper().replace("/", "")
    if not symbol.endswith('USDT'):
        symbol = symbol + 'USDT'
    return symbol


# =============================================================================
# SCORING SYSTEM (for trade selection when multiple signals)
# =============================================================================

# Cache for symbol winrates (avoid DB calls every signal)
_winrate_cache: Dict[str, Dict[str, Any]] = {}
_winrate_cache_ttl = 300  # 5 minutes


def get_cached_winrate(symbol: str) -> Dict[str, Any]:
    """Get winrate from cache or DB"""
    import time
    now = time.time()

    if symbol in _winrate_cache:
        cached = _winrate_cache[symbol]
        if now - cached.get('_cached_at', 0) < _winrate_cache_ttl:
            return cached

    # Fetch from DB
    logger = get_trade_logger()
    winrate_data = logger.get_symbol_winrate(symbol)
    winrate_data['_cached_at'] = now
    _winrate_cache[symbol] = winrate_data

    return winrate_data


def calculate_signal_score(data: Dict[str, Any], direction: str, include_history: bool = True) -> float:
    """
    Calculate a score for a trading signal based on ML features.
    Higher score = better trade opportunity.

    Features:
    - RSI: For longs, lower is better (oversold). For shorts, higher is better.
    - Volume Ratio: Higher is better (more confirmation)
    - ATR %: Sweet spot around 2-4% is ideal
    - Historical Winrate: Weighted by confidence (more trades = more weight)
    """
    score = 0.0

    # RSI scoring (0-100 scale)
    rsi = float(data.get('rsi', 50))
    if direction == 'long':
        # For longs: RSI < 30 is best, RSI > 70 is worst
        if rsi < 20:
            score += 4
        elif rsi < 30:
            score += 3
        elif rsi < 40:
            score += 2
        elif rsi < 50:
            score += 1
        elif rsi > 70:
            score -= 2
    else:
        # For shorts: RSI > 70 is best, RSI < 30 is worst
        if rsi > 80:
            score += 4
        elif rsi > 70:
            score += 3
        elif rsi > 60:
            score += 2
        elif rsi > 50:
            score += 1
        elif rsi < 30:
            score -= 2

    # Volume Ratio scoring (higher = more confirmation)
    vol_ratio = float(data.get('volumeRatio', 1.0))
    if vol_ratio > 2.5:
        score += 3
    elif vol_ratio > 1.5:
        score += 2
    elif vol_ratio > 1.0:
        score += 1
    elif vol_ratio < 0.5:
        score -= 1  # Low volume = weak signal

    # ATR % scoring (sweet spot: 2-4%)
    atr_pct = float(data.get('atrPercent', 2.0))
    if 2.0 <= atr_pct <= 4.0:
        score += 2  # Ideal volatility
    elif 1.0 <= atr_pct < 2.0 or 4.0 < atr_pct <= 6.0:
        score += 1  # Acceptable
    elif atr_pct > 8.0:
        score -= 1  # Too volatile
    elif atr_pct < 0.5:
        score -= 1  # Too quiet

    # Historical winrate scoring (confidence-weighted)
    if include_history:
        symbol = ensure_usdt_suffix(data.get('coin', ''))
        winrate_data = get_cached_winrate(symbol)

        winrate = winrate_data.get('winrate', 0.5)
        confidence = winrate_data.get('confidence', 0)
        total_trades = winrate_data.get('total', 0)

        # Winrate contribution: -3 to +3, weighted by confidence
        # 50% winrate = 0, 80% = +3, 20% = -3
        winrate_score = (winrate - 0.5) * 6  # Range: -3 to +3
        winrate_score *= confidence  # Weight by confidence

        score += winrate_score

        # Bonus for coins with proven track record (10+ trades with >60% WR)
        if total_trades >= 10 and winrate >= 0.6:
            score += 1

    return score


# =============================================================================
# SHADOW TRADE TRACKING (for ML data collection)
# =============================================================================

def create_shadow_trade(data: Dict[str, Any], reason: str) -> str:
    """
    Create a shadow trade entry for ML tracking.
    Shadow trades are signals we didn't execute but want to track outcomes.
    """
    symbol = ensure_usdt_suffix(data.get('coin', ''))
    direction = data.get('direction', '').lower()
    entry = float(data.get('entry', 0))
    tp = float(data.get('tp', 0))
    sl = float(data.get('sl', 0))

    shadow_id = f"{direction.upper()}_{symbol}_{int(time.time() * 1000)}"

    shadow_trades[shadow_id] = {
        'id': shadow_id,
        'symbol': symbol,
        'direction': direction,
        'entry': entry,
        'tp': tp,
        'sl': sl,
        'reason': reason,  # Why it wasn't executed
        'created_at': datetime.utcnow(),
        'rsi': float(data.get('rsi', 0)),
        'volume_ratio': float(data.get('volumeRatio', 0)),
        'atr_percent': float(data.get('atrPercent', 0)),
        'score': calculate_signal_score(data, direction),
        'status': 'ACTIVE',  # ACTIVE, WIN, LOSS
        'outcome': None,
        'exit_time': None,
    }

    print(f"[SHADOW] Created shadow trade: {shadow_id} (reason: {reason})")

    # Log to Supabase
    logger = get_trade_logger()
    if hasattr(logger, 'log_shadow_trade'):
        logger.log_shadow_trade(shadow_trades[shadow_id])

    return shadow_id


def check_shadow_trades():
    """
    Background task to check shadow trades for TP/SL hits.
    Called periodically by the shadow monitor thread.
    """
    if not executor or not shadow_trades:
        return

    # Get current prices for all symbols with shadow trades
    symbols_to_check = set(st['symbol'] for st in shadow_trades.values() if st['status'] == 'ACTIVE')

    for symbol in symbols_to_check:
        try:
            # Get current price
            ticker = executor.session.get_tickers(category="linear", symbol=symbol)
            if ticker and 'result' in ticker and 'list' in ticker['result'] and ticker['result']['list']:
                current_price = float(ticker['result']['list'][0]['lastPrice'])

                # Check all active shadow trades for this symbol
                for shadow_id, shadow in list(shadow_trades.items()):
                    if shadow['symbol'] != symbol or shadow['status'] != 'ACTIVE':
                        continue

                    entry = shadow['entry']
                    tp = shadow['tp']
                    sl = shadow['sl']
                    direction = shadow['direction']

                    outcome = None

                    if direction == 'long':
                        if current_price >= tp:
                            outcome = 'WIN'
                        elif current_price <= sl:
                            outcome = 'LOSS'
                    else:  # short
                        if current_price <= tp:
                            outcome = 'WIN'
                        elif current_price >= sl:
                            outcome = 'LOSS'

                    if outcome:
                        shadow_trades[shadow_id]['status'] = outcome
                        shadow_trades[shadow_id]['outcome'] = outcome
                        shadow_trades[shadow_id]['exit_time'] = datetime.utcnow()
                        shadow_trades[shadow_id]['exit_price'] = current_price

                        print(f"[SHADOW] {shadow_id} -> {outcome} (price: {current_price})")

                        # Log to Supabase
                        logger = get_trade_logger()
                        if hasattr(logger, 'update_shadow_trade'):
                            logger.update_shadow_trade(shadow_id, outcome, current_price)

        except Exception as e:
            print(f"[SHADOW] Error checking {symbol}: {e}")


def start_shadow_monitor():
    """Start background thread to monitor shadow trades"""
    def monitor_loop():
        while True:
            try:
                check_shadow_trades()
            except Exception as e:
                print(f"[SHADOW] Monitor error: {e}")
            time.sleep(30)  # Check every 30 seconds

    thread = threading.Thread(target=monitor_loop, daemon=True)
    thread.start()
    print("[SHADOW] Shadow trade monitor started")


# =============================================================================
# WEBHOOK ENDPOINTS
# =============================================================================

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    active_shadows = sum(1 for s in shadow_trades.values() if s['status'] == 'ACTIVE')
    return jsonify({
        'status': 'ok',
        'time': datetime.utcnow().isoformat(),
        'testnet': config.api.testnet,
        'pending_orders': len(pending_orders),
        'ready_states': len(ready_states),
        'shadow_trades': {'active': active_shadows, 'total': len(shadow_trades)}
    })


@app.route('/webhook', methods=['POST'])
def webhook():
    """
    TradingView webhook endpoint.

    Accepts Universal Backtester alert format:
    {
        "type": "READY|UPDATE|TRIGGERED|EXIT|CANCELLED",
        "direction": "LONG|SHORT",
        "coin": "BTCUSDT",
        "entry": 50000.0,
        "tp": 50500.0,
        "sl": 49500.0,
        "atr": 200.0,
        "zoneWidth": 300.0,
        "barsReady": 3,
        "outcome": "WIN|LOSS",
        "exitPrice": 50500.0,
        "time": "2024-01-15T10:30:00"
    }
    """
    try:
        # Verify signature if configured
        if config.webhook_secret:
            signature = request.headers.get('X-Signature', '')
            if not verify_webhook(request.data, signature):
                return jsonify({'error': 'Invalid signature'}), 401

        data = request.json
        if not data:
            return jsonify({'error': 'No JSON data'}), 400

        print(f"\n[WEBHOOK] Received: {json.dumps(data, indent=2)}")

        alert_type = data.get('type', '').upper()

        if alert_type == 'READY':
            return handle_ready(data)
        elif alert_type == 'UPDATE':
            return handle_update(data)
        elif alert_type == 'TRIGGERED':
            return handle_triggered(data)
        elif alert_type == 'EXIT':
            return handle_exit(data)
        elif alert_type == 'CANCELLED':
            return handle_cancelled(data)
        else:
            # Fallback: try legacy format (action=entry)
            action = data.get('action', '')
            if action == 'entry':
                return handle_legacy_entry(data)
            return jsonify({'error': f'Unknown alert type: {alert_type}'}), 400

    except Exception as e:
        print(f"[ERROR] Webhook error: {e}")
        telegram_alerts.send_error_alert(str(e), "Webhook handler")
        return jsonify({'error': str(e)}), 500


def handle_ready(data: Dict[str, Any]):
    """
    Handle READY alert - Step 1 triggered, watching for Step 2.
    Log state and send Telegram notification.
    """
    symbol = ensure_usdt_suffix(data.get('coin', ''))
    direction = data.get('direction', '').upper()
    entry = float(data.get('entry', 0))
    tp = float(data.get('tp', 0))
    sl = float(data.get('sl', 0))
    atr = float(data.get('atr', 0)) if data.get('atr') else None
    zone_width = float(data.get('zoneWidth', 0)) if data.get('zoneWidth') else None

    # Store ready state
    key = f"{direction}_{symbol}"
    ready_states[key] = {
        'symbol': symbol,
        'direction': direction,
        'entry': entry,
        'tp': tp,
        'sl': sl,
        'atr': atr,
        'zone_width': zone_width,
        'time': datetime.utcnow(),
        'bars_ready': 0,
    }

    print(f"[READY] {direction} {symbol} - Entry: {entry}, TP: {tp}, SL: {sl}")

    # Telegram notification
    telegram_alerts.send_ready_state(
        symbol=symbol,
        direction=direction.lower(),
        entry=entry,
        tp=tp,
        sl=sl,
        atr=atr,
        zone_width=zone_width,
    )

    return jsonify({'status': 'ok', 'type': 'ready', 'symbol': symbol, 'direction': direction})


def handle_update(data: Dict[str, Any]):
    """
    Handle UPDATE alert - Still in ready state, updated projected levels.
    """
    symbol = ensure_usdt_suffix(data.get('coin', ''))
    direction = data.get('direction', '').upper()
    key = f"{direction}_{symbol}"

    if key in ready_states:
        ready_states[key]['entry'] = float(data.get('entry', ready_states[key]['entry']))
        ready_states[key]['tp'] = float(data.get('tp', ready_states[key]['tp']))
        ready_states[key]['sl'] = float(data.get('sl', ready_states[key]['sl']))
        ready_states[key]['bars_ready'] = int(data.get('barsReady', 0))

    return jsonify({'status': 'ok', 'type': 'update'})


def handle_triggered(data: Dict[str, Any]):
    """
    Handle TRIGGERED alert - Signal fired, place order on Bybit.
    This is the main action handler.
    """
    symbol = ensure_usdt_suffix(data.get('coin', ''))
    direction = data.get('direction', '').lower()
    entry = float(data.get('entry', 0))
    tp = float(data.get('tp', 0))
    sl = float(data.get('sl', 0))

    # Validate
    if not symbol or not direction or not entry or not sl:
        return jsonify({'error': 'Missing required fields (coin, direction, entry, sl)'}), 400

    if direction not in ['long', 'short']:
        return jsonify({'error': 'Invalid direction'}), 400

    # Get ready state context (if available)
    key = f"{direction.upper()}_{symbol}"
    ready_context = ready_states.pop(key, {})
    atr_value = ready_context.get('atr')
    zone_width = ready_context.get('zone_width')
    bars_in_ready = ready_context.get('bars_ready', 0)

    print(f"\n{'='*50}")
    print(f"[TRIGGERED] {direction.upper()} {symbol}")
    print(f"  Entry: {entry}")
    print(f"  SL: {sl} ({abs(entry-sl)/entry*100:.2f}%)")
    print(f"  TP: {tp} ({abs(tp-entry)/entry*100:.2f}%)")

    # Initialize executor
    init_executor()

    # Check max positions limit
    positions = executor.get_all_positions()
    long_count = sum(1 for p in positions if p.side.lower() == 'buy')
    short_count = sum(1 for p in positions if p.side.lower() == 'sell')

    # Calculate score for this signal (includes historical winrate)
    signal_score = calculate_signal_score(data, direction)
    winrate_data = get_cached_winrate(symbol)
    wr_str = f"{winrate_data['wins']}/{winrate_data['total']}" if winrate_data['total'] > 0 else "new"
    print(f"  Score: {signal_score:.1f} (RSI={data.get('rsi', 'N/A')}, Vol={data.get('volumeRatio', 'N/A')}, ATR%={data.get('atrPercent', 'N/A')}, WR={wr_str})")

    if direction == 'long' and long_count >= config.risk.max_longs:
        msg = f"Max longs reached ({config.risk.max_longs}), creating shadow trade for {symbol}"
        print(f"  [SHADOW] {msg}")
        shadow_id = create_shadow_trade(data, "max_longs_reached")
        return jsonify({'status': 'shadow', 'reason': msg, 'shadow_id': shadow_id, 'score': signal_score}), 200

    if direction == 'short' and short_count >= config.risk.max_shorts:
        msg = f"Max shorts reached ({config.risk.max_shorts}), creating shadow trade for {symbol}"
        print(f"  [SHADOW] {msg}")
        shadow_id = create_shadow_trade(data, "max_shorts_reached")
        return jsonify({'status': 'shadow', 'reason': msg, 'shadow_id': shadow_id, 'score': signal_score}), 200

    # Check if this specific coin already has an open position
    existing_position = next((p for p in positions if p.symbol == symbol), None)
    if existing_position:
        msg = f"{symbol} already has open {existing_position.side} position, creating shadow trade"
        print(f"  [SHADOW] {msg}")
        shadow_id = create_shadow_trade(data, "duplicate_position")
        return jsonify({'status': 'shadow', 'reason': msg, 'shadow_id': shadow_id, 'score': signal_score}), 200

    # Get account equity
    equity = executor.get_account_equity()
    if equity <= 0:
        return jsonify({'error': 'Could not get account equity'}), 500

    print(f"  Equity: ${equity:.2f}")

    # Get symbol info
    symbol_info = executor.get_symbol_info(symbol)

    # Set leverage
    leverage = config.risk.default_leverage
    executor.set_leverage(symbol, leverage)

    # Calculate position size
    risk_pct = config.risk.max_risk_per_trade_pct
    qty = executor.calculate_position_size(equity, risk_pct, entry, sl, leverage)
    print(f"  Qty: {qty:.6f} (${qty * entry:.2f} notional)")
    print(f"  Risk: {risk_pct}% of ${equity:.2f} = ${equity * risk_pct / 100:.2f}")

    # Place order
    tp_mode = config.risk.tp_mode
    order_id = executor.place_order(
        symbol=symbol,
        direction=direction,
        qty=executor.round_qty(qty, symbol_info['qty_step']),
        entry=entry,
        sl=sl,
        tp=tp,
        symbol_info=symbol_info,
        tp_mode=tp_mode
    )

    if order_id:
        # Track pending order
        pending_orders[order_id] = {
            'symbol': symbol,
            'direction': direction,
            'created_at': datetime.utcnow(),
            'entry': entry,
            'tp': tp,
            'sl': sl,
        }

        # Log to Supabase
        logger = get_trade_logger()
        trade_record = TradeRecord(
            symbol=symbol,
            direction=direction,
            entry_price=entry,
            entry_time=datetime.utcnow(),
            qty=executor.round_qty(qty, symbol_info['qty_step']),
            leverage=leverage,
            margin_used=qty * entry / leverage,
            equity_at_entry=equity,
            sl_price=sl,
            tp_price=tp,
            order_id=order_id,
            risk_pct=risk_pct,
            risk_amount=equity * risk_pct / 100,
            atr_value=atr_value,
            zone_width=zone_width,
            bars_in_ready=bars_in_ready,
        )
        trade_id = logger.log_entry(trade_record)

        if trade_id:
            pending_orders[order_id]['trade_id'] = trade_id

        # Start trailing SL monitoring for this position
        if trailing_monitor:
            trailing_monitor.track_position(symbol, direction, entry, tp, sl)

        # Telegram notification
        telegram_alerts.send_trade_opened(
            symbol=symbol,
            direction=direction,
            entry_price=entry,
            sl_price=sl,
            tp_price=tp,
            leverage=leverage,
            risk_pct=risk_pct,
            qty=executor.round_qty(qty, symbol_info['qty_step']),
        )

        return jsonify({
            'status': 'success',
            'order_id': order_id,
            'symbol': symbol,
            'direction': direction,
            'qty': qty,
            'entry': entry,
            'tp': tp,
            'sl': sl,
        })
    else:
        telegram_alerts.send_error_alert(
            f"Failed to place {direction} order for {symbol}",
            f"Entry={entry}, TP={tp}, SL={sl}"
        )
        return jsonify({'error': 'Failed to place order'}), 500


def handle_exit(data: Dict[str, Any]):
    """
    Handle EXIT alert - Trade closed (TP or SL hit).
    Log result to Supabase and send Telegram.
    """
    symbol = ensure_usdt_suffix(data.get('coin', ''))
    direction = data.get('direction', '').lower()
    outcome = data.get('outcome', '').upper()  # "WIN" or "LOSS"
    exit_price = float(data.get('exitPrice', 0))

    print(f"[EXIT] {direction.upper()} {symbol} -> {outcome} @ {exit_price}")

    # Find the open trade in Supabase
    logger = get_trade_logger()
    open_trade = logger.find_open_trade(symbol, direction)

    if open_trade:
        trade_id = open_trade['id']
        entry_price = open_trade['entry_price']
        entry_time = datetime.fromisoformat(open_trade['entry_time'])
        margin_used = open_trade.get('margin_used', 0)
        equity = open_trade.get('equity_at_entry', 0)
        leverage = open_trade.get('leverage', config.risk.default_leverage)

        # Calculate PnL
        if direction == 'long':
            price_change_pct = ((exit_price - entry_price) / entry_price) * 100
        else:
            price_change_pct = ((entry_price - exit_price) / entry_price) * 100

        pnl_pct = price_change_pct * leverage
        pnl_amount = margin_used * (pnl_pct / 100) if margin_used else 0

        is_win = outcome == "WIN"
        exit_reason = "tp" if is_win else "sl"
        exit_time = datetime.utcnow()

        # Log exit to Supabase
        logger.log_exit(
            trade_id=trade_id,
            exit_price=exit_price,
            exit_time=exit_time,
            exit_reason=exit_reason,
            realized_pnl=pnl_amount,
            equity_at_close=equity + pnl_amount,
            is_win=is_win,
            entry_time=entry_time,
            margin_used=margin_used,
        )

        # Duration
        duration_mins = int((exit_time - entry_time).total_seconds() / 60)

        # Telegram notification
        telegram_alerts.send_trade_closed(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            pnl_pct=pnl_pct,
            outcome=outcome,
            duration_mins=duration_mins,
        )

        # Stop trailing SL monitoring
        if trailing_monitor:
            trailing_monitor.untrack_position(symbol)

        # Clean up pending orders for this symbol
        to_remove = [oid for oid, info in pending_orders.items() if info['symbol'] == symbol]
        for oid in to_remove:
            pending_orders.pop(oid, None)

        return jsonify({
            'status': 'success',
            'type': 'exit',
            'symbol': symbol,
            'outcome': outcome,
            'pnl': pnl_amount,
        })
    else:
        print(f"[WARN] No open trade found for {direction} {symbol}")
        return jsonify({'status': 'ok', 'type': 'exit', 'warning': 'No open trade found'})


def handle_cancelled(data: Dict[str, Any]):
    """
    Handle CANCELLED alert - Ready state expired without triggering.
    """
    symbol = ensure_usdt_suffix(data.get('coin', ''))
    direction = data.get('direction', '').upper()

    key = f"{direction}_{symbol}"
    ready_states.pop(key, None)

    print(f"[CANCELLED] {direction} {symbol}")

    telegram_alerts.send_ready_cancelled(symbol, direction.lower())

    return jsonify({'status': 'ok', 'type': 'cancelled'})


def handle_legacy_entry(data: Dict[str, Any]):
    """
    Handle legacy format: {"action":"entry","symbol":"...","direction":"...","entry":...,"sl":...,"tp1":...}
    Converts to TRIGGERED format internally.
    """
    triggered_data = {
        'type': 'TRIGGERED',
        'coin': data.get('symbol', ''),
        'direction': data.get('direction', '').upper(),
        'entry': data.get('entry', 0),
        'sl': data.get('sl', 0),
        'tp': data.get('tp1', data.get('tp', 0)),
    }
    return handle_triggered(triggered_data)


# =============================================================================
# STATUS ENDPOINTS
# =============================================================================

@app.route('/status', methods=['GET'])
def status():
    """Get current bot status"""
    init_executor()

    try:
        equity = executor.get_account_equity()
        positions = executor.get_all_positions()

        return jsonify({
            'status': 'ok',
            'equity': equity,
            'positions': [
                {
                    'symbol': p.symbol,
                    'side': p.side,
                    'size': p.size,
                    'entry': p.entry_price,
                    'pnl': p.unrealized_pnl,
                    'tp': p.take_profit,
                    'sl': p.stop_loss,
                }
                for p in positions
            ],
            'pending_orders': len(pending_orders),
            'ready_states': list(ready_states.keys()),
            'testnet': config.api.testnet,
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/orders', methods=['GET'])
def orders():
    """Get pending orders"""
    return jsonify({
        'pending_orders': [
            {
                'order_id': oid,
                'symbol': info['symbol'],
                'direction': info['direction'],
                'age_minutes': (datetime.utcnow() - info['created_at']).total_seconds() / 60
            }
            for oid, info in pending_orders.items()
        ]
    })


@app.route('/close', methods=['POST'])
def close_position():
    """Manual close position via API"""
    data = request.json or {}
    symbol = ensure_usdt_suffix(data.get('symbol', ''))

    if not symbol:
        return jsonify({'error': 'Missing symbol'}), 400

    init_executor()
    success = executor.close_position(symbol)

    return jsonify({'status': 'success' if success else 'failed', 'symbol': symbol})


@app.route('/shadows', methods=['GET'])
def get_shadow_trades():
    """Get shadow trades for ML analysis"""
    status_filter = request.args.get('status', None)  # ACTIVE, WIN, LOSS

    filtered = shadow_trades.values()
    if status_filter:
        filtered = [s for s in filtered if s['status'] == status_filter.upper()]

    # Calculate statistics
    all_shadows = list(shadow_trades.values())
    wins = sum(1 for s in all_shadows if s['outcome'] == 'WIN')
    losses = sum(1 for s in all_shadows if s['outcome'] == 'LOSS')
    active = sum(1 for s in all_shadows if s['status'] == 'ACTIVE')

    return jsonify({
        'stats': {
            'total': len(all_shadows),
            'active': active,
            'wins': wins,
            'losses': losses,
            'winrate': f"{wins/(wins+losses)*100:.1f}%" if (wins + losses) > 0 else "N/A"
        },
        'shadows': [
            {
                'id': s['id'],
                'symbol': s['symbol'],
                'direction': s['direction'],
                'entry': s['entry'],
                'tp': s['tp'],
                'sl': s['sl'],
                'reason': s['reason'],
                'score': s['score'],
                'rsi': s['rsi'],
                'volume_ratio': s['volume_ratio'],
                'atr_percent': s['atr_percent'],
                'status': s['status'],
                'outcome': s['outcome'],
                'created_at': s['created_at'].isoformat() if s['created_at'] else None,
                'exit_time': s['exit_time'].isoformat() if s.get('exit_time') else None,
            }
            for s in sorted(filtered, key=lambda x: x['created_at'], reverse=True)[:50]  # Last 50
        ]
    })


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    port = config.port

    print(f"\n{'='*50}")
    print(f"S-O Trading System - Webhook Server")
    print(f"{'='*50}")
    print(f"Port: {port}")
    print(f"Testnet: {config.api.testnet}")
    print(f"Leverage: {config.risk.default_leverage}x")
    print(f"Risk per Trade: {config.risk.max_risk_per_trade_pct}%")
    print(f"TP Mode: {config.risk.tp_mode}")
    print(f"Max Longs: {config.risk.max_longs}")
    print(f"Max Shorts: {config.risk.max_shorts}")
    print(f"Trailing SL: {'ON' if config.risk.trail_enabled else 'OFF'} "
          f"({config.risk.trail_tp_threshold_pct}% TP -> SL at {config.risk.trail_sl_move_pct}%)")
    print(f"{'='*50}\n")

    # Initialize executor
    init_executor()

    # Start shadow trade monitor (for ML data collection)
    start_shadow_monitor()

    # Send bot started notification
    equity = executor.get_account_equity()
    positions = executor.get_all_positions()
    telegram_alerts.send_bot_started(equity=equity, active_positions=len(positions))

    app.run(host='0.0.0.0', port=port, debug=False)
