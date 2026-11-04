"""Round 3 official kit-v4 hooks; no registration, HTTP, or publication."""
import argparse
from collections import Counter, defaultdict
import json
import math
import os
from pathlib import Path
import time
DAY = 86400

def read(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return default

def lines(path):
    if not Path(path).exists():
        return []
    return [json.loads(s) for s in Path(path).read_text(encoding='utf-8').splitlines() if s.strip()]

def write(path, value):
    path = Path(path)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)

def forecast(ledger, now):
    bins, seen = defaultdict(lambda: [0] * 7), set()
    for event in ledger:
        if event.get('kind') != 'settle' or event.get('round',3)!=3 or event.get('seq') in seen:
            continue
        seen.add(event['seq'])
        age = (now - event['ts']) / DAY
        sku = event.get('data', {}).get('sku') or event.get('data', {}).get('item')
        if sku and 0 <= age < 7:
            bins[sku][int(age)] += 1
    weights = [math.exp(-i / 3) for i in range(7)]
    result = {}
    for sku, counts in bins.items():
        rate = sum(w * n for w, n in zip(weights, counts)) / sum(weights)
        sigma = math.sqrt(sum(w * (n-rate)**2 for w,n in zip(weights,counts)) / sum(weights))
        result[sku] = {'rate': rate, 'sigma': sigma}
    return result

def pricing(unit, now, rate=0, competitor=None, failure=.1, warranty_hours=0):
    expiry = unit.get('expires_at')
    if unit.get('grade') == 'expired' or expiry is not None and expiry <= now:
        return None
    cost, listed = unit['cost'], unit['list_price']
    holding = 0 if unit['kind'] == 'food' else cost * .01 * min(7,1/max(rate,.1))
    risk = failure if warranty_hours else 0
    floor = math.ceil((cost+holding)/(1-risk))
    ask = max(floor,min(listed,competitor-1 if competitor else listed))
    if expiry is not None:
        hours = (expiry-now)/3600
        if hours < 6:
            ask = max(1,round(ask*max(.1,hours/6)))
            floor = max(1,round(ask*.8))
    return {'ask':ask,'floor':floor,'warranty_hours':warranty_hours,
            'expected_profit':ask*(1-risk)-cost-holding}

def procurement(inv,catalog,ledger,now):
    if inv.get('round',3)<3 or not inv.get('restock',{}).get('open',False):
        return {'buy':[]}
    from shop_profit import buy_budget,own_events
    from optimizer import config,db
    policy=config()
    cash = buy_budget(inv)
    if cash<=0:
        return {'buy':[]}
    rates = forecast(own_events(ledger),now)
    held = Counter(u['sku'] for u in inv.get('units',[]) if u.get('grade')!='expired'
                   and (u.get('expires_at') or math.inf)>now)
    candidates = []
    for sku,p in catalog.items():
        listed = p['list_price']
        if listed<=0:
            continue
        r = rates.get(sku,{'rate':0,'sigma':0})
        # Carry three supply cycles instead of buying for only twenty minutes.
        horizon = 20/1440
        target = math.ceil(r['rate']*horizon+2*r['sigma']*math.sqrt(horizon))
        if r['rate']>0:
            target=max(target,1 if p['kind']=='food' else 2)
            target=min(target,4)
        if p['kind']=='food':
            target = min(target,max(1,math.floor(r['rate']*3*p.get('shelf_hours',0)/24*.45)))
        if not rates and sum(held.values())<6:
            target = 1
        target=math.ceil(target*policy['stock_multiplier'])
        need = max(0,target-held[sku])
        if need:
            worst=math.ceil(listed*.75)
            own_sales=[e['data']['amount'] for e in own_events(ledger) if e.get('kind')=='settle'
                       and (e['data'].get('sku') or e['data'].get('item'))==sku
                       and 0<=now-e.get('ts',0)<7*DAY and isinstance(e['data'].get('amount'),(int,float))]
            from statistics import median
            expected=median(own_sales) if own_sales else worst*1.05
            with db(Path(__file__).resolve().parent/'.market') as c:
                costs=[v[0] for v in c.execute('select cost from units where sku=? order by supplied desc limit 20',(sku,))]
            # Replacement cost is an estimate from observed acquisitions; the
            # budget still reserves the official worst-case supply price.
            estimated_cost=sum(costs)/len(costs) if costs else worst
            wait=1/max(r['rate'],.1)
            storage=estimated_cost*inv.get('storage_per_day',.01)*min(wait,7) if p['kind']=='goods' else 0
            survival=min(1,r['rate']*p.get('shelf_hours',24)/24) if p['kind']=='food' and own_sales else 1
            net=(expected-estimated_cost-storage)*survival-estimated_cost*(1-survival)
            if own_sales and net<=0:continue
            roi=net/(max(estimated_cost,1)*max(wait,1/24))
            # Pure percentage ROI overweights cheap, low-ticket goods. For SKUs
            # with proven settlements, also reward absolute profit per day,
            # scaled by sqrt(capital) to avoid buying slow luxury stock blindly.
            profit_velocity=net/max(wait,1/24)/math.sqrt(max(estimated_cost,1))
            confidence=min(1,len(own_sales)/3)
            score=roi+confidence*profit_velocity
            candidates.append((score,sku,need,worst))
    buy=[]
    probe_left=max(0,6-sum(held.values()))
    for _,sku,need,worst_cost in sorted(candidates,key=lambda x:(-x[0],x[3],x[1])):
        qty=min(20,need,cash//worst_cost)
        if not rates:
            qty=min(qty,probe_left)
        if qty:
            buy.append({'sku':sku,'qty':qty})
            cash-=qty*worst_cost
            probe_left-=qty
        if len(buy)==10:
            break
    return {'buy':buy}

def review(deal):
    honest=deal['settled'].get('claim_honest')
    return {'stars':2 if honest is False else 5,'review':
            'Settled purchase; grade claim was false.' if honest is False else
            'Payment settled; no unobserved quality or failure claims.'}

def refresh_ledger(md):
    """Called only by a future live hook; public read, resumable and bounded."""
    from urllib.request import urlopen
    memory=read(md/'ledger-cursor.json',{'after':-500})
    for _ in range(4):
        with urlopen('https://market.ourolabs.ai/api/ledger?after='+str(memory['after']),timeout=5) as response:
            rows=json.load(response)
        if not rows:
            break
        # Cursor advances after durable append. Forecast deduplicates a replay.
        with (md/'ledger.jsonl').open('a',encoding='utf-8') as out:
            for row in rows:
                out.write(json.dumps(row,ensure_ascii=False)+'\n')
        memory['after']=rows[-1]['seq']
        write(md/'ledger-cursor.json',memory)
        if len(rows)<500:
            break

def restock_hook(state,now=None):
    md=Path(state)
    now=time.time() if now is None else now
    inv=read(md/'inventory.json',{})
    catalog=read(md/'catalog.json',{})
    ledger=lines(md/'ledger.jsonl')
    result=procurement(inv,catalog,ledger,now)
    if os.environ.get('ROUND3_FORUM_ENABLED')=='1' and (md/'recommendations-ready.json').exists():
        from recommendations import ensure_worker
        ensure_worker(md)
    return result

def main():
    parser=argparse.ArgumentParser()
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--state',type=Path)
    group.add_argument('--deal',type=Path)
    args=parser.parse_args()
    print(json.dumps(restock_hook(args.state) if args.state else review(read(args.deal,{})),ensure_ascii=False))
if __name__=='__main__':
    main()
