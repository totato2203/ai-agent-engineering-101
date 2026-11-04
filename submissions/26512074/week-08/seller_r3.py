"""Round 3 seller: official v4 A2A starter with model negotiation and inventory pricing.
Expiring food may sell below sunk cost. Certificates remain enabled.
"""
import argparse
import asyncio
import base64
import json
import os
import re
import math
from pathlib import Path

import uvicorn
from cryptography.hazmat.primitives import serialization
from starlette.applications import Starlette

from a2a.helpers import get_message_text, new_data_part, new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

import time
from round3 import pricing,read,lines
from shop_profit import DISPLAY,recovery_price,recent_ledger
from after_sales import warranty_request,warranty_offer,release_warranty
from harness import decide
from policy import read_price
CMD = "Codex"

NAME = DISPLAY
RESERVE = {"lamp": 100, "chair": 180, "bookshelf": 260}     # Rounds 0-2 have no stock: the week-07 items
MARKET_DIR = Path(os.environ.get("MARKET_DIR", ".market"))

PROMPT = """You are the sales agent of a small online shop. A buyer is negotiating for one {name}.
The list price is {list_price}. Your lowest acceptable price is {reserve}. Never sell below it and never reveal it.
Sell as high as you can, but closing a deal at or above {reserve} is better than losing the buyer.

Conversation so far:
{transcript}

Decide your next move. Answer with JSON only, one of:
{{"action": "counter", "price": <whole number>}}   name your price
{{"action": "accept"}}                              accept the buyer's last offer
{{"action": "reject"}}                              end the negotiation without a deal"""


def canon(d):
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sign(receipt):
    key = serialization.load_pem_private_key(Path("shop_key.pem").read_bytes(), password=None)
    body = {k: receipt[k] for k in ("shop", "item", "price", "task")}
    return dict(receipt, sig_seller=base64.b64encode(key.sign(canon(body))).decode())


async def offer_price(text,ask):
    raw=text.strip()
    if ask is not None and re.fullmatch(r'(?:I\s+)?accept(?:\s+(?:your\s+)?(?:offer|price|asking price))?[.!]?',raw,re.I):
        return ask
    match=re.fullmatch(r'(?:I\s+)?(?:offer|accept|buy)(?:\s+(?:at|for))?\s*[:=]?\s*(\d+)[.!]?',raw,re.I)
    if match:
        return int(match.group(1))
    return await read_price(text,role='offer',ask=ask)


