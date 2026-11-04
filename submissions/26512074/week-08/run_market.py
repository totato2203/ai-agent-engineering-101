"""Round 3 persistent operator entry point and independent recommendation worker."""
import argparse
import json
import os
from pathlib import Path
import time
from launch_round3 import configure,main as market_main


def worker(once=False,dry_run=False):
    configure()
    from recommendations import tick
    from round3 import refresh_ledger,write,read
    from shop_profit import recent_ledger
    from after_sales import service
    md=Path('.market')
    md.mkdir(exist_ok=True)
    with (md/'recommendation-worker.lock').open('a+b') as lock:
        lock.seek(0)
        if os.name=='nt':
            import msvcrt
            if os.fstat(lock.fileno()).st_size == 0:
                lock.write(b'0');lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:
                print(json.dumps({'status':'worker_already_running'}),flush=True)
                return
        else:
            import fcntl
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                return
        while True:
            write(md/'recommendation-heartbeat.json',{'at':time.time(),'pid':os.getpid()})
            try:
                refresh_ledger(md)
                support=service(md,read(md/'inventory.json',{}),recent_ledger(md/'ledger.jsonl',time.time()),time.time(),enabled=not dry_run)
                print(json.dumps({'at':time.time(),'after_sales':support}),flush=True)
                result=tick(md,enabled=not dry_run,refresh=once)
                print(json.dumps({'at':time.time(),**result}),flush=True)
            except Exception as exc:
                print(json.dumps({'at':time.time(),'status':'error','error':str(exc)}),flush=True)
            if once:
                # One-shot validation must not inhibit the permanent worker.
                (md/'recommendation-heartbeat.json').unlink(missing_ok=True)
                return
            time.sleep(60)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--recommendations-only',action='store_true')
    p.add_argument('--once',action='store_true')
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--publish',action='store_true')
    args=p.parse_args()
    if args.recommendations_only:
        worker(args.once,args.dry_run)
    else:
        market_main()
