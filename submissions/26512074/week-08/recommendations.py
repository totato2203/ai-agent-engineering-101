"""Evidence-based recommendations, persistent observations and feedback; no payment."""
import asyncio
from collections import Counter,defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
from statistics import median,pstdev
import subprocess
import sys
import time
from urllib.request import urlopen
from round3 import read,lines

NAME='totato2203-r3'
MARKER='[매수 기회 포착 | totato2203-r3]'
INTERVAL=300


def database(md):
    c=sqlite3.connect(Path(md)/'recommendations.sqlite3',timeout=10)
    c.execute('pragma journal_mode=WAL')
    c.executescript('''create table if not exists observations(at real,sku text,data text);
    create table if not exists publications(digest text primary key,at real,sku text,style text,body text,data text,feedback text);
    create table if not exists state(key text primary key,value text);''')
    return c


def trades(ledger,now):
    groups=defaultdict(list)
    seen=set()
    for e in ledger:
        d=e.get('data',{})
        price=d.get('amount')
        age=now-e.get('ts',0)
        if e.get('kind')!='settle' or e.get('round',3)!=3 or e.get('seq') in seen:
            continue
        seen.add(e.get('seq'))
        if isinstance(price,bool) or not isinstance(price,(int,float)) or not math.isfinite(price) or price<=0 or not 0<=age<86400:
            continue
        groups[d.get('sku') or d.get('item')].append(e)
    return groups


def features(events,stock,forum,sku,now):
    recent=[e for e in events if now-e['ts']<3600]
    prev=[e for e in events if 3600<=now-e['ts']<7200]
    short=[e for e in recent if now-e['ts']<900]
    older=[e for e in recent if 900<=now-e['ts']<1800]
    if len(recent)<3:
        return None
    prices=[e['data']['amount'] for e in recent]
    baseline=median(prices)
    previous=median([e['data']['amount'] for e in prev]) if len(prev)>=3 else None
    short_previous=median([e['data']['amount'] for e in older]) if len(older)>=3 else None
    short_median=median([e['data']['amount'] for e in short]) if len(short)>=3 else None
    requests=[p for p in forum if sku in p.get('text','') and
              any(word in p.get('text','').lower() for word in ('구합니다','구매 원','want to buy','wtb'))]
    request_now=sum(0<=now-p.get('ts',0)<3600 for p in requests)
    request_prev=sum(3600<=now-p.get('ts',0)<7200 for p in requests)
    return {'sku':sku,'median':baseline,'count':len(recent),'previous_count':len(prev),
        'volume_growth':(len(recent)-len(prev))/len(prev) if prev else None,
        'short_trend':short_median/short_previous-1 if short_median and short_previous else None,
        'medium_trend':baseline/previous-1 if previous else None,
        'frequency_per_minute':len(recent)/60,
        'request_count':request_now,'request_growth':(request_now-request_prev)/max(1,request_prev),
        'stock':stock,'volatility':pstdev(prices)/baseline,
        'confidence':min(1,len(prices)/10)/(1+pstdev(prices)/baseline),
        'refs':[e['seq'] for e in recent[-5:]],'latest_trade':max(e['ts'] for e in recent)}


def score(f,quote,now):
    if quote['price']<=0 or now-quote['at']>300 or quote['at']>now:
        return None
    discount=1-quote['price']/f['median']
    if discount<.03 or f['confidence']<.25:
        return None
    growth=max(-1,min(2,f['volume_growth'] or 0))
    shortage=min(1,f['count']/max(1,f['stock']))
    trend=max(-.2,min(.2,f['short_trend'] or f['medium_trend'] or 0))
    demand=max(-1,min(2,f['request_growth']))
    value=(discount*100+growth*8+shortage*8+trend*20+demand*3)*f['confidence']
    if value<12:
        return None
    return {**f,**quote,'discount':discount,'score':round(value,2),
            'strength':'강한 관심' if value>=30 else '관심', 'own':quote['shop']==NAME}


