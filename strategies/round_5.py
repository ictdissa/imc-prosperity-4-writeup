from __future__ import annotations

import json
import math
from typing import Dict, List, Tuple

from datamodel import Order, OrderDepth, TradingState


PRODUCTS = [
    "GALAXY_SOUNDS_DARK_MATTER",
    "GALAXY_SOUNDS_BLACK_HOLES",
    "GALAXY_SOUNDS_PLANETARY_RINGS",
    "GALAXY_SOUNDS_SOLAR_WINDS",
    "GALAXY_SOUNDS_SOLAR_FLAMES",
    "SLEEP_POD_SUEDE",
    "SLEEP_POD_LAMB_WOOL",
    "SLEEP_POD_POLYESTER",
    "SLEEP_POD_NYLON",
    "SLEEP_POD_COTTON",
    "MICROCHIP_CIRCLE",
    "MICROCHIP_OVAL",
    "MICROCHIP_SQUARE",
    "MICROCHIP_RECTANGLE",
    "MICROCHIP_TRIANGLE",
    "PEBBLES_XS",
    "PEBBLES_S",
    "PEBBLES_M",
    "PEBBLES_L",
    "PEBBLES_XL",
    "ROBOT_VACUUMING",
    "ROBOT_MOPPING",
    "ROBOT_DISHES",
    "ROBOT_LAUNDRY",
    "ROBOT_IRONING",
    "UV_VISOR_YELLOW",
    "UV_VISOR_AMBER",
    "UV_VISOR_ORANGE",
    "UV_VISOR_RED",
    "UV_VISOR_MAGENTA",
    "TRANSLATOR_SPACE_GRAY",
    "TRANSLATOR_ASTRO_BLACK",
    "TRANSLATOR_ECLIPSE_CHARCOAL",
    "TRANSLATOR_GRAPHITE_MIST",
    "TRANSLATOR_VOID_BLUE",
    "PANEL_1X2",
    "PANEL_2X2",
    "PANEL_1X4",
    "PANEL_2X4",
    "PANEL_4X4",
    "OXYGEN_SHAKE_MORNING_BREATH",
    "OXYGEN_SHAKE_EVENING_BREATH",
    "OXYGEN_SHAKE_MINT",
    "OXYGEN_SHAKE_CHOCOLATE",
    "OXYGEN_SHAKE_GARLIC",
    "SNACKPACK_CHOCOLATE",
    "SNACKPACK_VANILLA",
    "SNACKPACK_PISTACHIO",
    "SNACKPACK_STRAWBERRY",
    "SNACKPACK_RASPBERRY",
]

POSITION_LIMIT = 10
QUOTE_SIZE = 5

# Structural market-making parameters. The base layer is still shared, but the
# round is explicitly about selecting the products where the fill process is not
# toxic. These names are disabled at every timestamp; there is no start-time or
# first-window switch.
BASE_EDGE = 3.0
INVENTORY_SKEW = 0.35
BOUNDARY_POSITION = 5
BOUNDARY_EDGE = 4.0

DISABLED_PRODUCTS = {
    "GALAXY_SOUNDS_PLANETARY_RINGS",
    "GALAXY_SOUNDS_SOLAR_FLAMES",
    "SLEEP_POD_LAMB_WOOL",
    "MICROCHIP_SQUARE",
    "MICROCHIP_RECTANGLE",
    "PEBBLES_XS",
    "PEBBLES_M",
    "ROBOT_IRONING",
    "UV_VISOR_MAGENTA",
    "PANEL_1X2",
}

# Generic short-horizon adverse-selection guard. When the tape is moving, we
# still quote both sides, but we bias toward the direction of travel.
MOMENTUM_LAG = 20
MOMENTUM_THRESHOLD = 5.0
MOMENTUM_LEAN = 1.0

# "Same but slower": circle leads the rest of the shape sequence at 50-tick intervals.
MICROCHIP_LAGS = {
    "MICROCHIP_OVAL": 50,
    "MICROCHIP_SQUARE": 100,
    "MICROCHIP_RECTANGLE": 150,
    "MICROCHIP_TRIANGLE": 200,
}
MICROCHIP_SIGNAL_THRESHOLD = 15.0
MICROCHIP_LEAN = 0.5
MICROCHIP_FAIR_SHIFT = 0.20
MICROCHIP_MAX_SHIFT = 12.0

# Online residual pair trades. These legs are too toxic for standalone market
# making, but their spreads mean-revert robustly across public days under the
# official-style adverse fill model. Negative hedge means both legs move in the
# same target direction because the residual is A - hedge * B.
PAIR_SPECS = (
    ("MICROCHIP_RECTANGLE", "PEBBLES_XS", 0.20, 10, 2.0, 0.5, 0.005, 50),
    ("MICROCHIP_SQUARE", "ROBOT_IRONING", -0.32, 10, 2.5, 0.5, 0.005, 50),
)

