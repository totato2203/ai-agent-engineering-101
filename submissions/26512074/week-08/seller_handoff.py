"""Restore a fresh local SDK task snapshot during a controlled seller update."""
import asyncio
import time
from a2a.types import Task
from a2a.server.context import ServerCallContext
from google.protobuf.json_format import ParseDict
from optimizer import read

def restore(agent,store,md):
    snapshot=read(md/'seller-handoff.json',{})
    if not 0<=time.time()-snapshot.get('at',0)<300:return 0
    inventory=read(md/'inventory.json',{})
    units={u['unit']:u for u in inventory.get('units',[])}
    async def load():
        import re
        from optimizer import db
        count=0
        for raw in snapshot.get('tasks',[]):
            task=ParseDict(raw,Task())
            await store.save(task,ServerCallContext())
            status=raw.get('status',{});state=status.get('state','')
            if state in ('TASK_STATE_INPUT_REQUIRED','TASK_STATE_WORKING','TASK_STATE_SUBMITTED'):
                with db(md) as c:
                    row=c.execute('select * from trials where task=?',(task.id,)).fetchone()
                if row and row['unit'] in units:
                    text=' '.join(p.get('text','') for p in (status.get('message') or {}).get('parts',[]))
                    match=re.search(r'(?:asking|Counteroffer:)\s*(\d+)',text,re.I)
                    agent.open[task.id]={'unit':units[row['unit']],'ask':int(match[1]) if match else row['ask'],
                        'offer':row['last_offer'],'previous_offer':None,
                        'lines':['buyer: restored negotiation'],'seen_at':time.time(),
                        'warranty_hours':6 if 'Includes a 6-hour' in text else 0}
            # Signed receipt reservations survive until inventory confirms sale.
            for artifact in raw.get('artifacts',[]):
                for part in artifact.get('parts',[]):
                    unit=(part.get('data') or {}).get('unit')
                    if unit and unit in units:
                        agent.promised.add(unit);agent.promised_at[unit]=time.time()
            count+=1
        return count
    count=asyncio.run(load())
    (md/'seller-handoff.json').replace(md/'seller-handoff-restored.json')
    return count