async def fetch_quotes(choices,catalog):
    from protocol import A2AClient,task_text,task_state
    from policy import read_price
    semaphore=asyncio.Semaphore(2)
    async def one(shop,sku):
        async with semaphore:
            task=None
            async with A2AClient(shop['url'],timeout=15) as client:
                try:
                    await client.discover()
                    task=await client.send(f'Quote only, no purchase authorization: {catalog[sku]["name"]} ({sku}). State current asking price and certificate availability.')
                    if task_state(task)!='TASK_STATE_INPUT_REQUIRED':
                        return None
                    ask=await read_price(task_text(task),role='ask',metadata=task.get('status',{}).get('message',{}).get('metadata',{}))
                    if ask is not None and not isinstance(ask,bool) and math.isfinite(ask) and ask>0:
                        return {'sku':sku,'shop':shop['name'],'url':shop['url'],'price':ask,'at':time.time()}
                except Exception:
                    return None
                finally:
                    if task:
                        try:
                            await client.cancel(task['id'])
                        except Exception:
                            pass
    return [q for q in await asyncio.gather(*(one(*choice) for choice in choices)) if q]


def stock_ad(inv):
    units=[u for u in inv.get('units',[]) if u.get('grade')!='expired' and
           (u.get('expires_at') is None or u['expires_at']>time.time())]
    counts=Counter(u['sku'] for u in units)
    names={u['sku']:u['name'] for u in units}
    return '; '.join(f'{sku} {names[sku][:22]} {qty}개' for sku,qty in counts.most_common(2)) or '현재 판매 가능한 재고 없음'


def render(r,catalog,inventory,style):
    trend=r['short_trend']
    direction=f'{trend*100:+.1f}%' if trend is not None else '비교 표본 부족'
    medium=f"{r['medium_trend']*100:+.1f}%" if r['medium_trend'] is not None else '비교 표본 부족'
    volume=f"{r['volume_growth']*100:+.0f}%" if r['volume_growth'] is not None else '이전 기간 거래 없음'
    text=(f"{MARKER} {style} · {r['strength']}\n{r['sku']} {catalog[r['sku']]['name'][:45]}\n"
        f"최근 1시간 중앙값 {r['median']:,.0f} / 문의 당시 호가 {r['price']:,.0f} credits "
        f"(관측 시세 대비 {r['discount']*100:.1f}% 낮음)\n"
        f"거래 {r['count']}건, 이전 1시간 {r['previous_count']}건; 관측 거래량 변화 {volume}. "
        f"15분 가격 추세 {direction}, 1시간 추세 {medium}; 공개 판매 재고 {r['stock']}개.\n"
        f"판매처: {r['shop']} {r['url']} · {'우리 가게 상품 홍보입니다. ' if r['own'] else ''}"
        '견적과 재고는 변동되며 인증서·등급·보증·남은 유통기한을 최종 확인하세요. '
        '동일 SKU라도 품질 조건이 다를 수 있습니다. 가격 비교 후 구매 문의해 보세요.\n'
        f"우리 가게 {NAME} 판매 중: {stock_ad(inventory)}. SKU별 견적, 시장 인증서 제공, 별도 보증 미제공.\n"
        '도움이 됐다면 좋아요로 알려주세요. 반응은 상세 분석 주제 선정과 지속적인 분석 개선에 참고합니다. '
        '향후 상승이나 재판매 이익을 보장하지 않습니다.')
    return {'post':text,'as':'buyer','refs':r['refs']}


