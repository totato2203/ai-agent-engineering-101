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
from shop_profit import DISPLAY,ownership_tags

NAME='totato2203-r3'
MARKER=f'[매수 기회 포착 | {DISPLAY}]'
INTERVAL=300
MAX_RECOMMENDATIONS=3
MIN_RECOMMENDATIONS=1
MAX_QUOTES=24


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
    semaphore=asyncio.Semaphore(4)
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
    async def bounded(choice):
        try:
            return await asyncio.wait_for(one(*choice),timeout=25)
        except asyncio.TimeoutError:
            return None
    return [q for q in await asyncio.gather(*(bounded(choice) for choice in choices)) if q]


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
        f"우리 가게 {DISPLAY} ({NAME}) 판매 중: {stock_ad(inventory)}. SKU별 견적, 시장 인증서 제공, 별도 보증 미제공.\n"
        '도움이 됐다면 좋아요로 알려주세요. 반응은 상세 분석 주제 선정과 지속적인 분석 개선에 참고합니다. '
        '향후 상승이나 재판매 이익을 보장하지 않습니다.')
    return {'post':text,'as':'buyer','refs':r['refs']}


def select_slate(results,c,priority,limit=MAX_RECOMMENDATIONS):
    selected=[]
    seen=set()
    for r in sorted(results,key=lambda r:-priority(r)):
        if r['shop'] in seen:
            continue
        previous=next((row for row in c.execute('select data from publications where sku=? order by at desc',(r['sku'],))
                       if json.loads(row[0]).get('shop')==r['shop']),None)
        if previous and time.time()-c.execute('select max(at) from publications where sku=?',(r['sku'],)).fetchone()[0]<INTERVAL:
            old=json.loads(previous[0])
            meaningful=(abs(r['price']/old['price']-1)>=.02 or
                        r['count']>=old['count']*1.25 or abs(r['score']-old['score'])>=8)
            if not meaningful:
                continue
        selected.append(r)
        seen.add(r['shop'])
        if len(selected)==limit:
            break
    return selected


def purchase_exclusions(quotes,metrics,audits,shops,selected,now):
    positives={r['shop'] for r in selected}
    by_url={s['url']:s for s in shops}
    risks={}
    for url,audit in audits.items():
        shop=by_url.get(url)
        if not shop or shop['name'] in positives or audit.get('avoid_until',0)<=now:
            continue
        if not audit.get('reason','').startswith('receipt violation:'):
            continue
        risks[shop['name']]={'shop':shop['name'],'url':url,'reason':
            '자체 구매 검증에서 요청 상품·태스크 또는 합의 금액과 영수증이 일치하지 않은 기록. 재확인 전 구매 제외.',
            'evidence':audit['reason'],'priority':100,'refs':[]}
    for q in quotes:
        f=metrics.get(q['sku'])
        if not f or q['shop'] in positives or now-q['at']>300 or q['at']>now:
            continue
        premium=q['price']/f['median']-1
        if premium<.2:
            continue
        risk={'shop':q['shop'],'url':q['url'],'priority':premium*100,'refs':f['refs'][:2],
              'reason':f"{q['sku']} 확인 호가 {q['price']:,.0f}, 관측 중앙값 {f['median']:,.0f}보다 {premium*100:.1f}% 높음. 품질 조건을 비교할 때까지 이 견적 구매 보류."}
        if q['shop'] not in risks or risks[q['shop']]['priority']<risk['priority']:
            risks[q['shop']]=risk
    return sorted(risks.values(),key=lambda r:-r['priority'])[:3]


