import json
from pathlib import Path
import tempfile
import unittest
from community import service,relevant_stock,kind

class CommunityTests(unittest.TestCase):
    def setUp(self):
        self.inv={'units':[{'sku':'X','name':'김치','category':'식품>김치'}]}
        self.forum=[{'id':17,'ts':900,'author':'other','owner':'other','thread':None,'text':'김치 시세 분석 정보'}]
    def test_like_acknowledgement_precedes_reply_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            md=Path(d)
            self.assertEqual(service(md,self.inv,self.forum,[],1000,True)['status'],'like_queued')
            action=json.loads((md/'outbox.jsonl').read_text(encoding='utf-8'))
            self.assertEqual(action,{'vote':17,'value':1,'as':'shop'})
            (md/'outbox.jsonl').unlink()
            ack={'sent':action,'status':200,'answer':'{"counted":false}'}
            (md/'outbox.sent.jsonl').write_text(json.dumps(ack)+'\n')
            self.assertEqual(service(md,self.inv,self.forum,[],1040,True)['status'],'reply_queued')
            comment=json.loads((md/'outbox.jsonl').read_text(encoding='utf-8'))
            self.assertEqual(comment['thread'],17)
            self.assertIn('좋아요를 눌렀습니다',comment['post'])
            self.assertIn('제 글에도 좋아요',comment['post'])
            original=(md/'outbox.jsonl').read_text(encoding='utf-8')
            service(md,self.inv,self.forum,[],1100,True)
            self.assertEqual((md/'outbox.jsonl').read_text(encoding='utf-8'),original)
    def test_rejected_vote_never_claimed_in_reply(self):
        with tempfile.TemporaryDirectory() as d:
            md=Path(d)
            service(md,self.inv,self.forum,[],1000,True)
            vote=json.loads((md/'outbox.jsonl').read_text(encoding='utf-8'))
            (md/'outbox.jsonl').unlink()
            (md/'outbox.sent.jsonl').write_text(json.dumps({'sent':vote,'status':403})+'\n')
            service(md,self.inv,self.forum,[],1040,True)
            pending=[json.loads(l) for l in (md/'outbox.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertFalse(any(p.get('thread')==17 for p in pending))
    def test_relevance_self_and_expiry(self):
        post={**self.forum[0],'text':'김치 고장 불편'}
        self.assertEqual(kind(post),'complaint')
        self.assertEqual(len(relevant_stock(post,self.inv,1000)),1)
        self.assertEqual(relevant_stock(post,{'units':[dict(self.inv['units'][0],expires_at=999)]},1000),[])
        with tempfile.TemporaryDirectory() as d:
            md=Path(d)
            service(md,{'units':[]},[{**post,'author':'totato2203-r3'}],[],1000,True)
            self.assertFalse((md/'outbox.jsonl').exists())
if __name__=='__main__':
    unittest.main()
