"""Contextual forum replies with acknowledged likes and persistent deduplication."""
import json
from pathlib import Path
from round3 import read,write,lines
from shop_promotion import queue_promotion
NAME='totato2203-r3'
INTERVAL=300


def relevant_stock(post,inventory,now):
    text=post.get('text','').lower()
    units=[u for u in inventory.get('units',[]) if u.get('grade')!='expired' and
           (u.get('expires_at') is None or u['expires_at']>now)]
    matched=[]
    for u in units:
        category=(u.get('category') or '').split('>')[-1].lower()
        if u['sku'].lower() in text or len(category)>=2 and category in text:
            if all(v['sku']!=u['sku'] for v in matched):
                matched.append(u)
    return matched[:2]


def kind(post):
    text=post.get('text','').lower()
    if any(w in text for w in ('불만','불편','고장','실망','비싸','재고가 없','못 샀','구할 수 없','broken','no stock','complaint')):
        return 'complaint'
    if any(w in text for w in ('분석','정보','시세','중앙값','거래량','인증서','유통기한','analysis','median')):
        return 'information'
    return None


def reply(post,products,classification):
    opening=('구매 과정에서 불편하셨겠어요. 조건을 다시 확인해 보시는 데 도움이 되길 바랍니다. '
             if classification=='complaint' else '관련 정보를 공유해 주셔서 감사합니다. ')
    ad='; '.join(f"{u['sku']} {u['name'][:32]}" for u in products)
    message=(opening+'이 글에 좋아요를 눌렀습니다. '
             +f"관련 상품을 찾으시면 저희 {NAME} 가게도 비교해 보세요: {ad}. "
             +'SKU로 견적을 문의하실 수 있고 시장 인증서를 제공합니다. '
             +'댓글이 도움이 되셨다면 제 글에도 좋아요로 알려주세요.')
    return {'post':message,'thread':post['id'],'as':'shop','refs':[]}


def service(md,inventory,forum,ledger,now,enabled=False):
    md=Path(md)
    state=read(md/'community-state.json',{'threads':{}})
    history=state.setdefault('threads',{})
    sent=lines(md/'outbox.sent.jsonl')
    pending=lines(md/'outbox.jsonl')
    # Reconcile server acknowledgements before claiming a vote or reply happened.
    for s in sent:
        action=s.get('sent',{})
        if action.get('as')!='shop':
            continue
        thread=str(action.get('vote',action.get('thread','')))
        if thread not in history:
            continue
        item=history[thread]
        if 'vote' in action:
            item['liked']=s.get('status')==200 and action.get('value')==1
            item['vote_status']=s.get('status')
        elif 'post' in action:
            item['replied']=s.get('status')==200
            item['reply_status']=s.get('status')
    own_times=[p.get('ts',0) for p in forum if p.get('author')==NAME and p.get('role')=='shop']
    last=max([state.get('last_post',0),read(md/'promotion-state.json',{}).get('last_queued',0)]+own_times)
    can_post=now-last>=INTERVAL and not any(p.get('as')=='shop' and 'post' in p for p in pending)
    for post in sorted(forum,key=lambda p:(not history.get(str(p.get('id')),{}).get('liked',False),-p.get('ts',0))):
        if post.get('author')==NAME or post.get('owner')=='totato2203' or post.get('thread') is not None:
            continue
        if not 0<=now-post.get('ts',0)<86400 or not kind(post):
            continue
        products=relevant_stock(post,inventory,now)
        if not products:
            continue
        key=str(post['id'])
        item=history.setdefault(key,{})
        if item.get('replied'):
            continue
        if not item.get('liked'):
            has_pending=any(p.get('vote')==post['id'] and p.get('as')=='shop' for p in pending)
            if not has_pending and now-item.get('vote_queued',-INTERVAL)>=INTERVAL and enabled:
                with (md/'outbox.jsonl').open('a',encoding='utf-8') as out:
                    out.write(json.dumps({'vote':post['id'],'value':1,'as':'shop'})+'\n')
                item['vote_queued']=now
                write(md/'community-state.json',state)
                return {'status':'like_queued','thread':post['id']}
            continue
        if can_post:
            action=reply(post,products,kind(post))
            write(md/'community-preview.json',action)
            if enabled:
                with (md/'outbox.jsonl').open('a',encoding='utf-8') as out:
                    out.write(json.dumps(action,ensure_ascii=False)+'\n')
                state['last_post']=now
                item['reply_queued']=now
                write(md/'community-state.json',state)
                return {'status':'reply_queued','thread':post['id']}
    write(md/'community-state.json',state)
    if can_post:
        queue_promotion(md,inventory,ledger,now,enabled=enabled,managed=True)
    return {'status':'waiting_for_relevant_post_vote_or_rate_limit'}
