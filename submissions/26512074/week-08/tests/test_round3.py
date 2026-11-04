import unittest
from round3 import DAY,forecast,pricing,procurement,review
class Round3Tests(unittest.TestCase):
    def test_ledger(self):
        r={'seq':1,'kind':'settle','ts':DAY,'data':{'item':'x'}}
        self.assertEqual(forecast([r],DAY),forecast([r,r,{**r,'seq':2,'kind':'order'}],DAY))
    def test_procurement(self):
        cat={str(i):{'list_price':10000,'kind':'goods'} for i in range(20)}
        inv={'balance':3000000,'restock':{'open':True},'units':[]}
        self.assertEqual(sum(x['qty'] for x in procurement(inv,cat,[],DAY)['buy']),6)
        inv['units']=[{'sku':str(i),'cost':0} for i in range(6)]
        self.assertEqual(procurement(inv,cat,[],DAY)['buy'],[])
        inv.update(balance=750000,units=[])
        self.assertEqual(procurement(inv,cat,[],DAY)['buy'],[])
        inv.update(balance=1000000,restock={'open':False})
        self.assertEqual(procurement(inv,cat,[],DAY)['buy'],[])
    def test_pricing(self):
        u={'cost':80,'list_price':100,'kind':'food','expires_at':3600}
        self.assertLess(pricing(u,0)['ask'],80)
        self.assertIsNone(pricing(u,3600))
        u.update(kind='goods',expires_at=None)
        self.assertGreater(pricing(u,0,warranty_hours=6)['floor'],pricing(u,0)['floor'])
    def test_review(self):
        self.assertEqual(review({'settled':{'claim_honest':False}})['stars'],2)
    def test_popular_stock_target_and_spend_limit(self):
        cat={'x':{'list_price':100000,'kind':'goods'}}
        inv={'balance':5000000,'restock':{'open':True},'units':[]}
        events=[{'seq':1,'kind':'settle','ts':DAY,'data':{'item':'x','shop':'totato2203-r3'}}]
        buy=procurement(inv,cat,events,DAY)['buy']
        self.assertEqual(buy,[{'sku':'x','qty':2}])
        inv['balance']=800000
        self.assertEqual(procurement(inv,cat,events,DAY)['buy'],[])
if __name__=='__main__':
    unittest.main()
