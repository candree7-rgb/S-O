"""
S-O Trading System - Telegram Alerts
=====================================
Notifications for trade events and summaries.

Setup:
1. Create bot with @BotFather on Telegram
2. Get bot token
3. Start chat with bot, send any message
4. Get chat ID: https://api.telegram.org/bot<TOKEN>/getUpdates
5. Set env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""

import os
import logging
import requests
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

log = logging.getLogger("telegram")

# Config
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
BOT_NAME = os.getenv('BOT_NAME', 'S-O Trader')
TIMEZONE = ZoneInfo('Europe/Berlin')


def is_enabled() -> bool:
    """Check if Telegram is configured."""
    return bool(TELEGRAM_BOT_TOKEN) and bool(TELEGRAM_CHAT_ID)


def send_message(text: str, silent: bool = False) -> bool:
    """Send message to Telegram. Returns True on success."""
    if not is_enabled():
        return False

    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_notification": silent,
        }
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            log.debug(f"Telegram sent: {text[:50]}...")
            return True
        else:
            log.warning(f"Telegram error: {resp.status_code}")
            return False
    except Exception as e:
        log.warning(f"Telegram failed: {e}")
        return False


# ============================================
# READY STATE ALERTS
# ============================================

def send_ready_state(
    symbol: str,
    direction: str,
    entry: float,
    tp: float,
    sl: float,
    atr: float = None,
    zone_width: float = None,
) -> bool:
    """Send notification when signal enters READY state (Step 1 triggered)."""
    if not is_enabled():
        return False

    emoji = "🟡"
    dir_text = direction.upper()

    sl_dist = abs(entry - sl) / entry * 100
    tp_dist = abs(tp - entry) / entry * 100
    rr = tp_dist / sl_dist if sl_dist > 0 else 0

    lines = [
        f"{emoji} <b>READY - Watching</b>",
        "",
        f"<b>{symbol}</b> {dir_text}",
        "",
        f"Projected Entry: {entry:.6f}",
        f"TP: {tp:.6f} ({tp_dist:.2f}%)",
        f"SL: {sl:.6f} ({sl_dist:.2f}%)",
        f"R:R = 1:{rr:.1f}",
    ]

    if atr:
        lines.append(f"ATR: {atr:.6f}")
    if zone_width:
        lines.append(f"Zone Width: {zone_width:.6f}")

    lines.append("")
    lines.append(f"<i>{BOT_NAME}</i>")

    return send_message("\n".join(lines), silent=True)


def send_ready_cancelled(symbol: str, direction: str) -> bool:
    """Send notification when READY state is cancelled."""
    if not is_enabled():
        return False

    lines = [
        f"⚪ <b>CANCELLED</b>",
        "",
        f"<b>{symbol}</b> {direction.upper()}",
        "Signal expired without triggering",
        "",
        f"<i>{BOT_NAME}</i>",
    ]

    return send_message("\n".join(lines), silent=True)


# ============================================
# TRADE ALERTS
# ============================================

def send_trade_opened(
    symbol: str,
    direction: str,
    entry_price: float,
    sl_price: float,
    tp_price: float,
    leverage: int,
    risk_pct: float,
    qty: float = None,
) -> bool:
    """Send notification when new trade is opened (TRIGGERED)."""
    if not is_enabled():
        return False

    emoji = "🔴" if direction.lower() == 'short' else "🟢"
    dir_text = direction.upper()

    sl_dist = abs(entry_price - sl_price) / entry_price * 100
    tp_dist = abs(tp_price - entry_price) / entry_price * 100

    lines = [
        f"{emoji} <b>TRADE OPENED</b>",
        "",
        f"<b>{symbol}</b> {dir_text}",
        f"Leverage: {leverage}x",
        "",
        f"Entry: {entry_price:.6f}",
        f"SL: {sl_price:.6f} ({sl_dist:.2f}%)",
        f"TP: {tp_price:.6f} ({tp_dist:.2f}%)",
        "",
        f"Risk: {risk_pct:.1f}%",
    ]

    if qty:
        lines.append(f"Qty: {qty:.6f}")

    lines.append("")
    lines.append(f"<i>{BOT_NAME}</i>")

    return send_message("\n".join(lines))


def send_trade_closed(
    symbol: str,
    direction: str,
    entry_price: float,
    exit_price: float,
    pnl_pct: float,
    outcome: str,
    duration_mins: int = None,
) -> bool:
    """Send notification when trade is closed (EXIT)."""
    if not is_enabled():
        return False

    is_win = outcome.upper() == "WIN"
    emoji = "✅" if is_win else "❌"
    result = "WIN" if is_win else "LOSS"
    dir_text = direction.upper()

    pnl_str = f"+{pnl_pct:.2f}%" if pnl_pct > 0 else f"{pnl_pct:.2f}%"

    lines = [
        f"{emoji} <b>TRADE CLOSED: {result}</b>",
        "",
        f"<b>{symbol}</b> {dir_text}",
        "",
        f"Entry: {entry_price:.6f}",
        f"Exit: {exit_price:.6f}",
        f"PnL: <b>{pnl_str}</b>",
        f"Exit: {'Take Profit' if is_win else 'Stop Loss'}",
    ]

    if duration_mins is not None:
        if duration_mins < 60:
            dur_str = f"{duration_mins}m"
        elif duration_mins < 1440:
            dur_str = f"{duration_mins // 60}h {duration_mins % 60}m"
        else:
            dur_str = f"{duration_mins // 1440}d {(duration_mins % 1440) // 60}h"
        lines.append(f"Duration: {dur_str}")

    lines.append("")
    lines.append(f"<i>{BOT_NAME}</i>")

    return send_message("\n".join(lines))


# ============================================
# SUMMARY REPORTS
# ============================================

def send_daily_summary(
    trades_opened: int,
    trades_closed: int,
    wins: int,
    losses: int,
    total_pnl_pct: float,
    best_trade_pct: float = None,
    worst_trade_pct: float = None,
    equity_change_pct: float = None,
) -> bool:
    """Send daily summary."""
    if not is_enabled():
        return False

    now = datetime.now(TIMEZONE)
    date_str = (now - timedelta(days=1)).strftime("%d.%m.%Y")

    win_rate = (wins / trades_closed * 100) if trades_closed > 0 else 0
    emoji = "📈" if total_pnl_pct >= 0 else "📉"
    pnl_str = f"+{total_pnl_pct:.2f}%" if total_pnl_pct >= 0 else f"{total_pnl_pct:.2f}%"

    lines = [
        f"📊 <b>DAILY REPORT</b>",
        f"<i>{date_str}</i>",
        "",
        f"Trades Opened: {trades_opened}",
        f"Trades Closed: {trades_closed}",
        "",
        f"Wins: {wins}",
        f"Losses: {losses}",
        f"Win Rate: {win_rate:.1f}%",
        "",
        f"{emoji} Day PnL: <b>{pnl_str}</b>",
    ]

    if best_trade_pct is not None:
        lines.append(f"Best Trade: +{best_trade_pct:.2f}%")
    if worst_trade_pct is not None:
        lines.append(f"Worst Trade: {worst_trade_pct:.2f}%")
    if equity_change_pct is not None:
        eq_str = f"+{equity_change_pct:.2f}%" if equity_change_pct >= 0 else f"{equity_change_pct:.2f}%"
        lines.append(f"Equity: {eq_str}")

    lines.append("")
    lines.append(f"<i>{BOT_NAME}</i>")

    return send_message("\n".join(lines))


def send_weekly_summary(
    trades_closed: int,
    wins: int,
    losses: int,
    total_pnl_pct: float,
    avg_win_pct: float = None,
    avg_loss_pct: float = None,
    equity_change_pct: float = None,
) -> bool:
    """Send weekly summary."""
    if not is_enabled():
        return False

    now = datetime.now(TIMEZONE)
    week_start = (now - timedelta(days=7)).strftime("%d.%m")
    week_end = (now - timedelta(days=1)).strftime("%d.%m.%Y")

    win_rate = (wins / trades_closed * 100) if trades_closed > 0 else 0
    emoji = "📈" if total_pnl_pct >= 0 else "📉"
    pnl_str = f"+{total_pnl_pct:.2f}%" if total_pnl_pct >= 0 else f"{total_pnl_pct:.2f}%"

    lines = [
        f"📅 <b>WEEKLY REPORT</b>",
        f"<i>{week_start} - {week_end}</i>",
        "",
        f"Total Trades: {trades_closed}",
        f"Wins: {wins} | Losses: {losses}",
        f"Win Rate: <b>{win_rate:.1f}%</b>",
        "",
        f"{emoji} Week PnL: <b>{pnl_str}</b>",
    ]

    if avg_win_pct is not None:
        lines.append(f"Avg Win: +{avg_win_pct:.2f}%")
    if avg_loss_pct is not None:
        lines.append(f"Avg Loss: {avg_loss_pct:.2f}%")
    if equity_change_pct is not None:
        eq_str = f"+{equity_change_pct:.2f}%" if equity_change_pct >= 0 else f"{equity_change_pct:.2f}%"
        lines.append(f"Equity Change: {eq_str}")

    lines.append("")
    lines.append(f"<i>{BOT_NAME}</i>")

    return send_message("\n".join(lines))


# ============================================
# STATUS ALERTS
# ============================================

def send_bot_started(equity: float = None, active_positions: int = 0) -> bool:
    """Send notification when server starts."""
    if not is_enabled():
        return False

    now = datetime.now(TIMEZONE).strftime("%H:%M %d.%m.%Y")

    lines = [
        f"🤖 <b>{BOT_NAME} STARTED</b>",
        "",
        f"Time: {now}",
    ]

    if equity:
        lines.append(f"Equity: ${equity:.2f}")
    if active_positions > 0:
        lines.append(f"Active Positions: {active_positions}")

    lines.append("")
    lines.append("Webhook server ready!")

    return send_message("\n".join(lines))


def send_trailing_sl_moved(symbol: str, direction: str, old_sl: float, new_sl: float, entry: float) -> bool:
    """Send notification when trailing SL is activated."""
    if not is_enabled():
        return False

    emoji = "🔒"
    dir_text = direction.upper()
    profit_locked = abs(new_sl - entry) / entry * 100

    lines = [
        f"{emoji} <b>SL MOVED TO PROFIT</b>",
        "",
        f"<b>{symbol}</b> {dir_text}",
        "",
        f"Entry: {entry:.6f}",
        f"Old SL: {old_sl:.6f}",
        f"New SL: <b>{new_sl:.6f}</b>",
        f"Profit Locked: {profit_locked:.2f}%",
        "",
        f"<i>{BOT_NAME}</i>",
    ]

    return send_message("\n".join(lines))


def send_error_alert(error: str, context: str = None) -> bool:
    """Send alert for critical errors."""
    if not is_enabled():
        return False

    lines = [
        f"⚠️ <b>ERROR ALERT</b>",
        "",
        f"Error: {error[:200]}",
    ]

    if context:
        lines.append(f"Context: {context}")

    lines.append("")
    lines.append(f"<i>{BOT_NAME}</i>")

    return send_message("\n".join(lines))


def send_test() -> bool:
    """Send test message to verify setup."""
    if not is_enabled():
        print("[Telegram] Not configured - set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return False

    return send_message(
        f"✅ <b>Test Message</b>\n\n"
        f"Telegram alerts are working!\n\n"
        f"<i>{BOT_NAME}</i>"
    )


if __name__ == '__main__':
    if send_test():
        print("Telegram test successful!")
    else:
        print("Telegram test failed")
