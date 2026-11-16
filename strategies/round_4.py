from datamodel import Order, OrderDepth, Trade, TradingState
from typing import Dict, List, Tuple, Optional
import json
import math

# ============================================================
# Round 4 v17 FINAL CANDIDATE: official-proven Mark-confirmed VEV short overlay
#
# Reasoning from official backtests:
# - Later "clever" option modules underperformed official replay and/or died
#   under worse-fill stress.
# - The best official replay among our uploaded candidates was the older
#   Mark-confirmed rich-VELVET central-call short engine.
# - This version keeps that proven structural edge and removes only the tiny
#   noisy upper-strike passive trade set.
#
# Structural alpha:
# 1) HYDROGEL dynamic fair-value market making.
# 2) VELVET Mark-adjusted fair-value market making.
# 3) VEV central calls are shorted only when VELVET is rich versus the
#    Mark-adjusted fair and the option is not cheap versus IV-smile fair.
# 4) VEV shorts are covered on mean reversion, bullish Mark reversal, or
#    cheap option pricing.
#
# This is intentionally NOT the aggressive v13/v16 path. It prioritizes
# official-replay evidence and fill-cost robustness over clean-fill fantasy PnL.
# ============================================================

HYDROGEL_PACK = "HYDROGEL_PACK"
VELVET = "VELVETFRUIT_EXTRACT"

VOUCHERS: Dict[str, int] = {
    "VEV_4000": 4000,
    "VEV_4500": 4500,
    "VEV_5000": 5000,
    "VEV_5100": 5100,
    "VEV_5200": 5200,
    "VEV_5300": 5300,
    "VEV_5400": 5400,
    "VEV_5500": 5500,
    "VEV_6000": 6000,
    "VEV_6500": 6500,
}

POSITION_LIMITS: Dict[str, int] = {
    HYDROGEL_PACK: 200,
    VELVET: 200,
    **{symbol: 300 for symbol in VOUCHERS},
}

# Round-4 historical HYDROGEL is centered higher than the defensive R3 9980.
# Use a slow dynamic anchor, not a hard jump to 9995.
DELTA1_CONFIG: Dict[str, Dict[str, float]] = {
    HYDROGEL_PACK: {
        "fair": 10000.0,
        "take_edge": 30.0,
        "exit_edge": 0.0,
        "maker_edge": 2.0,
        "max_spread": 25.0,
        "limit": 200,
        "take_clip": 20,
        "make_clip": 18,
        "neutral_band": 60,
        "relief_band": 160,
        "relief_edge": 10.0,
        "inv_skew": 0.045,
        "inv_convex": 0.18,
    },
    VELVET: {
        "fair": 5250.0,
        "take_edge": 18.0,
        "exit_edge": 0.0,
        "maker_edge": 2.0,
        "max_spread": 16.0,
        "limit": 200,
        "take_clip": 10,
        "make_clip": 12,
        "neutral_band": 60,
        "relief_band": 120,
        "relief_edge": 0.0,
        "inv_skew": 0.040,
        "inv_convex": 0.14,
    },
}

# ---------- Mark flow model ----------
MARK_DECAY = 0.72
MARK_MAX_SKEW = 8.0
MARK_SCORE_TO_TICKS = 0.35

# Score is positive when future VELVET drift has historically been positive.
VELVET_BUY_MARK_SCORE = {
    "Mark 67": 3.0,   # strongest positive buyer
    "Mark 55": 0.3,
    "Mark 01": 0.2,
    "Mark 14": -0.7,
    "Mark 49": -2.2,
    "Mark 22": -0.2,
    "SUBMISSION": 0.0,
}
VELVET_SELL_MARK_SCORE = {
    "Mark 49": 3.0,   # Mark 49 selling precedes upward VELVET drift
    "Mark 22": 2.0,
    "Mark 14": 0.4,
    "Mark 55": -0.2,
    "Mark 01": -0.2,
    "Mark 67": -0.5,
    "SUBMISSION": 0.0,
}