def render_slate(selected,catalog,inventory,style,exclusions=(),own_quotes=()):
    text=[f'{MARKER} {style}',f'지금 구매를 검토할 가게 {len(selected)}곳 — 실제 견적 기준']
    from datetime import datetime,timezone,timedelta
    text.append('관측 갱신: '+datetime.now(timezone(timedelta(hours=9))).strftime('%m-%d %H:%M KST'))
    refs=[]
    for i,r in enumerate(selected,1):
        trend=f"{r['medium_trend']*100:+.1f}%" if r['medium_trend'] is not None else '표본 부족'
        text.append(f"{i}. {r['sku']} {catalog[r['sku']]['name'][:24]}\n"
            f"1시간 중앙값 {r['median']:,.0f} → 확인 호가 {r['price']:,.0f} "
            f"({r['discount']*100:.1f}% 낮음), 거래 {r['count']}건(이전 {r['previous_count']}건), "
            f"가격 추세 {trend}, 공개 재고 {r['stock']}개, 점수 {r['score']:.1f}.\n"
            f"판매처 {r['shop']}{' [우리 가게 광고]' if r['own'] else ''}: {r['url']}")
        refs.extend(r['refs'][:2])
        comparisons=[q for q in own_quotes if q['sku']==r['sku'] and q['shop']==NAME and 0<=time.time()-q['at']<=300]
        if comparisons and not r['own']:
            ours=max(comparisons,key=lambda q:q['at'])
            if ours['price']<r['price']:
                text.append(f"동일 SKU의 우리 가게 실제 확인 호가 {ours['price']:,.0f} credits로 위 견적보다 {r['price']-ours['price']:,.0f} 낮습니다. 등급·유통기한 등 조건을 함께 비교하세요.")
    text.append(f'지금 구매 제외·주의 가게 {len(exclusions)}곳 — 아래 관측 조건에 한함')
    if len(exclusions)<3:
        text.append('주의 목록은 확인된 근거가 있는 곳만 표시합니다. 나머지는 추가 확인 중입니다.')
    for i,r in enumerate(exclusions,1):
        text.append(f"{i}. {r['shop']}: {r['reason']} {r['url']}")
        refs.extend(r['refs'])
    text.append('문의 당시 관측입니다. 같은 SKU도 등급·보증·잔여 수명에 따라 가격이 다를 수 있습니다. 최종 조건을 확인하세요.')
    text.append('도움이 됐다면 좋아요로 알려주세요. 반응을 다음 상세 분석 주제 선정에 참고합니다.')
    text.append(f'광고 | {DISPLAY}: 시장 인증서 제공, SKU로 견적 문의하세요.')
    return {'post':'\n'.join(text),'as':'buyer','refs':list(dict.fromkeys(refs))[:10]}


def measure_feedback(c,ledger,forum,sent,now,inventory=None):
    own_tags=ownership_tags()
    counts={body:n for body,n in c.execute('select body,count(*) from publications group by body')}
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
        own=[e for e in after if e.get('data',{}).get('shop') in own_tags]
        before=[e for e in ledger if e.get('kind')=='settle' and e.get('round',3)==3 and
                published_at-900<=e.get('ts',0)<published_at and (e.get('data',{}).get('sku') or e.get('data',{}).get('item'))==sku]
        own_before=[e for e in {e['seq']:e for e in before}.values() if e.get('data',{}).get('shop') in own_tags]
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
        # One post's reactions must not become a separate full reward for every
        # SKU it mentions. Cash movement outside its window is not post impact.
        previous=json.loads(old) if old else {}
        feedback['reaction_share']=1/counts[body]
        feedback['feedback_version']=2
        feedback['trade_reward']=len(own)-len(own_before)
        if previous.get('mature') and previous.get('feedback_version')==2:
            for field in ('before_15m_trades','after_15m_trades','before_own_revenue','after_own_revenue','trade_reward'):
                feedback[field]=previous[field]
        feedback['reward']=((post.get('likes',0)-post.get('dislikes',0))*feedback['reaction_share']
                            +feedback['trade_reward'])
        c.execute('update publications set feedback=? where digest=?',(json.dumps(feedback),digest))


def choose_style(c):
    values=defaultdict(list)
    posts=defaultdict(float)
    for style,body,feedback in c.execute('select style,body,feedback from publications where feedback is not null'):
        f=json.loads(feedback)
        if f.get('mature'):
            posts[(style,body)]+=f['reward']
    for (style,body),reward in posts.items():
        values[style].append(reward)
    styles=['가격 메리트','거래량·수급 포착']
    unseen=next((s for s in styles if not values[s]),None)
    return unseen or max(styles,key=lambda s:sum(values[s])/len(values[s]))


