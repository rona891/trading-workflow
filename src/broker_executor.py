"""
Binance testnet executor — market buy + OCO (SL/TP) orders.
Testnet: https://testnet.binance.vision/
"""
import os
import math
import time
from dotenv import load_dotenv
from binance.client import Client
from binance.exceptions import BinanceAPIException

load_dotenv()

_TESTNET = os.getenv("TESTNET", "true").lower() == "true"
_API_KEY = os.getenv("BINANCE_TESTNET_API_KEY", "")
_SECRET = os.getenv("BINANCE_TESTNET_SECRET", "")


def _get_client() -> Client:
    client = Client(_API_KEY, _SECRET, testnet=_TESTNET)
    return client


def _get_symbol_info(client: Client, symbol: str) -> dict:
    info = client.get_symbol_info(symbol)
    if not info:
        raise ValueError(f"Symbol {symbol} not found on Binance")
    return info


def _extract_filter(info: dict, filter_type: str) -> dict:
    for f in info["filters"]:
        if f["filterType"] == filter_type:
            return f
    return {}


def _round_step(value: float, step: float) -> float:
    precision = int(round(-math.log10(step))) if step < 1 else 0
    return round(round(value / step) * step, precision)


def _round_price(value: float, tick: float) -> float:
    precision = int(round(-math.log10(tick))) if tick < 1 else 0
    return round(round(value / tick) * tick, precision)


def get_current_price(symbol: str) -> float:
    client = _get_client()
    ticker = client.get_symbol_ticker(symbol=symbol)
    return float(ticker["price"])


def get_account_balance(asset: str = "USDT") -> float:
    client = _get_client()
    account = client.get_account()
    for b in account["balances"]:
        if b["asset"] == asset:
            return float(b["free"])
    return 0.0


def place_long_entry_with_oco(
    symbol: str,
    usdt_amount: float,
    sl_price: float,
    tp_price: float,
) -> dict:
    """
    Market buy `usdt_amount` USDT of `symbol`, then place OCO (SL+TP).
    Returns dict with entry_price, quantity, sl_order_id, tp_order_id.
    """
    client = _get_client()
    info = _get_symbol_info(client, symbol)

    lot_filter = _extract_filter(info, "LOT_SIZE")
    step_size = float(lot_filter.get("stepSize", "0.001"))
    min_qty = float(lot_filter.get("minQty", "0.001"))

    price_filter = _extract_filter(info, "PRICE_FILTER")
    tick_size = float(price_filter.get("tickSize", "0.01"))

    min_notional_filter = _extract_filter(info, "MIN_NOTIONAL")
    min_notional = float(min_notional_filter.get("minNotional", "10"))

    entry_price = get_current_price(symbol)
    qty = _round_step(usdt_amount / entry_price, step_size)

    if qty < min_qty:
        raise ValueError(f"Quantity {qty} below minQty {min_qty} — increase USDT amount")
    if qty * entry_price < min_notional:
        raise ValueError(f"Notional {qty * entry_price:.2f} below minimum {min_notional}")

    sl_rounded = _round_price(sl_price, tick_size)
    tp_rounded = _round_price(tp_price, tick_size)

    # sl_limit = 0.2% below sl to guarantee fill
    sl_limit = _round_price(sl_rounded * 0.998, tick_size)

    print(f"[executor] BUY {qty} {symbol} @ ~{entry_price:.4f}")
    buy_order = client.order_market_buy(symbol=symbol, quantity=qty)
    time.sleep(1)

    # Confirm actual fill price from order
    fills = buy_order.get("fills", [])
    if fills:
        total_cost = sum(float(f["price"]) * float(f["qty"]) for f in fills)
        total_qty = sum(float(f["qty"]) for f in fills)
        actual_price = total_cost / total_qty if total_qty else entry_price
    else:
        actual_price = entry_price

    print(f"[executor] Filled @ {actual_price:.4f} — placing OCO SL={sl_rounded} TP={tp_rounded}")

    oco = client.order_oco_sell(
        symbol=symbol,
        quantity=qty,
        price=str(tp_rounded),
        stopPrice=str(sl_rounded),
        stopLimitPrice=str(sl_limit),
        stopLimitTimeInForce="GTC",
    )

    return {
        "symbol": symbol,
        "side": "long",
        "entry_price": actual_price,
        "quantity": qty,
        "sl": sl_rounded,
        "tp": tp_rounded,
        "buy_order_id": buy_order["orderId"],
        "oco_order_list_id": oco["orderListId"],
        "testnet": _TESTNET,
    }


def cancel_all_open_orders(symbol: str) -> None:
    client = _get_client()
    try:
        client.cancel_open_orders(symbol=symbol)
        print(f"[executor] Cancelled all open orders for {symbol}")
    except BinanceAPIException as e:
        print(f"[executor] Cancel error: {e}")


def get_open_orders(symbol: str) -> list:
    client = _get_client()
    return client.get_open_orders(symbol=symbol)


def get_position_status(symbol: str, oco_order_list_id: int) -> str:
    """Returns 'open', 'tp_hit', 'sl_hit', or 'unknown'."""
    client = _get_client()
    try:
        oco = client.get_order_list(orderListId=oco_order_list_id)
        status = oco.get("listOrderStatus", "")
        if status == "EXECUTING":
            return "open"
        if status == "ALL_DONE":
            orders = oco.get("orders", [])
            for order_ref in orders:
                order = client.get_order(
                    symbol=symbol,
                    orderId=order_ref["orderId"],
                )
                if order["status"] == "FILLED":
                    side = order["type"]
                    if "STOP" in side:
                        return "sl_hit"
                    return "tp_hit"
        return "unknown"
    except BinanceAPIException as e:
        print(f"[executor] Status check error: {e}")
        return "unknown"
