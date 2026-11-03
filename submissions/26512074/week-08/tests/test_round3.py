import unittest

from round3 import DAY, buyer_candidates, demand_rates, learn, plan, quote


class Round3Tests(unittest.TestCase):
    def snapshot(self):
        return {"now": 10 * DAY, "cash": 1000000,
                "catalog": [{"sku": "food-1", "kind": "food", "list_price": 10000}],
                "inventory": [], "supplies": [
                    {"id": "a", "sku": "food-1", "cost": 3000, "units": 20, "expires_at": 12 * DAY},
                    {"id": "b", "sku": "food-1", "cost": 4000, "units": 20, "expires_at": 12 * DAY}],
                "ledger": [{"id": str(i), "sku": "food-1", "status": "settled",
                            "at": (10 - i) * DAY, "units": 10} for i in range(7)]}

    def test_net_requirements_not_bought_twice(self):
        result = plan(self.snapshot())
        self.assertEqual(sum(p["units"] for p in result["purchases"]), 3)
        self.assertEqual(result["purchases"][0]["supply_id"], "a")

    def test_cash_reserve_and_incoming(self):
        s = self.snapshot()
        s["cash"] = 752999
        self.assertEqual(plan(s)["purchases"], [])
        s["cash"] = 1000000
        s["catalog"][0]["incoming_units"] = 3
        self.assertEqual(plan(s)["purchases"], [])

    def test_unproven_and_duplicate_sales(self):
        s = self.snapshot()
        ledger = s["ledger"]
        ledger += [ledger[0], {"id": "ad", "sku": "food-1", "status": "agreed",
                              "at": s["now"], "units": 10000}]
        self.assertEqual(demand_rates(ledger, s["now"])["food-1"]["observed_units"], 70)
        s["ledger"] = []
        self.assertEqual(plan(s)["purchases"], [])

    def test_expiry_salvage_and_no_expiry_extension(self):
        p = {"kind": "food", "list_price": 100}
        lot = {"cost": 80, "units": 10, "expires_at": DAY}
        q = quote(p, lot, {"rate": 1}, 0)
        self.assertLess(q["ask"], 80)
        self.assertFalse(quote(p, lot, {"rate": 1}, DAY)["sellable"])

    def test_warranty_risk_changes_breakeven(self):
        p = {"kind": "goods", "list_price": 100}
        q = quote(p, {"cost": 50, "units": 1, "warranty_refund_probability": .5}, {"rate": 1}, 0)
        self.assertEqual(q["breakeven"], 101)
        self.assertGreaterEqual(q["expected_unit_profit"], 0)

    def test_buyer_budget_quality_and_expiry(self):
        offers = [{"shop": "cheap", "sku": "x", "price": 10, "quality": .1},
                  {"shop": "good", "sku": "x", "price": 30, "quality": 1},
                  {"shop": "expired", "sku": "x", "price": 1, "expires_at": 0},
                  {"shop": "over", "sku": "x", "price": 100}]
        rows = buyer_candidates(offers, {"sku": "x", "budget": 50, "value": 100}, 1)
        self.assertEqual([r["shop"] for r in rows], ["good"])

    def test_reward_uses_cost_and_refund_not_revenue(self):
        event = {"id": "s1", "status": "settled", "strategy": "premium", "opponent": "a",
                 "revenue": 100, "total_cost": 120}
        learned = learn([event, event, {**event, "id": "pending", "status": "agreed"}])
        self.assertEqual(learned["strategies"]["premium"]["mean_reward"], -20)
        self.assertEqual(learned["opponent_response_estimates"]["a:premium"], {"alpha": 1, "beta": 2})

    def test_invalid_evidence_rejected(self):
        s = self.snapshot()
        s["cash"] = float("nan")
        with self.assertRaises(ValueError):
            plan(s)


if __name__ == "__main__":
    unittest.main()
