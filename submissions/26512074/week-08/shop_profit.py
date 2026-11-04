"""Inventory exposure and market-based cash recovery for shop ranking."""
from statistics import median
import math
import json
from pathlib import Path

_ledger_cache={}


def recent_ledger(path,now):
    key=str(path)
    cached=_ledger_cache.get(key)
    if cached and now-cached[0]<30:
        return cached[1]
    try:
        with Path(path).open('rb') as source:
            source.seek(0,2)
            size=source.tell()
            source.seek(max(0,size-8*1024*1024))
            if size>8*1024*1024:
                source.readline()
            rows=[]
            for line in source:
                try:
                    event=json.loads(line)
                except ValueError:
                    continue
                if now-event.get('ts',0)<7200:
                    rows.append(event)
    except FileNotFoundError:
        rows=[]
    _ledger_cache[key]=(now,rows)
    return rows

REGISTRATION='totato2203-r3'
DISPLAY='tomato&potato'
ALIASES={REGISTRATION,DISPLAY}
CASH_RESERVE=2000000
INVENTORY_CAP=1500000


def exposure(inventory):
    return sum(u['cost'] for u in inventory.get('units',[]))


def buy_budget(inventory):
    return max(0,min(250000,inventory.get('balance',0)-CASH_RESERVE,
                     INVENTORY_CAP-exposure(inventory)))


def own_events(ledger):
    return [e for e in ledger if e.get('data',{}).get('shop') in ALIASES]


def recovery_price(unit,inventory,ledger,now):
    """Use actual same-SKU/grade settlements; never label estimates as quotes."""
    if unit.get('grade')=='expired' or (unit.get('expires_at') is not None and unit['expires_at']<=now):
        return None
    cost=unit['cost']
    prices=[]
    seen=set()
    for e in ledger:
        d=e.get('data',{})
        if e.get('kind')!='settle' or e.get('round',3)!=3 or e.get('seq') in seen:
            continue
        seen.add(e.get('seq'))
        price=d.get('amount')
        if (d.get('sku') or d.get('item'))!=unit['sku'] or d.get('grade')!=unit.get('grade'):
            continue
        if not 0<=now-e.get('ts',0)<7200 or isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0:
            continue
        prices.append(price)
    stressed=inventory.get('balance',0)<CASH_RESERVE or exposure(inventory)>INVENTORY_CAP
    margin=.05 if stressed else .15
    # Reserve covers acquisition and a positive unit margin, without adding
    # seven speculative future storage days to today's acceptance threshold.
    floor=math.ceil(cost*1.01)
    ask=math.ceil(cost*(1+margin))
    if len(prices)>=3:
        ask=min(ask,math.floor(median(prices)*.99))
    ask=max(floor,min(unit['list_price'],ask))
    if unit.get('expires_at') is not None:
        hours=(unit['expires_at']-now)/3600
        if hours<6:
            ask=max(1,math.floor(ask*max(.1,hours/6)))
            floor=max(1,math.floor(ask*.8))
    return {'ask':ask,'floor':floor,'market_samples':len(prices),
            'market_median':median(prices) if len(prices)>=3 else None,
            'cash_recovery':stressed}
