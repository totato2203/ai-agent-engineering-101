"""Round 3 buyer: catalog SKUs, bounded offers, checkout certificate constraints."""
import argparse
import asyncio
import json
import math
import re
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
                history=[p['price'] for p in own if p.get('paid') and p.get('item')==sku and isinstance(p.get('price'),(int,float))]
                from statistics import median
                expected=min(ceiling,median(history)) if history else ceiling
                # Beta-smoothed actual checkout success, not public star claims.
                rows.append((reliability*max(0,value-expected),shop,sku,ceiling))
    return sorted(rows,key=lambda r:(-r[0],r[1]['url'],r[2]))


def terms_failure(rec,order):
    if rec.get('cert') is False:
        return 'seller explicitly disabled the required certificate'
    return None


def stated_lifetime(text):
    m=re.search(r'(\d+(?:\.\d+)?)\s*(?:hours?|h)\s+(?:of\s+)?shelf life left',text,re.I)
    return float(m.group(1)) if m else None


def checkout_feedback(payments,memory,now):
    """Brief SKU-level cooldown after repeated, confirmed stale-stock failures.

    The persisted order ID prevents old failures from restarting the cooldown
    forever. Other products and other shops remain eligible.
    """
    groups={}
    for p in payments[-100:]:
        groups.setdefault((p.get('shop'),p.get('item')),[]).append(p)
    for (shop,sku),rows in groups.items():
        if not shop or not sku:continue
        audit=memory.setdefault(shop,{})
        cooldowns=audit.setdefault('stock_cooldowns',{})
        if rows[-1].get('paid') is True:
            cooldowns.pop(sku,None)
        elif len(rows)>=2 and all(p.get('paid') is False and 'not in stock' in p.get('reason','') for p in rows[-2:]):
            last=rows[-1].get('order')
            if last and cooldowns.get(sku,{}).get('order')!=last:
                cooldowns[sku]={'order':last,'until':now+300,'reason':'repeated confirmed checkout stock failures'}


async def buy(shops,order,catalog,payments=(),memory=None):
    memory={} if memory is None else memory
    checkout_feedback(list(payments),memory,time.time())
    result={'shop':None,'receipt':None,'stars':3,'review':'No eligible stock for acceptable SKUs.',
            'strategy_revision':'retry-v2'}
    accept={'cert':True}
    required=order.get('use_within_hours',0)+.05 if order.get('kind')=='food' else None
    if required is not None:
        accept['min_hours_left']=required
    result['accept']=accept
    rows=candidates(shops,order,catalog,payments)
    seen=set()
    failures=[]
    for _,shop,sku,ceiling in rows:
        if memory.get(shop['url'],{}).get('stock_cooldowns',{}).get(sku,{}).get('until',0)>time.time():
            continue
        if shop['url'] in seen or len(seen)>=6:
            continue
        if memory.get(shop['url'],{}).get('avoid_until',0)>time.time():
            continue
        seen.add(shop['url'])
        if order.get('expires',math.inf)<=time.time()+5:
            break
        result['shop']=shop['url']
        task=None
        async with A2AClient(shop['url'],timeout=20) as client:
            try:
                await client.discover()
                terms=' Require a market certificate.'
                if required is not None:
                    terms+=f' Food must last at least {required:g} hours at checkout; select a suitable unit.'
                task=await client.send(f'I want to buy {catalog[sku]["name"]} ({sku}). Quote the total price.'+terms)
                last=None
                for turn in range(5):
                    if order.get('expires',math.inf)<=time.time()+3:
                        break
                    state=task_state(task)
                    if state=='TASK_STATE_COMPLETED':
                        try:
                            rec=receipt(task,sku,order['budget'],last)
                        except ValueError as exc:
                            memory[shop['url']]={'avoid_until':time.time()+3600,
                                                 'reason':'receipt violation: '+str(exc)}
                            raise
                        why=terms_failure(rec,order)
                        if why:
                            memory[shop['url']]={'avoid_until':time.time()+600,'reason':why}
                            raise ValueError(why)
                        result.update(receipt=rec,review='Receipt fits authorized offer; kit verifies certificate, signature and checkout.')
                        return result
                    if state!='TASK_STATE_INPUT_REQUIRED':
                        failures.append(shop['name']+': '+state)
                        break
                    text=task_text(task)
                    lifetime=stated_lifetime(text)
                    if required is not None and lifetime is not None and lifetime<required:
                        failures.append(shop['name']+': stated shelf life below order requirement')
                        break
                    metadata=task.get('status',{}).get('message',{}).get('metadata',{})
                    ask=await read_price(text,role='ask',metadata=metadata,allow_model=False)
                    audit=memory.setdefault(shop['url'],{})
                    audit.setdefault('quotes',[]).append({'at':time.time(),'sku':sku,'ask':ask})
                    audit['quotes']=audit['quotes'][-30:]
                    if ask is None or isinstance(ask,bool) or not math.isfinite(ask) or ask<0:
                        failures.append(shop['name']+': no usable quote')
                        break
                    if ask<=ceiling and turn>0:
                        offer=math.floor(ask)
                    else:
                        offer=min(ceiling,max(last or 0,math.floor(ask*(.8+.1*turn))))
                    if offer==last:
                        failures.append(shop['name']+': seller refused price ceiling')
                        break
                    audit['last_offer']=offer
                    last=offer
                    task=await client.send(str(offer),task['id'])
                # Inspect a completed final response before proceeding elsewhere.
                if task_state(task)=='TASK_STATE_COMPLETED':
                    rec=receipt(task,sku,order['budget'],last)
                    why=terms_failure(rec,order)
                    if not why:
                        result.update(receipt=rec,review='Receipt fits authorized offer; awaiting kit checkout checks.')
                        return result
                    failures.append(shop['name']+': '+why)
            except Exception as exc:
                failures.append(shop['name']+': '+type(exc).__name__+': '+str(exc)[:180])
            finally:
                if task and task_state(task)=='TASK_STATE_INPUT_REQUIRED':
                    try:
                        await client.cancel(task['id'])
                    except Exception:
                        pass
            # Negotiation receipts do not move money: only the single returned
            # receipt reaches the kit's signed mandate and ACP payment path.
    result['review']='; '.join(failures[-4:]) if failures else result['review']
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
    from round3 import lines,write
    memory_path=a.order.parent/'buyer-observations.json'
    memory=read(memory_path,{})
    out=asyncio.run(buy(read(a.shops,[]),order,read(a.order.parent/'catalog.json',{}),
                       lines(a.order.parent/'payments.jsonl'),memory))
    write(memory_path,memory)
    print(json.dumps(out,ensure_ascii=False))
