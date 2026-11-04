"""Rotate verifiable shop advertisements at the market's five-minute limit."""
from collections import Counter
import json
from pathlib import Path
from shop_profit import DISPLAY

INTERVAL = 300
SHOP = 'totato2203-r3'
MARKER = f'[가게 소식 | {DISPLAY}]'


def promotion(inventory, ledger, now, edition=0):
    units = [u for u in inventory.get('units', []) if u.get('grade') != 'expired'
             and (u.get('expires_at') is None or u['expires_at'] > now)]
    if not units:
        return None
    counts = Counter(u['sku'] for u in units)
    products = {u['sku']: u for u in units}
    stock = '; '.join(f"{sku} {products[sku]['name'][:45]} {qty}개"
                      for sku, qty in sorted(counts.items(), key=lambda p: (-p[1], p[0]))[:4])
    seen, sales = set(), []
    for event in ledger:
        seq, data = event.get('seq'), event.get('data', {})
        if event.get('kind') != 'settle' or event.get('round', 3) != 3:
            continue
        if seq is None or seq in seen or data.get('shop') != SHOP:
            continue
        seen.add(seq)
        if 0 <= now - event.get('ts', 0) < 86400:
            sales.append(event)
    mode = edition % 3
    if mode == 0:
        heading = '현재 판매 재고 안내'
        message = 'SKU로 문의하면 재고를 확인하고 견적을 드립니다.'
    elif mode == 1:
        heading = '구매 전 확인할 수 있는 사항'
        message = ('저희는 시장 인증서를 제공하고, 먼저 만료되는 재고부터 배정합니다. '
                   '식품은 필요한 보관시간을 알려주세요. 실제 잔여 수명은 결제 시 확인해 주세요.')
    else:
        heading = '판매 현황과 감사 인사'
        message = (f'수집한 공개 원장에서 최근 24시간 저희 가게의 정산 {len(sales)}건을 확인했습니다. '
                   '환불 전 관측 집계이며 수집 누락이 있을 수 있습니다. 관심과 거래에 감사합니다.'
                   if sales else '현재 수집한 원장에서 최근 24시간 저희 가게의 정산은 확인되지 않았습니다. 재고를 확인하고 문의해 주세요.')
    return {'post': f'{MARKER} {heading}\n{stock}\n{message}\n재고는 작성 시점 기준이며 거래 중 변동될 수 있습니다.',
            'as': 'shop', 'refs': [e['seq'] for e in sales[-5:]] if mode == 2 else []}


def queue_promotion(md, inventory, ledger, now, enabled=False):
    from round3 import read, write, lines
    md = Path(md)
    state = read(md / 'promotion-state.json', {})
    post = promotion(inventory, ledger, now, state.get('edition', 0))
    if post is None:
        return False
    write(md / 'promotion-preview.json', {'at': now, 'post': post})
    if not enabled or now - state.get('last_queued', -INTERVAL) < INTERVAL:
        return False
    if any(p.get('as') == 'shop' and 'post' in p for p in lines(md / 'outbox.jsonl')):
        return False
    with (md / 'outbox.jsonl').open('a', encoding='utf-8') as out:
        out.write(json.dumps(post, ensure_ascii=False) + '\n')
    write(md / 'promotion-state.json', {'last_queued': now, 'edition': state.get('edition', 0) + 1})
    return True