# HYDROGEL Mark signal is weak; use only tiny quote skew.
HYDRO_BUY_MARK_SCORE = {"Mark 14": 0.35, "Mark 22": -1.0, "Mark 38": -0.1}
HYDRO_SELL_MARK_SCORE = {"Mark 38": 0.20, "Mark 22": 1.0, "Mark 14": -0.15}

# ---------- VEV IV-smile module ----------
ENABLE_VOUCHERS = True
VOUCHER_TTE_DAYS = 4.0  # live Round 4 example says VEV TTE=4; historical days were 7/6/5.
VOUCHER_TTE = VOUCHER_TTE_DAYS / 365.0
VOUCHER_SQRT_TTE = math.sqrt(VOUCHER_TTE)
VOUCHER_MIN_TIME_VALUE = 1.0
VOUCHER_FIT_SYMBOLS = ["VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300", "VEV_5400", "VEV_5500"]
VOUCHER_TRADE_SYMBOLS = ["VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300"]
VOUCHER_TAKE_EDGE = 4.0
VOUCHER_MAKE_EDGE = 2.0
VOUCHER_MAX_SPREAD = 12
VOUCHER_CLIP = 4
VOUCHER_MAKE_CLIP = 2
VOUCHER_SOFT_LIMIT = 70
VOUCHER_INV_SKEW = 0.025

# ---------- Mark-confirmed VEV relative-value overlay ----------
# Richness is measured against Mark-adjusted VELVET fair, not an absolute
# timestamp/path threshold. Positive Mark flow raises fair and blocks shorts;
# bearish/neutral Mark flow allows call shorts when VELVET is rich.
ENABLE_MARK_CONFIRMED_CALL_SHORT = True
VEV_REL_RICH_ENTRY = 8.0       # spot - Mark-adjusted VELVET fair
VEV_REL_RICH_EXIT = 2.0
VEV_SHORT_FAIR_BUFFER = 4.0    # do not short calls that are already cheap vs smile
VEV_COVER_FAIR_BUFFER = 5.0
VEV_SHORT_BASE_CLIP = 8
VEV_SHORT_MAX_CLIP = 18
VEV_SHORT_SOFT_LIMIT = 140
VEV_SHORT_SYMBOLS = ["VEV_5000", "VEV_5100", "VEV_5200", "VEV_5300"]

