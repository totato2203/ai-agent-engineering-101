import unittest
import tempfile
from pathlib import Path
import recommendations as r

class RecommendationTests(unittest.TestCase):
    def setUp(self):
        self.now=100000
        self.events=[{'seq':i,'kind':'settle','round':3,'ts':self.now-i*30,
                      'data':{'item':'x','amount':100,'shop':'other'}} for i in range(10)]
    def test_real_windows_dedup_and_reliability(self):
        groups=r.trades(self.events+self.events,self.now)
        self.assertEqual(len(groups['x']),10)
        f=r.features(groups['x'],2,[],'x',self.now)
        self.assertEqual(f['median'],100)
        self.assertIsNone(f['volume_growth'])
        q={'sku':'x','shop':r.NAME,'url':'http://shop','price':70,'at':self.now}
        self.assertGreater(r.score(f,q,self.now)['score'],12)
        self.assertIsNone(r.score(f,{**q,'price':100},self.now))
        self.assertIsNone(r.score(f,{**q,'at':self.now-301},self.now))
        self.assertIsNone(r.features(self.events[:2],2,[],'x',self.now))
    def test_post_includes_conditions_ad_and_source(self):
        f=r.features(self.events,2,[],'x',self.now)
        q={'sku':'x','shop':r.NAME,'url':'http://shop','price':70,'at':self.now}
        rec=r.score(f,q,self.now)
        post=r.render(rec,{'x':{'name':'X'}},{'units':[{'sku':'y','name':'Y'}]},'가격 메리트')
        self.assertIn('30.0%',post['post'])
        self.assertIn('우리 가게',post['post'])
        self.assertIn('좋아요',post['post'])
        self.assertIn('이전 기간 거래 없음',post['post'])
        self.assertEqual(len(post['refs']),5)
    def test_feedback_and_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            c=r.database(d)
            import json
            data={'score':25,'median':100,'price':70,'shop_profit_baseline':0}
            c.execute('insert into publications values(?,?,?,?,?,?,null)',('h',98000,'x','가격 메리트','body',json.dumps(data)))
            sent=[{'sent':{'post':'body'},'status':200,'answer':'{"post":3}'}]
            r.measure_feedback(c,self.events,[{'id':3,'ts':98000,'likes':2,'dislikes':0}],sent,100000,{'balance':5000000,'start':5000000})
            c.commit();c.close()
            c=r.database(d)
            f=json.loads(c.execute('select feedback from publications').fetchone()[0])
            self.assertTrue(f['mature'])
            self.assertEqual(f['likes'],2)
            self.assertEqual(f['status'],'published')
            self.assertIsNone(f['visits'])
            c.close()
if __name__=='__main__':
    unittest.main()
