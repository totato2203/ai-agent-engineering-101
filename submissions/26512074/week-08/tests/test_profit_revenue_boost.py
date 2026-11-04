"""Focused regression checks for profitable seller negotiation and replenishment."""
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import optimizer as o
from round3 import procurement


class ProfitRevenueBoostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.md = Path(self.temp.name)
        self.now = 200000
        self.unit = {
            'unit': 'u1', 'sku': 'G11111111', 'name': 'Test goods',
            'cost': 10000, 'list_price': 20000, 'kind': 'goods',
            'grade': 'A', 'supplied_at': self.now - 1000,
            'expires_at': None,
        }
        self.inventory = {'round': 3, 'balance': 5000000, 'units': [self.unit]}

    def tearDown(self):
        self.temp.cleanup()

    def test_floor_stays_above_cost_on_every_turn(self):
        base = {'ask': 11500, 'floor': 10100}
        first = o.choose_quote(self.md, 't', self.unit, self.inventory,
                               base, self.now, SimpleNamespace(random=lambda: 1))
        repeated = o.choose_quote(self.md, 't', self.unit, self.inventory,
                                  base, self.now + 5, SimpleNamespace(random=lambda: 1))
        self.assertEqual(first['ask'], 11500)
        self.assertEqual(first['floor'], 10600)
        self.assertEqual(repeated['floor'], first['floor'])
        self.assertEqual(repeated['ask'], first['ask'])

    def test_market_median_can_raise_opening_without_breaking_list_ceiling(self):
        base = {'ask': 11500, 'floor': 10100,
                'market_samples': 4, 'market_median': 15000}
        q = o.choose_quote(self.md, 'market', self.unit, self.inventory,
                           base, self.now, SimpleNamespace(random=lambda: 1))
        self.assertEqual(q['ask'], 15450)
        self.assertLessEqual(q['floor'], q['ask'])
        self.assertLessEqual(q['ask'], self.unit['list_price'])

    def test_high_demand_explores_more_profitable_quote(self):
        with o.db(self.md) as c:
            for i in range(2):
                c.execute(
                    'insert into trials(task,sku,unit,at,arm,grade,kind,cost,settled_at,margin) '
                    'values(?,?,?,?,?,?,?,?,?,?)',
                    (f'old-{i}', self.unit['sku'], f'old-unit-{i}',
                     self.now-900+i*100, .15, 'A', 'goods', 10000,
                     self.now-850+i*100, 1000))
        q = o.choose_quote(self.md, 'high', self.unit, self.inventory,
                           {'ask': 11500, 'floor': 10100},
                           self.now, SimpleNamespace(random=lambda: 0))
        self.assertGreaterEqual(q['arm'], .25)
        self.assertGreaterEqual(q['floor'], 11000)
        self.assertLessEqual(q['floor'], q['ask'])

    def test_sparse_buyer_can_be_countered_twice_then_closed(self):
        with o.db(self.md) as c:
            c.execute('insert into trials(task,sku,unit,at) values(?,?,?,?)',
                      ('t', self.unit['sku'], self.unit['unit'], self.now))
        deal = {'unit': self.unit, 'ask': 15000, 'offer': 11000,
                'lines': ['buyer: request', 'buyer: 11000']}
        first = o.negotiate(self.md, 't', deal,
                            {'ask': 15000, 'floor': 10600}, self.now)
        self.assertEqual(first['action'], 'ask')
        deal.update(previous_offer=11000, offer=11800,
                    ask=first['price'], lines=deal['lines']+['buyer: 11800'])
        second = o.negotiate(self.md, 't', deal,
                             {'ask': 15000, 'floor': 10600}, self.now)
        self.assertEqual(second['action'], 'ask')
        deal.update(offer=second['price'], ask=second['price'],
                    lines=deal['lines']+['buyer: agreed'])
        third = o.negotiate(self.md, 't', deal,
                            {'ask': 15000, 'floor': 10600}, self.now)
        self.assertEqual(third['action'], 'accept')

    def test_expiry_clearance_keeps_recovery_floor(self):
        food = dict(self.unit,kind='food',expires_at=self.now+1800)
        inv = dict(self.inventory,units=[food])
        q = o.choose_quote(self.md, 'clearance', food, inv,
                           {'ask': 8000, 'floor': 2000},
                           self.now, SimpleNamespace(random=lambda: 1))
        self.assertEqual(q['ask'], 8000)
        self.assertEqual(q['floor'], 2000)

    def test_replenishment_prefers_proven_absolute_profit(self):
        now = self.now
        catalog = {
            'cheap': {'list_price': 2000, 'kind': 'goods'},
            'premium': {'list_price': 20000, 'kind': 'goods'},
        }
        inv = {'round': 3, 'balance': 5000000,
               'restock': {'open': True}, 'units': []}
        ledger = []
        for i, sku in enumerate(['cheap','premium']):
            for k in range(2):
                ledger.append({'seq': 10*i+k, 'kind': 'settle', 'round': 3,
                               'ts': now-600-k*60,
                               'data': {'shop': 'totato2203-r3',
                                        'item': sku,
                                        'amount': 1100 if sku=='cheap' else 11800}})
        with o.db(self.md) as c:
            c.execute('insert into units values(?,?,?,?)',('c','cheap',1000,now-10000))
            c.execute('insert into units values(?,?,?,?)',('p','premium',10000,now-10000))
        original = o.db
        with patch('optimizer.db',side_effect=lambda unused: original(self.md)):
            orders = procurement(inv,catalog,ledger,now)['buy']
        self.assertTrue(orders)
        self.assertEqual(orders[0]['sku'], 'premium')


if __name__ == '__main__':
    unittest.main()