# The local public backtester copy is missing Round 5 limits. This branch is ignored
# by the official engine and lets this same file run locally.
try:
    import prosperity4bt.data as _bt_data

    _bt_data.LIMITS.update({product: POSITION_LIMIT for product in PRODUCTS})
except Exception:
    pass


def best_bid_ask(depth: OrderDepth) -> Tuple[int | None, int, int | None, int]:
    best_bid = max(depth.buy_orders) if depth.buy_orders else None
    best_ask = min(depth.sell_orders) if depth.sell_orders else None
    bid_volume = depth.buy_orders[best_bid] if best_bid is not None else 0
    ask_volume = -depth.sell_orders[best_ask] if best_ask is not None else 0
    return best_bid, bid_volume, best_ask, ask_volume


def book_mid(depth: OrderDepth) -> float | None:
    best_bid, _, best_ask, _ = best_bid_ask(depth)
    if best_bid is None or best_ask is None:
        return None
    return (best_bid + best_ask) / 2.0


class Trader:
    def _load_data(
        self, trader_data: str
    ) -> Tuple[Dict[str, List[float]], List[float], List[List[float]]]:
        if not trader_data:
            return {}, [], []
        try:
            data = json.loads(trader_data)
            mids = data.get("mids", {})
            clean_mids: Dict[str, List[float]] = {}
            if isinstance(mids, dict):
                for product, history in mids.items():
                    if isinstance(product, str) and isinstance(history, list):
                        clean_mids[product] = [float(x) for x in history[-(MOMENTUM_LAG + 1) :]]
            circle = data.get("circle", [])
            clean_pairs: List[List[float]] = []
            pairs = data.get("pairs", [])
            if isinstance(pairs, list):
                for pair in pairs[: len(PAIR_SPECS)]:
                    if isinstance(pair, list) and len(pair) >= 4:
                        clean_pairs.append([float(x) for x in pair[:4]])
            if not clean_pairs:
                pair = data.get("pair", [])
                if isinstance(pair, list) and len(pair) >= 4:
                    clean_pairs.append([float(x) for x in pair[:4]])
            if isinstance(circle, list):
                return clean_mids, [float(x) for x in circle[-260:]], clean_pairs
        except Exception:
            pass
        return {}, [], []

    def _add_order(self, orders: Dict[str, List[Order]], product: str, price: int, quantity: int) -> None:
        if quantity:
            orders.setdefault(product, []).append(Order(product, int(price), int(quantity)))

    def _add_limited_order(
        self, orders: List[Order], product: str, price: int, quantity: int, expected_position: int
    ) -> int:
        if quantity > 0:
            quantity = min(quantity, POSITION_LIMIT - expected_position)
        elif quantity < 0:
            quantity = -min(-quantity, POSITION_LIMIT + expected_position)
        if quantity:
            orders.append(Order(product, int(price), int(quantity)))
            expected_position += quantity
        return expected_position

    def _sweep_to_target(self, product: str, depth: OrderDepth, position: int, target: int) -> List[Order]:
        target = max(-POSITION_LIMIT, min(POSITION_LIMIT, int(target)))
        expected_position = int(position)
        orders: List[Order] = []

        if target > expected_position:
            needed = target - expected_position
            for price in sorted(depth.sell_orders):
                if needed <= 0:
                    break
                quantity = min(needed, -int(depth.sell_orders[price]))
                expected_position = self._add_limited_order(orders, product, price, quantity, expected_position)
                needed = target - expected_position
        elif target < expected_position:
            needed = expected_position - target
            for price in sorted(depth.buy_orders, reverse=True):
                if needed <= 0:
                    break
                quantity = min(needed, int(depth.buy_orders[price]))
                expected_position = self._add_limited_order(orders, product, price, -quantity, expected_position)
                needed = expected_position - target

        return orders

    def _trade_pair(
        self,
        orders: Dict[str, List[Order]],
        state: TradingState,
        pair_state: List[float],
        product_a: str,
        product_b: str,
        hedge: float,
        quantity: int,
        entry_z: float,
        exit_z: float,
        alpha: float,
        warmup: int,
    ) -> List[float]:
        depth_a = state.order_depths.get(product_a)
        depth_b = state.order_depths.get(product_b)
        if depth_a is None or depth_b is None:
            return pair_state
        mid_a = book_mid(depth_a)
        mid_b = book_mid(depth_b)
        if mid_a is None or mid_b is None:
            return pair_state

        spread = mid_a - hedge * mid_b
        if len(pair_state) >= 4:
            mean = float(pair_state[0])
            variance = max(float(pair_state[1]), 1e-6)
            observations = int(pair_state[2])
            signal_state = int(pair_state[3])
        else:
            mean = spread
            variance = 1.0
            observations = 0
            signal_state = 0

        z_score = (spread - mean) / math.sqrt(variance)
        target_state = signal_state
        if observations >= warmup:
            if z_score > entry_z:
                target_state = -1
            elif z_score < -entry_z:
                target_state = 1
            elif abs(z_score) < exit_z:
                target_state = 0

        hedge_direction = -1 if hedge >= 0 else 1
        targets = {
            product_a: target_state * quantity,
            product_b: target_state * hedge_direction * quantity,
        }
        for product, depth in ((product_a, depth_a), (product_b, depth_b)):
            position = state.position.get(product, 0)
            target = targets[product]
            if position != target:
                pair_orders = self._sweep_to_target(product, depth, position, target)
                if pair_orders:
                    orders.setdefault(product, []).extend(pair_orders)

        diff = spread - mean
        mean += alpha * diff
        variance = (1.0 - alpha) * variance + alpha * diff * diff
        return [round(mean, 4), round(variance, 4), observations + 1, target_state]

    def _microchip_signal(self, product: str, circle_history: List[float]) -> float:
        lag = MICROCHIP_LAGS.get(product)
        if lag is None or len(circle_history) <= lag:
            return 0.0
        return circle_history[-1] - circle_history[-1 - lag]

    def _momentum_signal(self, product: str, mid_history: Dict[str, List[float]]) -> float:
        history = mid_history.get(product, [])
        if len(history) <= MOMENTUM_LAG:
            return 0.0
        return history[-1] - history[-1 - MOMENTUM_LAG]

    def _market_make(
        self,
        orders: Dict[str, List[Order]],
        product: str,
        depth: OrderDepth,
        position: int,
        mid_history: Dict[str, List[float]],
        circle_history: List[float],
        fair_shift: float = 0.0,
    ) -> None:
        best_bid, _, best_ask, _ = best_bid_ask(depth)
        if best_bid is None or best_ask is None:
            return

        mid = (best_bid + best_ask) / 2.0
        fair = mid - INVENTORY_SKEW * position + fair_shift

        buy_edge = BASE_EDGE
        sell_edge = BASE_EDGE

        momentum = self._momentum_signal(product, mid_history)
        if abs(momentum) >= MOMENTUM_THRESHOLD:
            if momentum > 0:
                buy_edge = max(1.0, buy_edge - MOMENTUM_LEAN)
                sell_edge += MOMENTUM_LEAN
            else:
                sell_edge = max(1.0, sell_edge - MOMENTUM_LEAN)
                buy_edge += MOMENTUM_LEAN

        signal = self._microchip_signal(product, circle_history)
        if abs(signal) >= MICROCHIP_SIGNAL_THRESHOLD:
            shift = max(-MICROCHIP_MAX_SHIFT, min(MICROCHIP_MAX_SHIFT, MICROCHIP_FAIR_SHIFT * signal))
            fair += shift
            if signal > 0:
                buy_edge = max(1.0, buy_edge - MICROCHIP_LEAN)
                sell_edge += MICROCHIP_LEAN
            else:
                sell_edge = max(1.0, sell_edge - MICROCHIP_LEAN)
                buy_edge += MICROCHIP_LEAN

        if position >= BOUNDARY_POSITION:
            buy_edge = max(buy_edge, BOUNDARY_EDGE)
        if position <= -BOUNDARY_POSITION:
            sell_edge = max(sell_edge, BOUNDARY_EDGE)

        buy_price = min(best_bid + 1, math.floor(fair - buy_edge))
        sell_price = max(best_ask - 1, math.ceil(fair + sell_edge))
        if buy_price >= sell_price:
            return

        buy_room = POSITION_LIMIT - position
        sell_room = POSITION_LIMIT + position
        if buy_room > 0 and buy_price < fair:
            self._add_order(orders, product, buy_price, min(QUOTE_SIZE, buy_room))
        if sell_room > 0 and sell_price > fair:
            self._add_order(orders, product, sell_price, -min(QUOTE_SIZE, sell_room))

    def run(self, state: TradingState):
        orders: Dict[str, List[Order]] = {}
        mid_history, circle_history, pair_states = self._load_data(state.traderData)

        for product, depth in state.order_depths.items():
            mid = book_mid(depth)
            if mid is None:
                continue
            history = mid_history.setdefault(product, [])
            history.append(mid)
            if len(history) > MOMENTUM_LAG + 1:
                del history[: -(MOMENTUM_LAG + 1)]

        circle_depth = state.order_depths.get("MICROCHIP_CIRCLE")
        if circle_depth is not None:
            circle_mid = book_mid(circle_depth)
            if circle_mid is not None:
                circle_history.append(circle_mid)
                if len(circle_history) > 260:
                    del circle_history[:-260]

        next_pair_states: List[List[float]] = []
        for index, spec in enumerate(PAIR_SPECS):
            pair_state = pair_states[index] if index < len(pair_states) else []
            next_pair_states.append(self._trade_pair(orders, state, pair_state, *spec))

        for product, depth in state.order_depths.items():
            if product in DISABLED_PRODUCTS:
                continue
            self._market_make(
                orders,
                product,
                depth,
                state.position.get(product, 0),
                mid_history,
                circle_history,
            )

        return orders, 0, json.dumps(
            {"mids": mid_history, "circle": circle_history, "pairs": next_pair_states},
            separators=(",", ":"),
        )