def tick(md,enabled=False,refresh=True):
    md=Path(md)
    now=time.time()
    from optimizer import config
    # Keep market recommendations on their original five-minute cadence;
    # the six-hour controller must not silently suppress this service.
    interval=INTERVAL
    inv=read(md/'inventory.json',{})
    catalog=read(md/'catalog.json',{})
    ledger=lines(md/'ledger.jsonl')
    forum=read(md/'forum.json',[])
    c=database(md)
    measure_feedback(c,ledger,forum,lines(md/'outbox.sent.jsonl'),now,inv)
    groups=trades(ledger,now)
    last=c.execute("select value from state where key='last_scan'").fetchone()
    if not refresh and last and now-float(last[0])<interval:
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
        from round3 import write
        identity=read(md/'shop-identity.json',{'urls':[]})
        identity['urls']=sorted(set(identity['urls'])|{own['url']})
        write(md/'shop-identity.json',identity)
        choices.extend([(own,s) for s in ranked if (own.get('stock') or {}).get(s,0)>0][:3])
    for sku in ranked:
        options=[s for s in shops if s['name']!=NAME and (s.get('stock') or {}).get(sku,0)>0]
        if options:
            # Historical prices select whom to ask, never substitute for a quote.
            def observed_price(shop):
                prices=[e['data']['amount'] for e in groups[sku]
                        if e['data'].get('shop')==shop['name'] and now-e['ts']<3600]
                return median(prices) if prices else math.inf
            choices.extend((s,sku) for s in sorted(options,key=lambda s:(observed_price(s),-s['stock'][sku]))[:2])
        if len(choices)>=MAX_QUOTES:
            break
    choices=choices[:MAX_QUOTES]
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
    selected=select_slate(results,c,priority)
    exclusions=purchase_exclusions(quotes,metrics,read(md/'buyer-observations.json',{}),shops,selected,time.time())
    chosen=selected[0] if selected else None
    preview={'at':now,'quotes_checked':len(quotes),'qualified':len(results),'recommendation':chosen,
             'recommendations':selected,
             'purchase_exclusions':exclusions,
             'feedback':[json.loads(row[0]) for row in c.execute('select feedback from publications where feedback is not null')]}
    (md/'recommendation-preview.json').write_text(json.dumps(preview,ensure_ascii=False,indent=2),encoding='utf-8')
    latest=c.execute('select max(at) from publications').fetchone()[0]
    if not selected or not enabled or latest and now-latest<interval:
        c.commit();c.close();return {'status':'no_evidence_backed_recommendation' if not selected else 'dry_run_or_interval',
                                   'recommendation_count':len(selected),**{k:preview[k] for k in ('quotes_checked','qualified')}}
    pending=lines(md/'outbox.jsonl')
    if any(p.get('as')=='buyer' and 'post' in p for p in pending):
        c.commit();c.close();return {'status':'pending_outbox'}
    post=render_slate(selected,catalog,inv,styles,exclusions,quotes)
    digest=hashlib.sha256(post['post'].encode()).hexdigest()
    if c.execute('select 1 from publications where body=?',(post['post'],)).fetchone():
        c.commit();c.close();return {'status':'duplicate'}
    # Worker holds an OS lock; journal/pending queue survive process restarts.
    for r in selected:
        c.execute('insert into publications values(?,?,?,?,?,?,null)',
                  (digest+':'+r['sku']+':'+r['shop'],now,r['sku'],styles,post['post'],json.dumps(r)))
    c.commit()
    with (md/'outbox.jsonl').open('a',encoding='utf-8') as out:
        out.write(json.dumps(post,ensure_ascii=False)+'\n')
    c.close()
    return {'status':'queued','skus':[r['sku'] for r in selected],
            'recommendation_count':len(selected),'digest':digest}


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
