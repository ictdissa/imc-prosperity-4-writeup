from datamodel import Order, OrderDepth, TradingState
from typing import Dict, List, Optional, Tuple
import json

Product = str


class Trader:
    """
    IMC Prosperity 4 Round 3: passive external-flow market maker.

    Backtested locally with an event-style replay model:
    - visible-book crossing fills are counted;
    - passive fills are approximated from external trade tape only when trade prices
      are consistent with sell-flow hitting bids or buy-flow lifting asks;
    - no mid-price fills are used.

    Surviving modules:
    1. HYDROGEL_PACK passive inside-spread market making.
    2. VELVETFRUIT_EXTRACT passive inside-spread market making.
    3. VEV_4000 passive synthetic-Velvet market making.
    4. VEV_6000 / VEV_6500 zero-price bid only.

    Removed after testing:
    - VEV_5400/5500 nonzero lottery bids: too small and day-fragile.
    - VEV_4500 synthetic module: little/no simulated fill contribution.
    - IV-smile/pair strategies and aggressive stale-book sweeping.
    """

    HYDROGEL = "HYDROGEL_PACK"
    VELVET = "VELVETFRUIT_EXTRACT"
    VEV4000 = "VEV_4000"
    VEV6000 = "VEV_6000"
    VEV6500 = "VEV_6500"

    LIMITS: Dict[Product, int] = {
        "HYDROGEL_PACK": 200,
        "VELVETFRUIT_EXTRACT": 200,
        "VEV_4000": 300,
        "VEV_4500": 300,
        "VEV_5000": 300,
        "VEV_5100": 300,
        "VEV_5200": 300,
        "VEV_5300": 300,
        "VEV_5400": 300,
        "VEV_5500": 300,
        "VEV_6000": 300,
        "VEV_6500": 300,
    }

    # HYDROGEL: wide-spread passive flow capture.
    HY_MIN_SPREAD = 10
    HY_WIDE_SPREAD = 16
    HY_BASE_SIZE = 56
    HY_WIDE_SIZE = 78
    HY_MARGIN = 1.0
    HY_INV_SKEW = 7.0
    HY_SOFT = 95
    HY_HARD = 165

    # VELVET: high-flow passive flow capture. No option hedging.
    VE_MIN_SPREAD = 5
    VE_WIDE_SPREAD = 6
    VE_BASE_SIZE = 34
    VE_WIDE_SIZE = 48
    VE_MARGIN = 0.75
    VE_INV_SKEW = 4.5
    VE_SOFT = 105
    VE_HARD = 170

    # VEV_4000: high-delta synthetic Velvet; wide-spread passive market making.
    V4_MIN_SPREAD = 14
    V4_WIDE_SPREAD = 22
    V4_BASE_SIZE = 18
    V4_WIDE_SIZE = 26
    V4_MARGIN = 5.0
    V4_INV_SKEW = 10.0
    V4_SOFT = 120
    V4_HARD = 210

    # Zero-cost tail bids. If they fill at 0, cash downside is zero.
    ZERO_TAIL_SIZE = 35
    ZERO_TAIL_CAP = 280

    def run(self, state: TradingState):
        data = self._decode(state.traderData)
        result: Dict[Product, List[Order]] = {product: [] for product in state.order_depths}
        buy_left, sell_left = self._capacity(state)

        # Velvet fair is also the anchor for VEV_4000.
        velvet_depth = state.order_depths.get(self.VELVET)
        velvet_fair = None
        if self._valid_depth(velvet_depth):
            ve_pos = state.position.get(self.VELVET, 0)
            velvet_fair = self._fair_delta_one(velvet_depth, data, "velvet", ve_pos, self.VE_INV_SKEW)

        # 1) Hydrogel passive MM.
        hy_depth = state.order_depths.get(self.HYDROGEL)
        if self._valid_depth(hy_depth):
            hy_pos = state.position.get(self.HYDROGEL, 0)
            hy_fair = self._fair_delta_one(hy_depth, data, "hydro", hy_pos, self.HY_INV_SKEW)
            self._passive_inside_mm(
                self.HYDROGEL, hy_depth, hy_fair, hy_pos, self.LIMITS[self.HYDROGEL],
                buy_left, sell_left, result,
                self.HY_MIN_SPREAD, self.HY_WIDE_SPREAD,
                self.HY_BASE_SIZE, self.HY_WIDE_SIZE,
                self.HY_MARGIN, self.HY_SOFT, self.HY_HARD,
                flatten_clip=18,
            )

        # 2) Velvet passive MM.
        if self._valid_depth(velvet_depth) and velvet_fair is not None:
            ve_pos = state.position.get(self.VELVET, 0)
            self._passive_inside_mm(
                self.VELVET, velvet_depth, velvet_fair, ve_pos, self.LIMITS[self.VELVET],
                buy_left, sell_left, result,
                self.VE_MIN_SPREAD, self.VE_WIDE_SPREAD,
                self.VE_BASE_SIZE, self.VE_WIDE_SIZE,
                self.VE_MARGIN, self.VE_SOFT, self.VE_HARD,
                flatten_clip=14,
            )

        # 3) VEV_4000 passive synthetic market maker.
        if velvet_fair is not None:
            v4_depth = state.order_depths.get(self.VEV4000)
            if self._valid_depth(v4_depth):
                v4_pos = state.position.get(self.VEV4000, 0)
                v4_fair = (velvet_fair - 4000.0) - self.V4_INV_SKEW * v4_pos / float(self.LIMITS[self.VEV4000])
                self._passive_inside_mm(
                    self.VEV4000, v4_depth, v4_fair, v4_pos, self.LIMITS[self.VEV4000],
                    buy_left, sell_left, result,
                    self.V4_MIN_SPREAD, self.V4_WIDE_SPREAD,
                    self.V4_BASE_SIZE, self.V4_WIDE_SIZE,
                    self.V4_MARGIN, self.V4_SOFT, self.V4_HARD,
                    flatten_clip=10,
                )

        # 4) Zero-cost tail bids only. Do not pay 1; do not short.
        self._zero_tail_bid(state, result, buy_left, self.VEV6000)
        self._zero_tail_bid(state, result, buy_left, self.VEV6500)

        return result, 0, self._encode(data)

    # ---------------- state ----------------

    def _decode(self, raw: str) -> Dict:
        if not raw:
            return {"ema": {}}
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                return {"ema": {}}
            data.setdefault("ema", {})
            return data
        except Exception:
            return {"ema": {}}

    def _encode(self, data: Dict) -> str:
        try:
            return json.dumps(data, separators=(",", ":"))
        except Exception:
            return ""

    def _capacity(self, state: TradingState) -> Tuple[Dict[Product, int], Dict[Product, int]]:
        buy_left: Dict[Product, int] = {}
        sell_left: Dict[Product, int] = {}
        for product, limit in self.LIMITS.items():
            pos = state.position.get(product, 0)
            buy_left[product] = max(0, limit - pos)
            sell_left[product] = max(0, limit + pos)
        return buy_left, sell_left

    # ---------------- helpers ----------------

    def _valid_depth(self, depth: Optional[OrderDepth]) -> bool:
        return depth is not None and bool(depth.buy_orders) and bool(depth.sell_orders)

    def _best_bid_ask(self, depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return bid, ask

    def _mid(self, depth: OrderDepth) -> Optional[float]:
        bid, ask = self._best_bid_ask(depth)
        if bid is None or ask is None:
            return None
        return 0.5 * (bid + ask)

    def _wall_mid(self, depth: OrderDepth) -> Optional[float]:
        if not self._valid_depth(depth):
            return self._mid(depth)
        wall_bid = max(depth.buy_orders.items(), key=lambda item: (item[1], item[0]))[0]
        wall_ask = max(depth.sell_orders.items(), key=lambda item: (-item[1], -item[0]))[0]
        return 0.5 * (wall_bid + wall_ask)

    def _microprice(self, depth: OrderDepth) -> Optional[float]:
        bid, ask = self._best_bid_ask(depth)
        if bid is None or ask is None:
            return None
        bid_qty = max(1, depth.buy_orders.get(bid, 0))
        ask_qty = max(1, -depth.sell_orders.get(ask, 0))
        return (ask * bid_qty + bid * ask_qty) / float(bid_qty + ask_qty)

    def _ema(self, data: Dict, key: str, value: Optional[float], alpha: float) -> Optional[float]:
        if value is None:
            prev = data.setdefault("ema", {}).get(key)
            return float(prev) if prev is not None else None
        bucket = data.setdefault("ema", {})
        prev = bucket.get(key)
        out = float(value) if prev is None else alpha * float(value) + (1.0 - alpha) * float(prev)
        bucket[key] = out
        return out

    def _fair_delta_one(self, depth: OrderDepth, data: Dict, key: str, position: int, inv_skew: float) -> Optional[float]:
        mid = self._mid(depth)
        if mid is None:
            return None
        wall = self._wall_mid(depth)
        micro = self._microprice(depth)
        ema = self._ema(data, key + "_mid", mid, 0.06)

        parts = []
        if wall is not None:
            parts.append((0.45, wall))
        if micro is not None:
            parts.append((0.25, micro))
        if ema is not None:
            parts.append((0.30, ema))
        if not parts:
            return mid
        fair = sum(w * v for w, v in parts) / sum(w for w, _ in parts)
        fair -= inv_skew * position / 200.0
        return fair

    # ---------------- execution ----------------

    def _passive_inside_mm(
        self,
        product: Product,
        depth: OrderDepth,
        fair: Optional[float],
        position: int,
        limit: int,
        buy_left: Dict[Product, int],
        sell_left: Dict[Product, int],
        result: Dict[Product, List[Order]],
        min_spread: int,
        wide_spread: int,
        base_size: int,
        wide_size: int,
        margin: float,
        soft_abs: int,
        hard_abs: int,
        flatten_clip: int,
    ) -> None:
        if fair is None:
            return
        bid, ask = self._best_bid_ask(depth)
        if bid is None or ask is None:
            return

        # Emergency inventory trim only. This prevents passive inventory from becoming
        # directional, but it is intentionally small to avoid recreating the failed taker bot.
        if abs(position) >= hard_abs:
            if position > 0 and sell_left.get(product, 0) > 0:
                qty = min(position - soft_abs, sell_left[product], depth.buy_orders.get(bid, 0), flatten_clip)
                if qty > 0:
                    result[product].append(Order(product, bid, -qty))
                    sell_left[product] -= qty
                    buy_left[product] += qty
                    position -= qty
            elif position < 0 and buy_left.get(product, 0) > 0:
                qty = min(-position - soft_abs, buy_left[product], -depth.sell_orders.get(ask, 0), flatten_clip)
                if qty > 0:
                    result[product].append(Order(product, ask, qty))
                    buy_left[product] -= qty
                    sell_left[product] += qty
                    position += qty

        spread = ask - bid
        if spread < min_spread:
            return

        quote_bid = bid + 1
        quote_ask = ask - 1
        if quote_bid >= quote_ask:
            return

        size = wide_size if spread >= wide_spread else base_size
        inv_frac = min(1.0, abs(position) / float(max(1, soft_abs)))
        size = max(4, int(size * (1.0 - 0.55 * inv_frac)))

        can_buy = position < soft_abs and buy_left.get(product, 0) > 0
        can_sell = position > -soft_abs and sell_left.get(product, 0) > 0

        # Strong one-sided inventory gates. Once inventory has a direction, only quote
        # the side that pulls it back toward zero.
        if position > 0.50 * soft_abs:
            can_buy = False
        if position < -0.50 * soft_abs:
            can_sell = False

        if can_buy and quote_bid <= fair - margin:
            qty = min(size, buy_left[product])
            if qty > 0:
                result[product].append(Order(product, quote_bid, qty))
                buy_left[product] -= qty
                sell_left[product] += qty

        if can_sell and quote_ask >= fair + margin:
            qty = min(size, sell_left[product])
            if qty > 0:
                result[product].append(Order(product, quote_ask, -qty))
                sell_left[product] -= qty
                buy_left[product] += qty

    def _zero_tail_bid(
        self,
        state: TradingState,
        result: Dict[Product, List[Order]],
        buy_left: Dict[Product, int],
        product: Product,
    ) -> None:
        depth = state.order_depths.get(product)
        if depth is None or buy_left.get(product, 0) <= 0:
            return
        pos = state.position.get(product, 0)
        if pos >= self.ZERO_TAIL_CAP:
            return
        # Bid 0 only; never pay the ask of 1. This is a free optionality module.
        qty = min(self.ZERO_TAIL_SIZE, buy_left[product], self.ZERO_TAIL_CAP - pos)
        if qty > 0:
            result[product].append(Order(product, 0, qty))
            buy_left[product] -= qty