def measure_feedback(c,ledger,forum,sent,now,inventory=None):
    for digest,at,sku,style,body,data,old in c.execute('select * from publications').fetchall():
        r=json.loads(data)
        acknowledgements=[s for s in sent if s.get('sent',{}).get('post')==body]
        success=next((s for s in acknowledgements if s.get('status')==200),None)
        post_id=None
        if success:
            try:
                post_id=json.loads(success.get('answer','{}')).get('post')
            except ValueError:
                pass
        post=next((p for p in forum if p.get('id')==post_id or p.get('text')==body),{})
        published_at=post.get('ts',at)
        after=[e for e in ledger if e.get('kind')=='settle' and e.get('round',3)==3 and
               published_at<=e.get('ts',0)<published_at+900 and (e.get('data',{}).get('sku') or e.get('data',{}).get('item'))==sku]
        after={e['seq']:e for e in after}.values()
        own=[e for e in after if e.get('data',{}).get('shop')==NAME]
        before=[e for e in ledger if e.get('kind')=='settle' and e.get('round',3)==3 and
                published_at-900<=e.get('ts',0)<published_at and (e.get('data',{}).get('sku') or e.get('data',{}).get('item'))==sku]
        own_before=[e for e in {e['seq']:e for e in before}.values() if e.get('data',{}).get('shop')==NAME]
        after_count=len(list(after))
        feedback={'status':'published' if success else 'pending_or_failed','post_id':post_id,
          'likes':post.get('likes'),'dislikes':post.get('dislikes'),
          'before_15m_trades':len({e['seq'] for e in before}),'after_15m_trades':after_count,
          'before_own_revenue':sum(e['data'].get('amount',0) for e in own_before),
          'after_own_revenue':sum(e['data'].get('amount',0) for e in own),
          'visits':None,'shop_profit_before':r.get('shop_profit_baseline'),
          'shop_profit_now':((inventory.get('balance',0)-inventory.get('start',5000000)-inventory.get('injected',0)) if inventory else None),
          'limitation':'Visits unavailable; shop profit follows platform balance-start-injected; before/after association, not causation.',
          'mature':bool(success and now>=published_at+900),
          'recommendation_score':r['score']}
        if after_count:
            observed=median([e['data']['amount'] for e in after])
            feedback['observed_median_change']=observed/r['median']-1
            feedback['discount_gap_after']=1-r['price']/observed
        profit_change=((feedback['shop_profit_now']-feedback['shop_profit_before'])
                       if feedback['shop_profit_now'] is not None and feedback['shop_profit_before'] is not None else 0)
        feedback['reward']=(post.get('likes',0)-post.get('dislikes',0)+len(own)-len(own_before)
                            +max(-2,min(2,profit_change/100000)))
        c.execute('update publications set feedback=? where digest=?',(json.dumps(feedback),digest))


def choose_style(c):
    values=defaultdict(list)
    for style,feedback in c.execute('select style,feedback from publications where feedback is not null'):
        f=json.loads(feedback)
        if f.get('mature'):
            values[style].append(f['reward'])
    styles=['가격 메리트','거래량·수급 포착']
    unseen=next((s for s in styles if not values[s]),None)
    return unseen or max(styles,key=lambda s:sum(values[s])/len(values[s]))


