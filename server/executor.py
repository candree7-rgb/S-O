"""
S-O Trading System - Bybit Order Executor
==========================================
Handles order placement, position management, TP/SL on Bybit.
"""

import os
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

from pybit.unified_trading import HTTP

from config import config


@dataclass
class OrderResult:
    """Result of an order execution"""
    success: bool
    order_id: str = None
    filled_price: float = None
    filled_qty: float = None
    error: str = None
    timestamp: datetime = None


@dataclass
class Position:
    """Active position on exchange"""
    symbol: str
    side: str
    size: float
    entry_price: float
    leverage: int
    unrealized_pnl: float
    take_profit: float = None
    stop_loss: float = None


class BybitExecutor:
    """
    Executes orders on Bybit Unified Trading API.
    """

    def __init__(self):
        self.client = HTTP(
            testnet=config.api.testnet,
            api_key=config.api.api_key,
            api_secret=config.api.api_secret,
            recv_window=10000
        )
        print(f"[EXECUTOR] Bybit client initialized (testnet={config.api.testnet})")

    def get_account_equity(self) -> float:
        """Get current account equity in USDT"""
        try:
            result = self.client.get_wallet_balance(accountType="UNIFIED", coin="USDT")
            if result['retCode'] == 0:
                equity = float(result['result']['list'][0]['totalEquity'])
                return equity
        except Exception as e:
            print(f"[ERROR] Failed to get equity: {e}")
        return 0

    def get_balance(self) -> Dict:
        """Get detailed account balance"""
        def safe_float(val, default=0.0):
            if val is None or val == '':
                return default
            try:
                return float(val)
            except (ValueError, TypeError):
                return default

        try:
            response = self.client.get_wallet_balance(accountType="UNIFIED", coin="USDT")
            if response['retCode'] == 0:
                coins = response['result']['list'][0]['coin']
                usdt = next((c for c in coins if c['coin'] == 'USDT'), None)
                if usdt:
                    equity = safe_float(usdt.get('equity'), 0)
                    wallet_balance = safe_float(usdt.get('walletBalance'), 0)
                    available = wallet_balance if wallet_balance > 0 else equity

                    if equity == 0 and available == 0:
                        return {'error': 'No USDT balance. Please add funds.'}

                    return {
                        'equity': equity,
                        'available': available,
                        'wallet_balance': wallet_balance,
                        'unrealized_pnl': safe_float(usdt.get('unrealisedPnl'), 0)
                    }
            return {'error': response.get('retMsg', 'Unknown error')}
        except Exception as e:
            return {'error': str(e)}

    def get_symbol_info(self, symbol: str) -> Dict:
        """Get symbol trading rules (min qty, tick size, etc.)"""
        try:
            result = self.client.get_instruments_info(category="linear", symbol=symbol)
            if result['retCode'] == 0 and result['result']['list']:
                info = result['result']['list'][0]
                return {
                    'min_qty': float(info['lotSizeFilter']['minOrderQty']),
                    'qty_step': float(info['lotSizeFilter']['qtyStep']),
                    'tick_size': float(info['priceFilter']['tickSize']),
                    'min_notional': float(info.get('lotSizeFilter', {}).get('minNotionalValue', 5))
                }
        except Exception as e:
            print(f"[ERROR] Failed to get symbol info: {e}")
        return {'min_qty': 0.001, 'qty_step': 0.001, 'tick_size': 0.01, 'min_notional': 5}

    def round_qty(self, qty: float, step: float) -> float:
        """Round quantity to valid step"""
        return round(qty / step) * step

    def round_price(self, price: float, tick: float) -> float:
        """Round price to valid tick"""
        return round(price / tick) * tick

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for symbol"""
        try:
            response = self.client.set_leverage(
                category="linear",
                symbol=symbol,
                buyLeverage=str(leverage),
                sellLeverage=str(leverage)
            )
            if response['retCode'] == 0 or response['retCode'] == 110043:
                return True
        except Exception as e:
            if '110043' in str(e) or 'not modified' in str(e).lower():
                return True
        return False

    def calculate_position_size(self, equity: float, risk_pct: float,
                                 entry: float, sl: float, leverage: int) -> float:
        """Calculate position size based on risk"""
        risk_amount = equity * (risk_pct / 100)
        sl_distance_pct = abs(entry - sl) / entry

        if sl_distance_pct == 0:
            return 0

        # Position value to achieve desired risk
        position_value = risk_amount / sl_distance_pct

        # Cap at max position size
        max_position_value = equity * (config.risk.max_position_size_pct / 100) * leverage
        position_value = min(position_value, max_position_value)

        # Convert to quantity
        qty = position_value / entry
        return qty

    def place_order(self, symbol: str, direction: str, qty: float,
                    entry: float, sl: float, tp: float,
                    symbol_info: Dict, tp_mode: str = "single") -> Optional[str]:
        """
        Place limit order with TP/SL.

        tp_mode:
          - "single": 100% at TP
          - "split": 50% at TP, 50% at TP2 (TP2 = 2x TP distance)

        Returns order ID if successful.
        """
        try:
            qty = self.round_qty(qty, symbol_info['qty_step'])
            entry = self.round_price(entry, symbol_info['tick_size'])
            sl = self.round_price(sl, symbol_info['tick_size'])
            tp = self.round_price(tp, symbol_info['tick_size'])

            if qty < symbol_info['min_qty']:
                print(f"[WARN] Qty {qty} below minimum {symbol_info['min_qty']}")
                return None

            side = "Buy" if direction.lower() == "long" else "Sell"

            if tp_mode == "single":
                result = self.client.place_order(
                    category="linear",
                    symbol=symbol,
                    side=side,
                    orderType="Limit",
                    qty=str(qty),
                    price=str(entry),
                    stopLoss=str(sl),
                    takeProfit=str(tp),
                    timeInForce="GTC",
                    reduceOnly=False
                )

                if result['retCode'] == 0:
                    order_id = result['result']['orderId']
                    print(f"  [ORDER] {side} {qty} @ {entry}, TP={tp}, SL={sl} -> {order_id[:8]}...")
                    return order_id
                else:
                    print(f"  [ERROR] Order failed: {result['retMsg']}")
                    return None

            else:
                # Split mode: 50% at TP1, 50% at TP2
                tp2_distance = abs(tp - entry) * 2
                if direction.lower() == "long":
                    tp2 = entry + tp2_distance
                else:
                    tp2 = entry - tp2_distance
                tp2 = self.round_price(tp2, symbol_info['tick_size'])

                qty1 = self.round_qty(qty * 0.5, symbol_info['qty_step'])
                qty2 = self.round_qty(qty - qty1, symbol_info['qty_step'])

                # Order 1: 50% with TP1
                result1 = self.client.place_order(
                    category="linear",
                    symbol=symbol,
                    side=side,
                    orderType="Limit",
                    qty=str(qty1),
                    price=str(entry),
                    stopLoss=str(sl),
                    takeProfit=str(tp),
                    timeInForce="GTC",
                    reduceOnly=False
                )

                order_id_1 = None
                if result1['retCode'] == 0:
                    order_id_1 = result1['result']['orderId']
                    print(f"  [ORDER 1] {side} {qty1} @ {entry}, TP1={tp}, SL={sl} -> {order_id_1[:8]}...")
                else:
                    print(f"  [ERROR] Order 1 failed: {result1['retMsg']}")
                    return None

                # Order 2: 50% with TP2
                result2 = self.client.place_order(
                    category="linear",
                    symbol=symbol,
                    side=side,
                    orderType="Limit",
                    qty=str(qty2),
                    price=str(entry),
                    stopLoss=str(sl),
                    takeProfit=str(tp2),
                    timeInForce="GTC",
                    reduceOnly=False
                )

                if result2['retCode'] == 0:
                    order_id_2 = result2['result']['orderId']
                    print(f"  [ORDER 2] {side} {qty2} @ {entry}, TP2={tp2}, SL={sl} -> {order_id_2[:8]}...")

                return order_id_1

        except Exception as e:
            print(f"[ERROR] Place order failed: {e}")
            return None

    def close_position(self, symbol: str) -> bool:
        """Market close a position"""
        try:
            result = self.client.get_positions(category="linear", symbol=symbol)
            if result['retCode'] == 0 and result['result']['list']:
                for pos in result['result']['list']:
                    size = float(pos.get('size', 0))
                    if size > 0:
                        side = "Sell" if pos['side'] == "Buy" else "Buy"
                        self.client.place_order(
                            category="linear",
                            symbol=symbol,
                            side=side,
                            orderType="Market",
                            qty=str(size),
                            reduceOnly=True
                        )
                        print(f"[CLOSE] Market closed {symbol}")
                        return True
        except Exception as e:
            print(f"[ERROR] Close position failed: {e}")
        return False

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for symbol"""
        try:
            response = self.client.get_positions(category="linear", symbol=symbol)
            if response['retCode'] == 0 and response['result']['list']:
                pos = response['result']['list'][0]
                size = float(pos['size'])
                if size > 0:
                    return Position(
                        symbol=symbol,
                        side=pos['side'],
                        size=size,
                        entry_price=float(pos['avgPrice']),
                        leverage=int(pos['leverage']),
                        unrealized_pnl=float(pos['unrealisedPnl']),
                        take_profit=float(pos['takeProfit']) if pos['takeProfit'] else None,
                        stop_loss=float(pos['stopLoss']) if pos['stopLoss'] else None
                    )
        except Exception as e:
            print(f"Error getting position: {e}")
        return None

    def get_all_positions(self) -> List[Position]:
        """Get all open positions"""
        positions = []
        try:
            response = self.client.get_positions(category="linear", settleCoin="USDT")
            if response['retCode'] == 0:
                for pos in response['result']['list']:
                    if float(pos['size']) > 0:
                        positions.append(Position(
                            symbol=pos['symbol'],
                            side=pos['side'],
                            size=float(pos['size']),
                            entry_price=float(pos['avgPrice']),
                            leverage=int(pos['leverage']),
                            unrealized_pnl=float(pos['unrealisedPnl']),
                            take_profit=float(pos['takeProfit']) if pos['takeProfit'] else None,
                            stop_loss=float(pos['stopLoss']) if pos['stopLoss'] else None
                        ))
        except Exception as e:
            print(f"Error getting positions: {e}")
        return positions

    def update_stop_loss(self, symbol: str, side: str, sl: float, symbol_info: Dict = None) -> bool:
        """Update stop loss for an open position"""
        try:
            tick = symbol_info['tick_size'] if symbol_info else 0.01
            sl = self.round_price(sl, tick)

            response = self.client.set_trading_stop(
                category="linear",
                symbol=symbol,
                positionIdx=0,  # one-way mode (cross)
                stopLoss=str(sl),
            )
            if response['retCode'] == 0:
                print(f"  [SL UPDATE] {symbol} new SL={sl}")
                return True
            else:
                print(f"  [ERROR] SL update failed: {response['retMsg']}")
        except Exception as e:
            print(f"[ERROR] Update SL failed: {e}")
        return False

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel a pending order"""
        try:
            response = self.client.cancel_order(
                category="linear",
                symbol=symbol,
                orderId=order_id
            )
            return response['retCode'] == 0
        except Exception as e:
            print(f"Error cancelling order: {e}")
            return False

    def get_open_orders(self, symbol: str = None) -> list:
        """Get all open/pending orders"""
        try:
            params = {"category": "linear", "settleCoin": "USDT"}
            if symbol:
                params["symbol"] = symbol
            response = self.client.get_open_orders(**params)
            if response['retCode'] == 0:
                return response['result']['list']
            return []
        except Exception as e:
            print(f"Error getting open orders: {e}")
            return []
