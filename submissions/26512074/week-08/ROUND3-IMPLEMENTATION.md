# Week 09 implementation on the week-09 branch

## Status

Offline planning implemented; kit-v4 integration is blocked. No registration,
publication, account creation, market transaction or changes to running agents.
The existing week-08 live commands still use the previous implementation.
`round3.py` does not replace those commands or claim v4 compatibility.

The two attached texts were read. The submission remains in week-08 as instructed
by the midterm announcement; week-09 is the Git branch, not the submission folder.
Public agent.md and week-08 lecture retrieval failed; the subsequent network
permission request was rejected. This checkout contains the week-07 kit and no
week-08/week-09 assignment directory or kit-v4 hook definitions. The field names
below are a local normalized interface, not a guessed official contract.

## Implemented strategies

- Settled public ledger units produce exponentially decayed daily demand and
  dispersion. Duplicate ledger identities and pending receipts are excluded.
- MRP net requirements subtract existing and incoming stock; safety stock uses
  dispersion, lead time and review interval. Shared cash reserve, shelf life,
  available supply and per-purchase 20-unit limits constrain procurement.
- Alternative grades/supply lots compete by expected ROI. This is a greedy
  allocation, not a claim of globally optimal portfolio allocation.
- Non-food prices account for expected holding cost and warranty refunds.
  Competitor offers influence opening prices; perishable salvage can go below
  historical cost. Expired food is never offered.
- Buyer proposals rank expected surplus using quality, failures, refund chances
  and settlement reliability. Orders enforce budget and remaining lifetime.
  These are proposals; existing signed receipts/checkout are not bypassed.
- Settlement rewards deduct supplied total costs, including refunds and storage.
  Per-opponent response posteriors retain evidence for later adaptation. They
  estimate observed responses, not the platform's actual hidden tastes.
- Inventory-based forum advertisement drafts have a posting interval. Nothing
  is posted. No invented repair, popularity or quality claims are generated.

## Requests not implemented

VPN accounts, coordinated false reviews/votes, fabricated injuries or failures,
and impersonating a selectively enforced regulator are not implemented.
Rating exchanges, retaliatory votes and discounts for ratings are not included.
Existing signed reciprocal-procurement functionality remains in competition.py;
new concealed agreements or outreach were not added.

Repair, refrigeration that alters official expiry, cash loans, transferring
buyer purchases into seller stock, identifying voters, and distress procurement
require actual supported market operations. They cannot be implemented honestly
by modifying local inventory or expiry files. No such mutation occurs.

The previous floor-price convergence is consistent with the old seller reducing
its threshold to the immutable reserve after bounded rounds, and the old buyer
anchoring bids to those reserves. That is a code-level explanation; causal
market-wide evidence has not been collected.

## Local interface and verification

Run from week-08:

```powershell
python -m unittest discover -s tests -p test_round3.py -v
python round3.py --snapshot snapshot.json --output plan.json
```

Snapshot: `now` (Unix seconds), `cash`, `catalog` (sku, kind food/goods,
list_price, optional competitor_prices/incoming_units), `inventory` (id, sku,
cost per unit, units, food expires_at), `supplies` (same fields). Optional
`ledger` rows use id, sku, status, at, units. Optional `order` has sku, budget,
value; `offers` has shop, sku, price and estimated quality/risk probabilities.
`outcomes` uses settled id, strategy, opponent, revenue, total_cost.
All credit/risk estimates must be supplied by a future verified adapter.
Zero observed demand deliberately yields no purchases; exploration needs explicit
future policy and budget rather than treating an advertisement as sales.

Eight planner tests passed with the installed Python 3.14 interpreter. The first
PowerShell run captured unittest stderr as NativeCommandError despite all tests
passing; its original output is retained in logs/round3-planner-tests.log.
The default python command resolves to an unusable WindowsApps alias.
architecture.tex documents the implemented offline pipeline; no LaTeX compiler
was found, so a compiled architecture.pdf is not claimed.

No actual Round-3 performance is claimed. Seller/buyer twenty-settlement minimums,
kit-v4 hook execution, architecture.pdf and final midterm reporting remain pending.
