"""Offline Round-3 planner. Normalized input is NOT the unverified kit-v4 contract.

No network, account creation, payment, forum publication or key access occurs here.
Run: python round3.py --snapshot snapshot.json --output plan.json
Times are Unix seconds; credits are whole numbers; rates are units/day.
"""
import argparse
import json
import math
from pathlib import Path

DAY = 86400


def number(value, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected numeric evidence")
    if not math.isfinite(value) or value < minimum:
        raise ValueError("invalid numeric evidence")
    return value


def probability(value):
    number(value)
    if value > 1:
        raise ValueError("probability outside [0,1]")
    return value


def unique(rows, key):
    seen = set()
    for row in rows:
        identity = row[key]
        if not isinstance(identity, str) or not identity or identity in seen:
            raise ValueError(f"invalid or duplicate {key}")
        seen.add(identity)
    return rows


def demand_rates(events, now, days=7):
    """Decayed settled units with daily dispersion; deduplicate ledger identities.

    Missing evidence remains zero. Demand category lists and forum ads are not sales.
    """
    bins, seen = {}, set()
    for event in events:
        if event.get("status") != "settled":
            continue
        identity = event["id"]
        if identity in seen:
            continue
        seen.add(identity)
        at = number(event["at"])
        age = (now - at) / DAY
        if not 0 <= age < days:
            continue
        units = number(event["units"])
        bins.setdefault(event["sku"], [0.] * days)[int(age)] += units
    weights = [math.exp(-i / 3) for i in range(days)]
    result = {}
    for sku, values in bins.items():
        mean = sum(v * w for v, w in zip(values, weights)) / sum(weights)
        variance = sum(w * (v - mean) ** 2 for v, w in zip(values, weights)) / sum(weights)
        result[sku] = {"rate": mean, "sigma": math.sqrt(variance), "observed_units": sum(values)}
    return result


def quote(product, lot, forecast, now):
    cost = number(lot["cost"])
    list_price = number(product["list_price"])
    failure = probability(lot.get("failure_probability", .1))
    warranty = probability(lot.get("warranty_refund_probability", failure))
    rate = forecast.get("rate", 0)
    available = number(lot["units"])
    days_to_sell = min(30, available / max(rate, .01))
    food = product["kind"] == "food"
    remaining = (number(lot["expires_at"]) - now) / DAY if food else None
    if food and remaining <= 0:
        return {"sellable": False, "reason": "expired", "ask": None}
    storage = 0 if food else cost * .01 * days_to_sell
    loss = 0 if food else warranty
    # Full-price refund risk: expected profit = price*(1-p) - cost - storage.
    breakeven = math.ceil((cost + storage) / max(.01, 1 - loss))
    competitors = [number(p) for p in product.get("competitor_prices", [])]
    market = min(competitors) - 1 if competitors else list_price
    target = max(breakeven, min(list_price, market))
    if food:
        sellthrough = min(1, rate * remaining / max(1, available))
        # Sunk acquisition cost does not justify throwing away salvage revenue.
        target = max(1, math.floor(target * (.15 + .85 * sellthrough)))
    ask = max(1, target)
    return {"sellable": True, "ask": ask, "breakeven": breakeven,
            "expected_unit_profit": round(ask * (1 - loss) - cost - storage, 2),
            "remaining_days": remaining, "risk_is_estimated": "warranty_refund_probability" not in lot}


def restock(products, inventory, supplies, forecasts, cash, now, config):
    """MRP net requirements with safety stock, shelf-life and shared cash limits."""
    reserve = number(config.get("cash_reserve", 750000))
    spendable = max(0, cash - reserve)
    window = number(config.get("review_days", .25)) + number(config.get("lead_days", .05))
    z = number(config.get("safety_z", 1.65))
    candidates = []
    for supply in supplies:
        sku = supply["sku"]
        if sku not in products:
            raise ValueError("supply SKU missing from catalog")
        product = products[sku]
        forecast = forecasts.get(sku, {"rate": 0, "sigma": 0})
        cost = number(supply["cost"])
        if cost <= 0:
            continue
        held = sum(number(lot["units"]) for lot in inventory if lot["sku"] == sku and
                   (product["kind"] != "food" or number(lot["expires_at"]) > now))
        incoming = number(product.get("incoming_units", 0))
        safety = z * forecast["sigma"] * math.sqrt(window)
        target = math.ceil(forecast["rate"] * window + safety)
        if product["kind"] == "food":
            shelf = (number(supply["expires_at"]) - now) / DAY
            # Leave enough time for transfer and resale, never extend market expiry.
            horizon = max(0, shelf - config.get("resale_buffer_days", .05))
            target = min(target, math.floor(forecast["rate"] * horizon))
        need = max(0, target - held - incoming)
        proposed = {**supply, "units": max(1, need)}
        pricing = quote(product, proposed, forecast, now)
        profit = pricing.get("expected_unit_profit", -cost)
        if need and profit > 0:
            candidates.append({"sku": sku, "supply_id": supply["id"], "cost": cost,
                               "need": need, "available": int(number(supply["units"])),
                               "safety_stock": round(safety, 3),
                               "roi": profit / cost, "expected_unit_profit": profit})
    candidates.sort(key=lambda c: (-c["roi"], c["sku"], c["supply_id"]))
    purchases, allocated = [], {}
    for candidate in candidates:
        sku = candidate["sku"]
        units = min(20, candidate["available"], max(0, candidate["need"] - allocated.get(sku, 0)),
                    math.floor(spendable / candidate["cost"]))
        if units:
            purchases.append({**candidate, "units": units})
            allocated[sku] = allocated.get(sku, 0) + units
            spendable -= candidate["cost"] * units
    return purchases


def buyer_candidates(offers, order, now):
    """Compare quality-adjusted expected surplus without exposing a private budget."""
    budget = number(order["budget"])
    ranked = []
    for offer in offers:
        if offer["sku"] != order["sku"]:
            continue
        price = number(offer["price"])
        if price > budget:
            continue
        remaining = (number(offer["expires_at"]) - now) if "expires_at" in offer else math.inf
        if remaining <= number(order.get("minimum_remaining_seconds", 3600)):
            continue
        quality = probability(offer.get("quality", .5))
        reliability = probability(offer.get("settlement_reliability", .5))
        failure = probability(offer.get("failure_probability", .1))
        refund = probability(offer.get("refund_probability", 0))
        value = number(order["value"]) * quality * (1 - failure)
        surplus = reliability * (value - price * (1 - failure * refund))
        if surplus > 0:
            ranked.append({"shop": offer["shop"], "sku": offer["sku"], "price": price,
                           "expected_surplus": surplus,
                           "opening_offer": max(1, math.floor(price * .8)),
                           "requires_signed_receipt_and_checkout": True})
    return sorted(ranked, key=lambda row: (-row["expected_surplus"], row["shop"]))


def learn(outcomes):
    """Settlement-only reward updates; refunds/storage must be included by adapter.

    Per-opponent beta posteriors estimate willingness, not access to hidden tastes.
    """
    arms, opponents, seen = {}, {}, set()
    for outcome in outcomes:
        if outcome.get("status") != "settled" or outcome["id"] in seen:
            continue
        seen.add(outcome["id"])
        reward = number(outcome["revenue"]) - number(outcome["total_cost"])
        arm = arms.setdefault(outcome["strategy"], {"count": 0, "reward": 0})
        arm["count"] += 1
        arm["reward"] += reward
        key = outcome["opponent"] + ":" + outcome["strategy"]
        posterior = opponents.setdefault(key, {"alpha": 1, "beta": 1})
        posterior["alpha" if reward > 0 else "beta"] += 1
    for arm in arms.values():
        arm["mean_reward"] = arm["reward"] / arm["count"]
    return {"strategies": arms, "opponent_response_estimates": opponents,
            "reward_definition": "settled revenue minus acquisition, storage and refunds"}


def plan(snapshot):
    now = number(snapshot["now"])
    cash = number(snapshot["cash"])
    catalog = unique(snapshot["catalog"], "sku")
    products = {p["sku"]: p for p in catalog}
    for product in catalog:
        if product["kind"] not in ("food", "goods"):
            raise ValueError("kind must be food or goods")
    inventory = unique(snapshot.get("inventory", []), "id")
    supplies = unique(snapshot.get("supplies", []), "id")
    rates = demand_rates(snapshot.get("ledger", []), now)
    quotes = [{"lot": lot["id"], "sku": lot["sku"],
               **quote(products[lot["sku"]], lot, rates.get(lot["sku"], {}), now)} for lot in inventory]
    config = snapshot.get("config", {})
    purchases = restock(products, inventory, supplies, rates, cash, now, config)
    forum = []
    if now - number(snapshot.get("last_post_at", 0)) >= number(config.get("post_interval_seconds", 3600)):
        stock = [q for q in quotes if q["sellable"]][:3]
        if stock:
            forum.append({"type": "post_draft", "text": "현재 재고 안내: " + "; ".join(
                f"{q['sku']} {q['ask']} credits" for q in stock) + ". 가격과 남은 유통기한을 확인해 주세요."})
    return {"mode": "offline_plan_only", "contract_verified": False,
            "forecast": rates, "purchases": purchases, "quotes": quotes,
            "buyer_candidates": buyer_candidates(snapshot.get("offers", []), snapshot["order"], now)
                if "order" in snapshot else [],
            "learning": learn(snapshot.get("outcomes", [])), "forum_drafts": forum,
            "capabilities_unverified": ["kit-v4 hooks", "inventory transfer and resale", "repair",
                                        "expiry extension", "loans", "identity-bound voting"],
            "market_actions_executed": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = plan(json.loads(args.snapshot.read_text(encoding="utf-8")))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"mode": result["mode"], "output": str(args.output), "market_actions_executed": 0}))


if __name__ == "__main__":
    main()
