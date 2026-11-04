import unittest
from shop_profit import buy_budget,recovery_price,own_events,DISPLAY

class ShopProfitTests(unittest.TestCase):
    def test_overstock_and_cash_reserve_block_purchases(self):
        self.assertEqual(buy_budget({'balance':5000000,'units':[{'cost':1600000}]}),0)
        self.assertEqual(buy_budget({'balance':1900000,'units':[]}),0)
        self.assertEqual(buy_budget({'balance':2200000,'units':[]}),200000)
    def test_cash_recovery_price_uses_matching_grade_and_positive_margin(self):
        unit={'sku':'x','grade':'B','kind':'goods','cost':100,'list_price':180}
        events=[{'seq':i,'kind':'settle','round':3,'ts':1000,'data':{'sku':'x','grade':'B','amount':130}} for i in range(3)]
        events.append({'seq':99,'kind':'settle','ts':1000,'data':{'sku':'x','grade':'C','amount':1}})
        p=recovery_price(unit,{'balance':1000000,'units':[]},events,1100)
        self.assertEqual(p['market_median'],130)
        self.assertEqual(p['market_samples'],3)
        self.assertLess(p['ask'],180)
        self.assertGreater(p['floor'],100)
    def test_only_own_sales_drive_replenishment(self):
        rows=[{'data':{'shop':'other'}},{'data':{'shop':'totato2203-r3'}}]
        self.assertEqual(own_events(rows),[rows[1]])
        self.assertEqual(DISPLAY,'tomato&potato')

if __name__=='__main__':
    unittest.main()
