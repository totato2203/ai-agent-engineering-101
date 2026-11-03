import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
import buyer_r3
import seller_r3
from round3 import restock_hook
from signing import verify_receipt
import base64

class ContractTests(unittest.TestCase):
    def test_buyer_acceptable_stock_budget(self):
        shops=[{'url':'http://shop','offers':[{'sku':'x','qty':1},{'sku':'y','qty':1}]}]
        order={'acceptable':['x'],'budget':60}
        rows=buyer_r3.candidates(shops,order,{'x':{'list_price':100}})
        self.assertEqual([(r[2],r[3]) for r in rows],[('x',60)])

    def test_seller_signs_canonical_body_and_retains_unit(self):
        with tempfile.TemporaryDirectory() as d:
            key=Ed25519PrivateKey.generate()
            keypath=Path(d)/'key.pem'
            keypath.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            real_path=Path
            with patch.object(seller_r3,'Path',side_effect=lambda p:keypath if p=='shop_key.pem' else real_path(p)):
                rec=seller_r3.sign({'shop':'s','item':'x','price':10,'task':'t','unit':'u','cert':True})
            public=base64.b64encode(key.public_key().public_bytes_raw()).decode()
            verify_receipt(rec,public)
            self.assertEqual(rec['unit'],'u')
            self.assertTrue(rec['cert'])

    def test_restock_contract_drafts_no_publish(self):
        with tempfile.TemporaryDirectory() as d:
            md=Path(d)
            inv={'round':3,'balance':1000000,'restock':{'open':True},'units':[
                {'unit':'u','sku':'x','name':'X','kind':'goods','cost':50,'list_price':100}]}
            (md/'inventory.json').write_text(json.dumps(inv))
            (md/'catalog.json').write_text(json.dumps({'x':{'kind':'goods','list_price':100}}))
            result=restock_hook(md,10000)
            self.assertEqual(result,{'buy':[]})
            self.assertFalse((md/'outbox.jsonl').exists())
            self.assertTrue((md/'forum-drafts.json').exists())

    def test_a2a_app_build(self):
        self.assertTrue(seller_r3.build(9301).routes)

if __name__=='__main__':
    unittest.main()
