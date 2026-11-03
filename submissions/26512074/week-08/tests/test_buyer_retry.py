import unittest
from unittest.mock import patch,AsyncMock
import buyer_r3


def task(state,text='',price=None):
    t={'id':'t','status':{'state':state,'message':{'parts':[{'text':text}]}}}
    if price is not None:
        t['artifacts']=[{'parts':[{'data':{'shop':'s','item':'x','price':price,'task':'t','sig_seller':'placeholder'}}]}]
    return t

class FakeClient:
    scripts={}
    visits=[]
    def __init__(self,url,**kwargs):
        self.url=url
        self.answers=list(self.scripts[url])
    async def __aenter__(self):
        self.visits.append(self.url)
        return self
    async def __aexit__(self,*args):
        pass
    async def discover(self):
        return {}
    async def send(self,*args):
        return self.answers.pop(0)
    async def cancel(self,*args):
        return {}

class BuyerRetryTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self,first,order=None):
        FakeClient.visits=[]
        FakeClient.scripts={'http://a':first,'http://b':[
            task('TASK_STATE_INPUT_REQUIRED','asking 80'),
            task('TASK_STATE_INPUT_REQUIRED','asking 80'),
            task('TASK_STATE_COMPLETED',price=80)]}
        shops=[{'url':'http://'+s,'name':s,'offers':[{'sku':'x','qty':1}]} for s in ['a','b']]
        memory={}
        with patch.object(buyer_r3,'A2AClient',FakeClient):
            result=await buyer_r3.buy(shops,order or {'budget':100,'acceptable':['x']},
                                       {'x':{'list_price':100,'name':'X'}},memory=memory)
        self.assertEqual(result['shop'],'http://b')
        self.assertEqual(result['receipt']['price'],80)
        self.assertEqual(FakeClient.visits,['http://a','http://b'])
        return memory
    async def test_rejection_tries_next_shop(self):
        await self.run_case([task('TASK_STATE_REJECTED')])
    async def test_overcharge_blocked_and_next_shop_used(self):
        memory=await self.run_case([task('TASK_STATE_INPUT_REQUIRED','asking 80'),
             task('TASK_STATE_INPUT_REQUIRED','asking 80'),task('TASK_STATE_COMPLETED',price=90)])
        self.assertIn('receipt violation',memory['http://a']['reason'])
    async def test_insufficient_food_lifetime_tries_next(self):
        await self.run_case([task('TASK_STATE_INPUT_REQUIRED','345 h of shelf life left. asking 80')],
                            {'budget':100,'acceptable':['x'],'kind':'food','use_within_hours':540})
    async def test_certificate_refusal_tries_next(self):
        end=task('TASK_STATE_COMPLETED',price=80)
        end['artifacts'][0]['parts'][0]['data']['cert']=False
        await self.run_case([task('TASK_STATE_INPUT_REQUIRED','asking 80'),
                            task('TASK_STATE_INPUT_REQUIRED','asking 80'),end])

if __name__=='__main__':
    unittest.main()