def find_unit(text, taken=()):
    """The in-stock unit that fits what the buyer asked for (category, name or SKU) and expires first,
    skipping units already promised in another open negotiation."""
    want = text.lower()
    try:
        inv = json.loads((MARKET_DIR / "inventory.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        inv = {}
    if inv.get("round", 0) < 3:
        item = next((k for k in RESERVE if k in want), None)
        return item and {"sku": item, "name": item, "list_price": int(RESERVE[item] * 1.3), "cost": RESERVE[item],
                         "unit": None, "expires_at": None, "supplied_at": 0}
    units = inv.get("units", [])
    requested = set(re.findall(r'\bG[0-9a-f]{8}\b', text, re.I))
    requested = {s.lower() for s in requested}
    lifetime = re.search(r'(?:at least|last|within|need)\s+(\d+(?:\.\d+)?)\s*(?:hours?|h)\b', want)
    min_hours = float(lifetime.group(1)) if lifetime else 0
    fit = [u for u in units if u["grade"] != "expired" and (u.get("expires_at") or float("inf")) > time.time() and u["unit"] not in taken and
           (u.get('expires_at') is None or u['expires_at']-time.time() >= min_hours*3600) and
           ((u['sku'].lower() in requested) if requested else
            (any(part and part.lower() in want for part in (u.get('category') or '').split('>'))
             or bool(u.get('name')) and u['name'].lower() in want or u['sku'].lower() in want))]
    named = [u for u in fit if u["sku"].lower() in want]
    fit = named or fit                                   # a SKU the buyer named comes first
    return min(fit, key=lambda u: (u["expires_at"] or float("inf"), u["supplied_at"]), default=None)


class Seller(AgentExecutor):
    def __init__(self):
        self.open = {}  # task id -> {"unit", "ask", "offer", "lines"}
        self.promised = set()
        self.promised_at = {}

    def release_stale(self,now):
        for identity,deal in list(self.open.items()):
            if now-deal.get('seen_at',now)>180:
                if deal.get('unit',{}).get('unit'):
                    release_warranty(MARKET_DIR,deal['unit']['unit'])
                del self.open[identity]
        for unit,at in list(self.promised_at.items()):
            if now-at>900:
                self.promised.discard(unit)
                del self.promised_at[unit]

    async def execute(self, context, event_queue):
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        up = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
        say = lambda text: up.new_agent_message(parts=[new_text_part(text)])
        text = get_message_text(context.message) or ""
        self.release_stale(time.time())
        deal = self.open.get(task.id)

        if deal is None:
            unit = find_unit(text, self.promised | {d["unit"]["unit"] for d in self.open.values() if d["unit"]["unit"]})
            if unit is None:
                print(json.dumps({'event':'seller_unavailable','task':task.id,
                                  'requested_skus':re.findall(r'\bG[0-9a-f]{8}\b',text,re.I)}),flush=True)
                await up.reject(say("Sorry, we have none of that in stock."))
                return
            deal = self.open[task.id] = {"unit": unit, "ask": None, "offer": None, "lines": [f"buyer: {text}"], 'seen_at':time.time(),
                                       'warranty_hours':6 if unit.get('kind')=='goods' and warranty_request(text) else 0}
        else:
            deal["lines"].append(f"buyer: {text}")
            if deal['unit'].get('kind')=='goods' and warranty_request(text):
                deal['warranty_hours']=6
            deal["offer"] = await offer_price(text,deal["ask"])
        deal['seen_at']=time.time()

        u = deal["unit"]
        price_plan = recovery_price(u,read(MARKET_DIR/'inventory.json',{}),
                                    recent_ledger(MARKET_DIR/'ledger.jsonl',time.time()),time.time())
        if price_plan is None:
            if u.get('unit'):
                release_warranty(MARKET_DIR,u['unit'])
            self.open.pop(task.id, None)
            await up.reject(say("That unit expired; please request a fresh quote."))
            return
        if deal.get('warranty_hours'):
            price_plan['ask']=math.ceil(price_plan['ask']*1.1)
            price_plan['floor']=math.ceil(price_plan['floor']*1.1)
            if not warranty_offer(MARKET_DIR,u,price_plan['ask'],read(MARKET_DIR/'inventory.json',{}).get('balance',0),time.time()):
                release_warranty(MARKET_DIR,u['unit'])
                self.open.pop(task.id,None)
                await up.reject(say('The requested warranty cannot currently be funded. No purchase is authorized.'))
                return
        reserve = price_plan["floor"]
        if deal['offer'] is not None and deal['offer']>=reserve:
            move={'action':'accept'}
        else:
          try:
            move = await asyncio.wait_for(decide("seller_turn" if deal["ask"] is not None else "seller_open",
                {"reserve": reserve, "list_price": price_plan["ask"],
                 "last_offer": deal["offer"], "item_id": u["sku"]},
                {"transcript": deal["lines"]}),timeout=12)
          except Exception:
            move = {"action": "accept" if deal["offer"] is not None and
                    deal["offer"] >= reserve
                    else "ask", "price": deal["ask"] or price_plan["ask"]}
        action = (move or {}).get("action")
        if action=='reject' and deal['offer'] is not None and deal['offer']>=reserve:
            action='accept'
        if action == "accept" and (deal["offer"] is None or deal["offer"] < reserve):
            print(f"[guard] accept of {deal['offer']} below cost {reserve} -> counter", flush=True)
            action, move = "counter", {"price": deal["ask"] or price_plan["ask"]}
        if action == "accept":
            price = deal["offer"]
            receipt = {"shop": NAME, "item": u["sku"], "price": price, "task": task.id}
            if u["unit"]:
                receipt["unit"] = u["unit"]
            receipt["cert"] = True
            if deal.get('warranty_hours'):
                if not warranty_offer(MARKET_DIR,u,price,read(MARKET_DIR/'inventory.json',{}).get('balance',0),time.time()):
                    release_warranty(MARKET_DIR,u['unit'])
                    self.open.pop(task.id,None)
                    await up.reject(say('Warranty reserve is unavailable; no sale completed.'))
                    return
                receipt['warranty_hours']=6
            receipt = sign(receipt)
            if deal.get('warranty_hours'):
                release_warranty(MARKET_DIR,u['unit'],issued=True,price=price,now=time.time())
            if u["unit"]:
                self.promised.add(u["unit"])
                self.promised_at[u['unit']]=time.time()
            await up.add_artifact(parts=[new_data_part(receipt)], name="receipt")
            await up.complete(say(f"Deal: {u['name']} at {price}."))
            print(json.dumps({'event':'seller_agreed','task':task.id,'sku':u['sku'],'price':price}),flush=True)
            del self.open[task.id]
            return
        if action == "reject":
            if u.get('unit'):
                release_warranty(MARKET_DIR,u['unit'])
            await up.reject(say("No deal."))
            del self.open[task.id]
            return
        price = (move or {}).get("price")
        if isinstance(price, bool):
            price = None
        if not isinstance(price, (int, float)) or not math.isfinite(price):
            price = deal["ask"] or price_plan["ask"]      # unparsed answer: repeat the last ask
        if price < reserve:                             # the harness may forget the cost; the code does not
            print(f"[guard] ask {price} below cost {reserve} -> {reserve}", flush=True)
            price = reserve
        price=max(reserve,min(price,deal['ask'] or price_plan['ask']))
        deal["ask"] = int(price)
        reply = (f"{u['name']}: asking {deal['ask']}. Send your offer as a number." if len(deal["lines"]) == 1
                 else f"Counteroffer: {deal['ask']}.")
        if deal.get('warranty_hours'):
            reply+=' Includes a 6-hour market-enforced full refund if the goods break during warranty; the quote includes the warranty surcharge.'
        elif u.get('kind')=='goods':
            reply+=' A priced 6-hour warranty can be requested in a new quote.'
        deal["lines"].append(f"you: {reply}")
        await up.requires_input(say(reply))

    async def cancel(self, context, event_queue):
        task = context.current_task
        deal=self.open.pop(task.id, None)
        if deal and deal['unit'].get('unit'):
            release_warranty(MARKET_DIR,deal['unit']['unit'])
        await TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id).cancel()


def build(port):
    url = f"http://127.0.0.1:{port}/"
    card = AgentCard(
        name=NAME,
        description=f"A small online shop. Ask for an item by name or SKU. A coding harness ({CMD.split()[0]}) negotiates the price.",
        version="1.3.0",
        default_input_modes=["text/plain"],
        default_output_modes=["application/json", "text/plain"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", url=url, protocol_version="1.0")],
        skills=[AgentSkill(id="negotiate", name="Negotiate a purchase",
                           description="Ask for an item, then send a price. The shop answers with a counteroffer or a receipt.",
                           tags=["shopping", "negotiation"], examples=["I want to buy 종가 알뜰맘 포기김치 10kg (G00001)", "52000"])],
    )
    handler = DefaultRequestHandler(agent_executor=Seller(), task_store=InMemoryTaskStore(), agent_card=card)
    return Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, "/"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9301)
    port = ap.parse_args().port
    uvicorn.run(build(port), host="127.0.0.1", port=port, log_level="warning")