class Trader:
    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}
        data = self.decode_data(state.traderData)
        expected_pos = {p: int(state.position.get(p, 0)) for p in POSITION_LIMITS}

        # Update Mark-flow scores from public market trades.
        self.update_mark_scores(state, data)

        # Delta-one core.
        for product in (HYDROGEL_PACK, VELVET):
            if product in state.order_depths:
                fair_override = None
                if product == HYDROGEL_PACK:
                    fair_override = self.compute_hydrogel_fair(state.order_depths[product], data)
                elif product == VELVET:
                    fair_override = self.compute_velvet_fair(state.order_depths[product], data)
                orders = self.trade_delta1(product, state.order_depths[product], expected_pos[product], fair_override)
                if orders:
                    result[product] = orders
                    for o in orders:
                        expected_pos[product] += o.quantity

        # Small IV-smile VEV add-on.
        if ENABLE_VOUCHERS and VELVET in state.order_depths:
            voucher_orders = self.trade_voucher_smile(state, expected_pos, data)
            for product, orders in voucher_orders.items():
                if orders:
                    result.setdefault(product, []).extend(orders)
                    for o in orders:
                        expected_pos[product] += o.quantity

        data["p"] = [int(state.position.get(HYDROGEL_PACK, 0)), int(state.position.get(VELVET, 0))]
        return result, 0, self.encode_data(data)

    # ---------- Mark flow ----------
    def update_mark_scores(self, state: TradingState, data: Dict) -> None:
        vs = float(data.get("vs", 0.0)) * MARK_DECAY
        hs = float(data.get("hs", 0.0)) * MARK_DECAY

        for tr in state.market_trades.get(VELVET, []):
            qty_scale = min(3.0, max(1.0, float(getattr(tr, "quantity", 1)) / 5.0))
            buyer = str(getattr(tr, "buyer", ""))
            seller = str(getattr(tr, "seller", ""))
            vs += qty_scale * VELVET_BUY_MARK_SCORE.get(buyer, 0.0)
            vs += qty_scale * VELVET_SELL_MARK_SCORE.get(seller, 0.0)

        for tr in state.market_trades.get(HYDROGEL_PACK, []):
            qty_scale = min(3.0, max(1.0, float(getattr(tr, "quantity", 1)) / 5.0))
            buyer = str(getattr(tr, "buyer", ""))
            seller = str(getattr(tr, "seller", ""))
            hs += qty_scale * HYDRO_BUY_MARK_SCORE.get(buyer, 0.0)
            hs += qty_scale * HYDRO_SELL_MARK_SCORE.get(seller, 0.0)

        data["vs"] = max(-25.0, min(25.0, vs))
        data["hs"] = max(-15.0, min(15.0, hs))

    # ---------- Fair values ----------
    def compute_hydrogel_fair(self, depth: OrderDepth, data: Dict) -> float:
        # HYDROGEL is still a stable/fair-value product, but Round 4 historical
        # levels were higher and more drifting than our defensive Round 3 9980.
        # Use a slow rolling median blend rather than a hard one-number fit.
        obs = self.basic_mid(depth)
        hist = data.get("h", [])
        if not isinstance(hist, list):
            hist = []
        if obs is not None:
            hist.append(float(obs))
            hist = hist[-64:]
            data["h"] = [round(x, 2) for x in hist]

        if len(hist) >= 20:
            med = self.median(hist[-64:])
            base = 0.70 * 10000.0 + 0.30 * med
        else:
            base = 10000.0

        # HYDROGEL Mark edge is weaker than VELVET; keep this tiny.
        mark_skew = max(-1.0, min(1.0, 0.04 * float(data.get("hs", 0.0))))
        fair = base + mark_skew
        return max(9985.0, min(10018.0, fair))

    def compute_velvet_fair(self, depth: OrderDepth, data: Dict) -> float:
        obs = self.basic_mid(depth)
        hist = data.get("v", [])
        if not isinstance(hist, list):
            hist = []
        if obs is not None:
            hist.append(float(obs))
            hist = hist[-64:]
            data["v"] = [round(x, 2) for x in hist]
        if len(hist) < 20:
            base = 5250.0
        else:
            dynamic = self.median(hist[-64:])
            base = 0.88 * 5250.0 + 0.12 * dynamic
        mark_skew = max(-MARK_MAX_SKEW, min(MARK_MAX_SKEW, MARK_SCORE_TO_TICKS * float(data.get("vs", 0.0))))
        fair = base + mark_skew
        data["vf"] = round(float(fair), 3)
        return fair

    # ---------- Delta-one strategy ----------
    def trade_delta1(self, product: str, depth: OrderDepth, position: int, fair_override: Optional[float] = None) -> List[Order]:
        cfg = DELTA1_CONFIG[product]
        orders: List[Order] = []

        best_bid, best_ask = self.best_bid_ask(depth)
        if best_bid is None or best_ask is None:
            return orders
        spread = best_ask - best_bid
        if spread <= 0 or spread > float(cfg["max_spread"]):
            return orders

        fair = float(cfg["fair"]) if fair_override is None else float(fair_override)
        take_edge = float(cfg["take_edge"])
        exit_edge = float(cfg["exit_edge"])
        limit = int(cfg["limit"])
        take_clip = int(cfg["take_clip"])
        expected = int(position)

        # A) inventory relief / exits first.
        relief_band = int(cfg.get("relief_band", limit + 1))
        relief_edge = float(cfg.get("relief_edge", max(0.0, take_edge - 2.0)))

        if expected > 0:
            exit_price = fair - exit_edge
            if abs(expected) >= relief_band:
                exit_price = min(exit_price, fair - relief_edge)
            if best_bid >= exit_price:
                qty = min(expected, take_clip)
                filled = self.sweep_sell_safe(orders, product, depth, qty, int(math.ceil(exit_price)), position, limit)
                expected -= filled

        elif expected < 0:
            exit_price = fair + exit_edge
            if abs(expected) >= relief_band:
                exit_price = max(exit_price, fair + relief_edge)
            if best_ask <= exit_price:
                qty = min(-expected, take_clip)
                filled = self.sweep_buy_safe(orders, product, depth, qty, int(math.floor(exit_price)), position, limit)
                expected += filled

        # B) take stale liquidity.
        if best_ask <= fair - take_edge and expected < limit:
            qty = min(limit - expected, take_clip)
            filled = self.sweep_buy_safe(orders, product, depth, qty, int(math.floor(fair - take_edge)), position, limit)
            expected += filled

        if best_bid >= fair + take_edge and expected > -limit:
            qty = min(limit + expected, take_clip)
            filled = self.sweep_sell_safe(orders, product, depth, qty, int(math.ceil(fair + take_edge)), position, limit)
            expected -= filled

        # C) passive maker quotes.
        self.add_passive_quotes_safe(orders, product, depth, expected, position, cfg, fair)
        return orders

    def add_passive_quotes_safe(self, orders: List[Order], product: str, depth: OrderDepth, expected: int, current_position: int, cfg: Dict[str, float], fair: float) -> None:
        best_bid, best_ask = self.best_bid_ask(depth)
        if best_bid is None or best_ask is None:
            return

        limit = int(cfg["limit"])
        make_clip = int(cfg["make_clip"])
        maker_edge = float(cfg["maker_edge"])
        neutral_band = int(cfg["neutral_band"])
        excess = max(0, abs(expected) - neutral_band)
        sign = 1 if expected > 0 else -1 if expected < 0 else 0
        reservation = fair - float(cfg["inv_skew"]) * expected - float(cfg["inv_convex"]) * excess * sign

        bid_price = min(best_bid + 1, int(math.floor(reservation - maker_edge)))
        ask_price = max(best_ask - 1, int(math.ceil(reservation + maker_edge)))

        util = abs(expected) / max(1, limit)
        if util > 0.90:
            size_scale = 0.0
        elif util > 0.85:
            size_scale = 0.25
        elif util > 0.65:
            size_scale = 0.50
        else:
            size_scale = 1.0

        bid_qty = max(0, int(make_clip * size_scale))
        ask_qty = max(0, int(make_clip * size_scale))

        if bid_qty > 0 and bid_price < best_ask and bid_price <= reservation - maker_edge:
            self.append_buy_safe(orders, product, int(bid_price), bid_qty, current_position, limit)

        if ask_qty > 0 and ask_price > best_bid and ask_price >= reservation + maker_edge:
            self.append_sell_safe(orders, product, int(ask_price), ask_qty, current_position, limit)

    # ---------- Voucher smile ----------
    def trade_voucher_smile(self, state: TradingState, expected_pos: Dict[str, int], data: Dict) -> Dict[str, List[Order]]:
        out: Dict[str, List[Order]] = {}
        spot = self.basic_mid(state.order_depths[VELVET])
        if spot is None or spot <= 0:
            return out

        # Mark-adjusted VELVET fair was computed before voucher trading.
        velvet_fair = float(data.get("vf", 5250.0))
        velvet_richness = float(spot - velvet_fair)
        mark_score = float(data.get("vs", 0.0))

        points: Dict[str, Tuple[float, float]] = {}
        for symbol in VOUCHER_FIT_SYMBOLS:
            depth = state.order_depths.get(symbol)
            if depth is None:
                continue
            bid, ask = self.best_bid_ask(depth)
            if bid is None or ask is None or ask - bid > VOUCHER_MAX_SPREAD + 8:
                continue
            mid = self.basic_mid(depth)
            if mid is None:
                continue
            K = float(VOUCHERS[symbol])
            intrinsic = max(0.0, spot - K)
            # Same filter top option teams use: low time value creates unstable IV.
            if mid - intrinsic < VOUCHER_MIN_TIME_VALUE:
                continue
            iv = self.implied_vol_call(spot, K, mid)
            if iv is None or not (0.01 < iv < 5.0):
                continue
            x = math.log(K / spot) / VOUCHER_SQRT_TTE
            points[symbol] = (x, iv)

        if len(points) < 4:
            return out

        for symbol in VOUCHER_TRADE_SYMBOLS:
            depth = state.order_depths.get(symbol)
            if depth is None:
                continue
            best_bid, best_ask = self.best_bid_ask(depth)
            if best_bid is None or best_ask is None:
                continue
            if best_ask - best_bid > VOUCHER_MAX_SPREAD:
                continue

            fit_points = [value for name, value in points.items() if name != symbol]
            if len(fit_points) < 3:
                continue
            coef = self.fit_parabola(fit_points)
            if coef is None:
                continue

            K = float(VOUCHERS[symbol])
            x = math.log(K / spot) / VOUCHER_SQRT_TTE
            fair_iv = max(0.01, min(5.0, self.eval_parabola(coef, x)))
            fair = self.bs_call(spot, K, fair_iv)
            current_pos = int(expected_pos.get(symbol, state.position.get(symbol, 0)))
            limit = POSITION_LIMITS[symbol]
            orders: List[Order] = []

            # Base IV-smile reservation. If long, sell easier; if short, buy easier.
            reservation = fair - VOUCHER_INV_SKEW * current_pos

            # Small pure relative-value engine from v2. This is conservative and
            # stays active even when no Mark-confirmed directional overlay exists.
            max_abs = VOUCHER_SOFT_LIMIT
            buy_room = max(0, min(max_abs - current_pos, limit - current_pos))
            sell_room = max(0, min(max_abs + current_pos, limit + current_pos))

            if reservation - best_ask >= VOUCHER_TAKE_EDGE and buy_room > 0:
                qty = min(VOUCHER_CLIP, buy_room, -int(depth.sell_orders.get(best_ask, 0)))
                if qty > 0:
                    self.append_buy_safe(orders, symbol, int(best_ask), qty, current_pos, limit)
                    current_pos += qty

            if best_bid - reservation >= VOUCHER_TAKE_EDGE and sell_room > 0:
                qty = min(VOUCHER_CLIP, sell_room, int(depth.buy_orders.get(best_bid, 0)))
                if qty > 0:
                    self.append_sell_safe(orders, symbol, int(best_bid), qty, current_pos, limit)
                    current_pos -= qty

            # Mark-confirmed overlay:
            # - Short central calls only when VELVET is rich vs Mark-adjusted fair.
            # - Mark bullishness blocks shorting automatically because it raises
            #   velvet_fair; additionally, strong positive mark_score blocks entries.
            # - Cover on mean reversion, bullish Mark reversal, or cheap option.
            if ENABLE_MARK_CONFIRMED_CALL_SHORT and symbol in VEV_SHORT_SYMBOLS:
                max_abs = max(max_abs, VEV_SHORT_SOFT_LIMIT)

                # Cover existing shorts first.
                buy_room = max(0, min(max_abs - current_pos, limit - current_pos))
                if current_pos < 0 and (
                    velvet_richness <= VEV_REL_RICH_EXIT
                    or mark_score >= 8.0
                    or best_ask <= fair - VEV_COVER_FAIR_BUFFER
                ):
                    qty = min(VEV_SHORT_MAX_CLIP, -current_pos, -int(depth.sell_orders.get(best_ask, 0)), buy_room)
                    if qty > 0:
                        self.append_buy_safe(orders, symbol, int(best_ask), qty, current_pos, limit)
                        current_pos += qty

                # Enter/add shorts if all structural conditions agree.
                sell_room = max(0, min(max_abs + current_pos, limit + current_pos))
                if (
                    velvet_richness >= VEV_REL_RICH_ENTRY
                    and mark_score <= 6.0
                    and best_bid >= fair - VEV_SHORT_FAIR_BUFFER
                    and sell_room > 0
                ):
                    # Size increases smoothly with richness and bearish Mark flow,
                    # but remains capped well below the hard 300 limit.
                    strength = max(0.0, velvet_richness - VEV_REL_RICH_ENTRY)
                    bearish_bonus = max(0.0, -mark_score) * 0.25
                    clip = int(min(VEV_SHORT_MAX_CLIP, VEV_SHORT_BASE_CLIP + strength * 0.7 + bearish_bonus))
                    qty = min(max(1, clip), sell_room, int(depth.buy_orders.get(best_bid, 0)))
                    if qty > 0:
                        self.append_sell_safe(orders, symbol, int(best_bid), qty, current_pos, limit)
                        current_pos -= qty

            # Passive IV-smile making, smaller when carrying directional short risk.
            buy_room = max(0, min(VOUCHER_SOFT_LIMIT - current_pos, limit - current_pos))
            sell_room = max(0, min(VOUCHER_SOFT_LIMIT + current_pos, limit + current_pos))
            util = abs(current_pos) / max(1, max(VOUCHER_SOFT_LIMIT, abs(current_pos)))
            if util < 0.90:
                scale = 0.4 if util > 0.65 else 1.0
                qty = max(1, int(VOUCHER_MAKE_CLIP * scale))
                bid_price = min(best_bid + 1, int(math.floor(reservation - VOUCHER_MAKE_EDGE)))
                ask_price = max(best_ask - 1, int(math.ceil(reservation + VOUCHER_MAKE_EDGE)))

                # Do not add bids when already running the short-call overlay.
                allow_bid = current_pos < VOUCHER_SOFT_LIMIT * 0.75
                allow_ask = current_pos > -VOUCHER_SOFT_LIMIT * 0.75

                if allow_bid and buy_room > 0 and bid_price < best_ask:
                    self.append_buy_safe(orders, symbol, int(bid_price), min(qty, buy_room), current_pos, limit)
                if allow_ask and sell_room > 0 and ask_price > best_bid:
                    self.append_sell_safe(orders, symbol, int(ask_price), min(qty, sell_room), current_pos, limit)

            if orders:
                out[symbol] = orders
                expected_pos[symbol] = int(expected_pos.get(symbol, 0)) + sum(o.quantity for o in orders)

        return out

    # ---------- safe order helpers ----------
    def submitted_buy_qty(self, orders: List[Order]) -> int:
        return sum(o.quantity for o in orders if o.quantity > 0)

    def submitted_sell_qty(self, orders: List[Order]) -> int:
        return -sum(o.quantity for o in orders if o.quantity < 0)

    def buy_room_from_current(self, orders: List[Order], current_position: int, limit: int) -> int:
        return max(0, limit - current_position - self.submitted_buy_qty(orders))

    def sell_room_from_current(self, orders: List[Order], current_position: int, limit: int) -> int:
        return max(0, limit + current_position - self.submitted_sell_qty(orders))

    def append_buy_safe(self, orders: List[Order], product: str, price: int, qty: int, current_position: int, limit: int) -> int:
        qty = min(int(qty), self.buy_room_from_current(orders, current_position, limit))
        if qty > 0:
            orders.append(Order(product, int(price), int(qty)))
        return qty

    def append_sell_safe(self, orders: List[Order], product: str, price: int, qty: int, current_position: int, limit: int) -> int:
        qty = min(int(qty), self.sell_room_from_current(orders, current_position, limit))
        if qty > 0:
            orders.append(Order(product, int(price), -int(qty)))
        return qty

    def sweep_buy_safe(self, orders: List[Order], product: str, depth: OrderDepth, max_qty: int, max_price: int, current_position: int, limit: int) -> int:
        filled = 0
        remaining = min(max(0, int(max_qty)), self.buy_room_from_current(orders, current_position, limit))
        for price, volume in sorted(depth.sell_orders.items()):
            if remaining <= 0 or int(price) > int(max_price):
                break
            available = max(0, -int(volume))
            qty = min(available, remaining)
            if qty > 0:
                added = self.append_buy_safe(orders, product, int(price), int(qty), current_position, limit)
                filled += added
                remaining -= added
                if added < qty:
                    break
        return filled

    def sweep_sell_safe(self, orders: List[Order], product: str, depth: OrderDepth, max_qty: int, min_price: int, current_position: int, limit: int) -> int:
        filled = 0
        remaining = min(max(0, int(max_qty)), self.sell_room_from_current(orders, current_position, limit))
        for price, volume in sorted(depth.buy_orders.items(), reverse=True):
            if remaining <= 0 or int(price) < int(min_price):
                break
            available = max(0, int(volume))
            qty = min(available, remaining)
            if qty > 0:
                added = self.append_sell_safe(orders, product, int(price), int(qty), current_position, limit)
                filled += added
                remaining -= added
                if added < qty:
                    break
        return filled

    # ---------- math ----------
    def best_bid_ask(self, depth: OrderDepth) -> Tuple[Optional[int], Optional[int]]:
        best_bid = max(depth.buy_orders.keys()) if depth.buy_orders else None
        best_ask = min(depth.sell_orders.keys()) if depth.sell_orders else None
        return best_bid, best_ask

    def basic_mid(self, depth: OrderDepth) -> Optional[float]:
        bid, ask = self.best_bid_ask(depth)
        if bid is None or ask is None:
            return None
        return 0.5 * (bid + ask)

    def median(self, values: List[float]) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        n = len(ordered)
        m = n // 2
        if n % 2 == 1:
            return float(ordered[m])
        return 0.5 * (ordered[m - 1] + ordered[m])

    def norm_cdf(self, x: float) -> float:
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def bs_call(self, spot: float, strike: float, vol: float) -> float:
        intrinsic = max(0.0, spot - strike)
        if spot <= 0 or strike <= 0 or vol <= 1e-9:
            return intrinsic
        sigma_t = vol * VOUCHER_SQRT_TTE
        if sigma_t <= 0:
            return intrinsic
        d1 = (math.log(spot / strike) + 0.5 * vol * vol * VOUCHER_TTE) / sigma_t
        d2 = d1 - sigma_t
        return spot * self.norm_cdf(d1) - strike * self.norm_cdf(d2)

    def implied_vol_call(self, spot: float, strike: float, price: float) -> Optional[float]:
        intrinsic = max(0.0, spot - strike)
        if price <= intrinsic + 1e-6 or price >= spot:
            return None
        lo = 1e-4
        hi = 5.0
        for _ in range(45):
            mid = (lo + hi) / 2.0
            if self.bs_call(spot, strike, mid) < price:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def fit_parabola(self, points: List[Tuple[float, float]]) -> Optional[Tuple[float, float, float]]:
        if len(points) < 3:
            return None
        s0 = float(len(points))
        s1 = sum(x for x, _ in points)
        s2 = sum(x * x for x, _ in points)
        s3 = sum(x * x * x for x, _ in points)
        s4 = sum(x * x * x * x for x, _ in points)
        y0 = sum(y for _, y in points)
        y1 = sum(x * y for x, y in points)
        y2 = sum(x * x * y for x, y in points)
        return self.solve_3x3([[s4, s3, s2], [s3, s2, s1], [s2, s1, s0]], [y2, y1, y0])

    def eval_parabola(self, coef: Tuple[float, float, float], x: float) -> float:
        return coef[0] * x * x + coef[1] * x + coef[2]

    def solve_3x3(self, matrix: List[List[float]], vector: List[float]) -> Optional[Tuple[float, float, float]]:
        rows = [matrix[i][:] + [vector[i]] for i in range(3)]
        for col in range(3):
            pivot = max(range(col, 3), key=lambda row: abs(rows[row][col]))
            if abs(rows[pivot][col]) < 1e-12:
                return None
            rows[col], rows[pivot] = rows[pivot], rows[col]
            divisor = rows[col][col]
            for j in range(col, 4):
                rows[col][j] /= divisor
            for row in range(3):
                if row == col:
                    continue
                factor = rows[row][col]
                for j in range(col, 4):
                    rows[row][j] -= factor * rows[col][j]
        return rows[0][3], rows[1][3], rows[2][3]

    def decode_data(self, raw: str) -> Dict:
        if not raw:
            return {}
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, dict):
                return decoded
        except Exception:
            pass
        return {}

    def encode_data(self, data: Dict) -> str:
        try:
            return json.dumps(data, separators=(",", ":"))[:3500]
        except Exception:
            return ""