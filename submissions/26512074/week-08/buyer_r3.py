"""Round 3 buyer: catalog SKUs, bounded offers, checkout certificate constraints."""
import argparse
import asyncio
import json
import math
from pathlib import Path
import time
from protocol import A2AClient, receipt, task_state, task_text
from policy import read_price
from round3 import read


def candidates(shops,order,catalog,payments=()):
    rows=[]
    acceptable=set(order.get('acceptable',[]))
    for shop in shops:
        own=[p for p in payments if p.get('shop')==shop['url']]
        reliability=(1+sum(p.get('paid') is True for p in own))/(2+len(own))
        for offer in shop.get('offers',[]):
            sku=offer['sku']
            if sku not in acceptable or offer.get('qty',0)<1 or sku not in catalog:
                continue
            value=catalog[sku]['list_price']
            # Positive surplus if non-food survives; actual failure rates are unknown.
            ceiling=min(order['budget'],math.floor(value*.85))
            if ceiling>0:
                rows.append((reliability*value*.15,shop,sku,ceiling))
    return sorted(rows,key=lambda r:(-r[0],r[1]['url'],r[2]))


async def buy(shops,order,catalog,payments=()):
    result={'shop':None,'receipt':None,'stars':3,'review':'No settled purchase.'}
    accept={'cert':True}
    if order.get('kind')=='food':
        accept['min_hours_left']=order.get('use_within_hours',0)+.05
    result['accept']=accept
    rows=candidates(shops,order,catalog,payments)
    # Discovery is read-only. Try another seller only before a binding offer.
    for _,shop,sku,ceiling in rows[:5]:
        result['shop']=shop['url']
        async with A2AClient(shop['url'],timeout=30) as client:
            try:
                await client.discover()
                task=await client.send(f'I want to buy {catalog[sku]["name"]} ({sku}). Quote the total price.')
            except Exception:
                continue
            last=None
            try:
                for turn in range(4):
                    if order.get('expires',math.inf)<=time.time():
                        await client.cancel(task['id'])
                        return result
                    state=task_state(task)
                    if state=='TASK_STATE_COMPLETED':
                        result['receipt']=receipt(task,sku,order['budget'],last)
                        result['review']='Signed artifact received; market validates signature and checkout before payment.'
                        return result
                    if state!='TASK_STATE_INPUT_REQUIRED':
                        return result
                    ask=await read_price(task_text(task),role='ask',metadata={})
                    if ask is None or isinstance(ask,bool) or not math.isfinite(ask) or ask<0:
                        await client.cancel(task['id'])
                        return result
                    offer=min(ceiling,math.floor(ask*(.8+.1*turn)))
                    if ask<=ceiling and turn>0:
                        offer=math.floor(ask)
                    if offer==last:
                        await client.cancel(task['id'])
                        return result
                    last=offer
                    task=await client.send(str(offer),task['id'])
                if task_state(task)=='TASK_STATE_COMPLETED':
                    result['receipt']=receipt(task,sku,order['budget'],last)
                else:
                    await client.cancel(task['id'])
                return result
            except Exception as exc:
                result['review']='Uncertain negotiation; no additional supplier contacted: '+type(exc).__name__
                return result
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--shops',type=Path,required=True)
    p.add_argument('--order',type=Path,required=True)
    p.add_argument('--item',required=True)
    p.add_argument('--budget',type=float,required=True)
    a=p.parse_args()
    order=read(a.order,{})
    order['budget']=min(order['budget'],a.budget)
    from round3 import lines
    out=asyncio.run(buy(read(a.shops,[]),order,read(a.order.parent/'catalog.json',{}),
                       lines(a.order.parent/'payments.jsonl')))
    print(json.dumps(out,ensure_ascii=False))
