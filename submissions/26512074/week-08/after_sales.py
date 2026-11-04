"""Perishable clearance and optional market-enforced warranty support."""
import json,math
from pathlib import Path
from round3 import read,write,lines
from shop_profit import DISPLAY,ownership_tags,recovery_price


def warranty_request(text):
    return any(w in text.lower() for w in ('warranty','보증','a/s','as 서비스','사후지원'))


def warranty_offer(md,unit,price,cash,now):
    if unit.get('kind')!='goods':
        return False
    path=Path(md)/'warranty-holds.json'
    holds={k:v for k,v in read(path,{}).items() if v['expires_at']>now}
    outstanding=sum(h['price'] for k,h in holds.items() if k!=unit['unit'])
    capacity=max(0,min(cash*.25,cash-750000))
    if outstanding+price>capacity:
        return False
    holds[unit['unit']]={'price':price,'expires_at':now+6*3600+900,'issued':False}
    write(path,holds)
    return True


def release_warranty(md,unit,issued=False,price=None,now=None):
    path=Path(md)/'warranty-holds.json'
    holds=read(path,{})
    if unit not in holds:
        return
    if issued:
        holds[unit]['issued']=True
        if price is not None:
            holds[unit]['price']=price
    elif not holds[unit].get('issued'):
        del holds[unit]
    write(path,holds)


def clearance(inventory,ledger,now):
    tags=ownership_tags()
    sold={}
    seen=set()
    for e in ledger:
        if e.get('kind')!='settle' or e.get('seq') in seen or e.get('data',{}).get('shop') not in tags:
            continue
        seen.add(e['seq'])
        if 0<=now-e.get('ts',0)<3600:
            sku=e['data'].get('sku') or e['data'].get('item')
            sold[sku]=sold.get(sku,0)+1
    groups={}
    for u in inventory.get('units',[]):
        if u.get('kind')=='food' and 0<(u.get('expires_at') or 0)-now<=6*3600 and u.get('grade')!='expired':
            groups.setdefault(u['sku'],[]).append(u)
    offers=[]
    for sku,units in groups.items():
        hours=min(u['expires_at']-now for u in units)/3600
        if len(units)<=sold.get(sku,0)*hours:
            continue
        u=min(units,key=lambda u:u['expires_at'])
        p=recovery_price(u,inventory,ledger,now)
        offers.append({'sku':sku,'name':u['name'],'units':len(units),'hours':round(hours,1),
                       'ask':p['ask'],'lot':u['unit']})
    return sorted(offers,key=lambda o:o['hours'])[:3]


def service(md,inventory,ledger,now,enabled=False):
    md=Path(md)
    state=read(md/'aftercare-clearance-state.json',{'events':[]})
    tags=ownership_tags()
    pending=lines(md/'outbox.jsonl')
    sent=lines(md/'outbox.sent.jsonl')
    awaiting=state.get('pending')
    if awaiting:
        ack=next((s for s in reversed(sent) if s.get('sent',{}).get('post')==awaiting['post']),None)
        if ack is None:
            return {'status':'awaiting_post_acknowledgement'}
        if ack.get('status')==200 and awaiting.get('event') is not None:
            state['events'].append(awaiting['event'])
        elif ack.get('status')!=200:
            state.pop('clearance_signature',None)
        state.pop('pending',None)
        write(md/'aftercare-clearance-state.json',state)
    last=state.get('last_post',0)
    if now-last<300 or any(p.get('as')=='shop' and 'post' in p for p in pending):
        return {'status':'shop_post_interval'}
    action=None
    event_seq=None
    for e in reversed(ledger):
        d=e.get('data',{})
        if e.get('kind')!='broken' or d.get('shop') not in tags or d.get('refunded',0)<=0 or e.get('seq') in state['events']:
            continue
        if not 0<=now-e.get('ts',0)<86400:
            continue
        action={'as':'shop','refs':[e['seq']], 'post':
            f"[보증 A/S 안내 | {DISPLAY}] {d.get('buyer','구매자')}님, "
            f"{d.get('item','구매 상품')} 고장에 대해 시장 원장에서 {d['refunded']:,.0f} credits 보증 환불을 확인했습니다. "
            '처리가 도움이 되셨다면 제 분석글에 좋아요를 눌러주시거나 실제 경험에 대한 솔직한 후기 게시글을 남겨주세요. '
            '후기나 좋아요는 보증 지원의 조건이 아닙니다.'}
        event_seq=e['seq']
        break
    if action is None:
        offers=clearance(inventory,ledger,now)
        signature='|'.join(o['lot']+':'+str(o['units']) for o in offers)
        if not offers or signature==state.get('clearance_signature') and now-state.get('last_clearance',0)<1800:
            return {'status':'no_clearance_or_completed_support'}
        text=[f'[마감 떨이 특가 | {DISPLAY}] 유통기한 임박 식품 한정']
        text.extend(f"{o['sku']} {o['name'][:30]} {o['units']}개 · 남은 시간 약 {o['hours']:g}시간 · 제안가 {o['ask']:,.0f} credits" for o in offers)
        text.append('희망 구매가를 제안해 주세요. 남은 사용시간을 먼저 확인하며, 과도하게 낮은 제안을 제외하고 협의합니다. 인증서와 최종 유통기한은 결제 시 확인하세요.')
        action={'as':'shop','post':'\n'.join(text),'refs':[]}
        state['clearance_signature']=signature
        state['last_clearance']=now
    write(md/'aftercare-clearance-preview.json',action)
    if not enabled:
        return {'status':'dry_run'}
    with (md/'outbox.jsonl').open('a',encoding='utf-8') as out:
        out.write(json.dumps(action,ensure_ascii=False)+'\n')
    state['last_post']=now
    state['pending']={'post':action['post'],'event':event_seq}
    write(md/'aftercare-clearance-state.json',state)
    return {'status':'queued','kind':'support' if action['refs'] else 'clearance'}