def tick(md,enabled=False,refresh=True):
    md=Path(md)
    now=time.time()
    inv=read(md/'inventory.json',{})
    catalog=read(md/'catalog.json',{})
    ledger=lines(md/'ledger.jsonl')
    forum=read(md/'forum.json',[])
    c=database(md)
    measure_feedback(c,ledger,forum,lines(md/'outbox.sent.jsonl'),now,inv)
    groups=trades(ledger,now)
    last=c.execute("select value from state where key='last_scan'").fetchone()
    if not refresh and last and now-float(last[0])<INTERVAL:
        c.commit();c.close();return {'status':'scan_interval'}
    with urlopen('https://market.ourolabs.ai/api/shops',timeout=15) as response:
        shops=json.load(response)['shops']
    supply=Counter()
    for shop in shops:
        supply.update(shop.get('stock') or {})
    metrics={sku:features(events,supply[sku],forum,sku,now) for sku,events in groups.items() if sku in catalog}
    metrics={s:f for s,f in metrics.items() if f}
    ranked=sorted(metrics,key=lambda s:(-metrics[s]['count'],s))
    # Own stock is considered along with other shops; actual quotes determine eligibility.
    choices=[]
    own=next((s for s in shops if s['name']==NAME),None)
    if own:
        choices.extend([(own,s) for s in ranked if (own.get('stock') or {}).get(s,0)>0][:2])
    for sku in ranked:
        options=[s for s in shops if s['name']!=NAME and (s.get('stock') or {}).get(sku,0)>0]
        if options:
            # Historical prices select whom to ask, never substitute for a quote.
            def observed_price(shop):
                prices=[e['data']['amount'] for e in groups[sku]
                        if e['data'].get('shop')==shop['name'] and now-e['ts']<3600]
                return median(prices) if prices else math.inf
            choices.append((min(options,key=lambda s:(observed_price(s),-s['stock'][sku])),sku))
        if len(choices)>=6:
            break
    choices=choices[:6]
    quotes=asyncio.run(fetch_quotes(choices,catalog))
    with (md/'recommendation-quotes.jsonl').open('a',encoding='utf-8') as journal:
        for q in quotes:
            journal.write(json.dumps(q,ensure_ascii=False)+'\n')
    results=[]
    for q in quotes:
        r=score(metrics[q['sku']],q,time.time())
        if r:
            r['shop_profit_baseline']=inv.get('balance',0)-inv.get('start',5000000)-inv.get('injected',0)
            results.append(r)
    for sku,f in metrics.items():
        previous=c.execute('select data from observations where sku=? order by at desc limit 1',(sku,)).fetchone()
        if previous:
            old=json.loads(previous[0])
            f['supply_change']=f['stock']-old.get('stock',f['stock'])
            f['observed_demand_change']=f['count']-old.get('count',f['count'])
        c.execute('insert into observations values(?,?,?)',(now,sku,json.dumps(f)))
    c.execute("insert or replace into state values('last_scan',?)",(str(now),))
    styles=choose_style(c)
    topic_rewards=defaultdict(list)
    for topic,raw in c.execute('select sku,feedback from publications where feedback is not null'):
        feedback=json.loads(raw)
        if feedback.get('mature'):
            topic_rewards[topic].append(feedback['reward'])
    def priority(r):
        rewards=topic_rewards[r['sku']]
        learned=max(-3,min(3,sum(rewards)/len(rewards))) if rewards else 0
        return r['score']+(3 if r['own'] else 0)+learned
    chosen=None
    for r in sorted(results,key=lambda r:-priority(r)):
        previous=c.execute('select at,data from publications where sku=? order by at desc limit 1',(r['sku'],)).fetchone()
        if previous:
            old=json.loads(previous[1])
            meaningful=abs(r['price']/old['price']-1)>=.02 or r['count']>=old['count']*1.25 or abs(r['score']-old['score'])>=8
            if not meaningful:
                continue
        chosen=r;break
    preview={'at':now,'quotes_checked':len(quotes),'qualified':len(results),'recommendation':chosen,
             'feedback':[json.loads(row[0]) for row in c.execute('select feedback from publications where feedback is not null')]}
    (md/'recommendation-preview.json').write_text(json.dumps(preview,ensure_ascii=False,indent=2),encoding='utf-8')
    latest=c.execute('select max(at) from publications').fetchone()[0]
    if not chosen or not enabled or latest and now-latest<INTERVAL:
        c.commit();c.close();return {'status':'no_new_opportunity' if not chosen else 'dry_run_or_interval',**{k:preview[k] for k in ('quotes_checked','qualified')}}
    pending=lines(md/'outbox.jsonl')
    if any(p.get('as')=='buyer' and 'post' in p for p in pending):
        c.commit();c.close();return {'status':'pending_outbox'}
    post=render(chosen,catalog,inv,styles)
    digest=hashlib.sha256(post['post'].encode()).hexdigest()
    if c.execute('select 1 from publications where digest=?',(digest,)).fetchone():
        c.commit();c.close();return {'status':'duplicate'}
    # Worker holds an OS lock; journal/pending queue survive process restarts.
    c.execute('insert into publications values(?,?,?,?,?,?,null)',(digest,now,chosen['sku'],styles,post['post'],json.dumps(chosen)))
    c.commit()
    with (md/'outbox.jsonl').open('a',encoding='utf-8') as out:
        out.write(json.dumps(post,ensure_ascii=False)+'\n')
    c.close()
    return {'status':'queued','sku':chosen['sku'],'score':chosen['score'],'digest':digest}


def ensure_worker(md):
    md=Path(md)
    heartbeat=md/'recommendation-heartbeat.json'
    if time.time()-read(heartbeat,{}).get('at',0)<180:
        return
    root=Path(__file__).resolve().parent
    log=(root/'logs/recommendation-worker.log').open('a',encoding='utf-8')
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    subprocess.Popen([sys.executable,'-X','utf8','-u',str(root/'run_market.py'),'--recommendations-only'],
        cwd=root,stdout=log,stderr=log,creationflags=flags)
    log.close()
