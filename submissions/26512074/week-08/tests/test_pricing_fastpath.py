import unittest
from pricing_fastpath import counter_ask


class CounterTests(unittest.TestCase):
    def test_open_and_concede(self):
        prices = [counter_ask(100, 115, None)]
        for _ in range(8):
            prices.append(counter_ask(100, 115, prices[-1]))
        self.assertEqual(prices[:5], [115, 111, 107, 103, 100])
        self.assertEqual(prices[-1], 100)

    def test_never_below_floor(self):
        self.assertEqual(counter_ask(260, 275, 260), 260)
        self.assertEqual(counter_ask(260, 275, 270), 266)
        self.assertEqual(counter_ask(250, 240, None), 250)

    def test_reject_bad_inputs(self):
        with self.assertRaises(ValueError):
            counter_ask(100, float("nan"), None)
        with self.assertRaises(ValueError):
            counter_ask(100, 120, True)


if __name__ == "__main__":
    unittest.main()
