"""Model-planned pricing, fast A2A execution, signed exact-price receipts."""
import argparse
import asyncio
import re

import uvicorn
from starlette.applications import Starlette
from a2a.helpers import get_message_text, new_data_part, new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

from policy import RESERVES, event, load_policy, read_price
from signing import sign_receipt


class Seller(AgentExecutor):
    def __init__(self, name):
        self.name, self.tasks, self.locks = name, {}, {}

    async def execute(self, context, event_queue):
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        async with self.locks.setdefault(task.id, asyncio.Lock()):
            up = TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id)
            say = lambda message, **meta: up.new_agent_message(parts=[new_text_part(message)], metadata=meta)
            text = get_message_text(context.message) or ""
            state = self.tasks.get(task.id)
            if state is None:
                item = next((i for i in RESERVES if re.search(r"\b" + i + r"\b", text, re.I)), None)
                if item is None:
                    await up.reject(say("Specify lamp, chair or bookshelf; no unverified physical quality claims."))
                    return
                policy = load_policy()["items"][item]
                state = {"item": item, "policy": policy, "round": 0,
                         "ask": RESERVES[item] + policy["opening_markup"], "terminal": False}
                self.tasks[task.id] = state
                event("seller_open", task=task.id, item=item, ask=state["ask"], policy=policy)
            else:
                if state["terminal"]:
                    raise ValueError("task is terminal")
                item, plan = state["item"], state["policy"]
                offer = await read_price(text, role="offer", ask=state["ask"])
                if offer is not None:
                    state["round"] += 1
                    threshold = RESERVES[item] + (0 if state["round"] >= plan["floor_after"] else plan["minimum_markup"])
                    if offer >= threshold:
                        rec = sign_receipt({"shop": self.name, "item": item, "price": offer, "task": task.id})
                        state["terminal"] = True
                        await up.add_artifact(parts=[new_data_part(rec)], name="receipt")
                        await up.complete(say(f"Agreed {offer}. Signed receipt issued; only ACP settlement counts as payment."))
                        event("seller_agreed", task=task.id, item=item, price=offer, reserve=RESERVES[item])
                        return
                    if state["round"] >= plan["max_rounds"]:
                        state["terminal"] = True
                        await up.reject(say("No affordable agreement. No payment or purchase claimed."))
                        event("seller_rejected", task=task.id, item=item)
                        return
                    state["ask"] = max(threshold, state["ask"] - plan["concession_step"])
            await up.requires_input(say(
                f"{state['item']}: exact price, no additional fees. Asking {state['ask']}",
                ask=state["ask"], item_id=state["item"]))

    async def cancel(self, context, event_queue):
        task = context.current_task
        async with self.locks.setdefault(task.id, asyncio.Lock()):
            self.tasks.setdefault(task.id, {})["terminal"] = True
            await TaskUpdater(event_queue=event_queue, task_id=task.id, context_id=task.context_id).cancel()


def build(port, name="totato2203"):
    load_policy()  # No model-generated plan means no silently invented policy.
    card = AgentCard(name=name,
        description="Fast exact-price furniture checkout. Signed receipts, same-item ACP totals, "
                    "bounded negotiation and no extra fees. Fictional course goods; no claimed platform endorsement.",
        version="3.0.0", default_input_modes=["text/plain"],
        default_output_modes=["text/plain", "application/json"], capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[AgentInterface(protocol_binding="JSONRPC", protocol_version="1.0", url=f"http://127.0.0.1:{port}/")],
        skills=[AgentSkill(id="signed-fast-deal", name="Signed exact-price lamp, chair, bookshelf",
            description="Name an item, then offer a whole-number price. Ask is in metadata and the last number. "
                        "Signed receipt matches agreement; the kit supports ACP/AP2 checkout.", tags=["shopping", "acp", "ap2"])])
    handler = DefaultRequestHandler(agent_executor=Seller(name), task_store=InMemoryTaskStore(), agent_card=card)
    return Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, "/"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(build(args.port), host="127.0.0.1", port=args.port, log_level="warning")
