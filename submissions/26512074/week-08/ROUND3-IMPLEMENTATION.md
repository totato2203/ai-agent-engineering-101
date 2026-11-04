# Week 09 재구현 — kit v4 계약 기준

브랜치: `week-09`. 공지의 제출 경로를 따라 코드는 `week-08`에 둔다.
이전 `round3.py`, 테스트, 아키텍처와 이전 플래너 테스트 로그를 교체했다.
기존 week-08 A2A 클라이언트, 모델 harness, 서명 유틸리티와 공식 v4 소스는 재사용했다.
시장 등록, 거래, 게시, 계정 생성은 실행하지 않았다.

## 적용한 전략

- `round3.py`: 실제 `settle` ledger만 중복 제거해 7일 감쇠 수요·분산을 계산한다.
  미래 실행 시 공개 ledger를 페이지 단위로 읽고 cursor와 원본을 보존한다.
- 공급창이 열렸을 때만 MRP 순소요량과 안전재고를 계산한다. 20분 보충 주기,
  기존 재고, 식품 수명, 75만원 현금유보, 무작위 등급의 최대 원가 75%를 반영한다.
  한 번에 최대 10개 SKU, SKU당 20개. 데이터가 없으면 전체 재고 3개까지 탐색한다.
  공급창 지연, 판매 기회 손실, 시장 수요의 자기 가게 점유율은 아직 보정하지 않는다.
- `seller_r3.py`: 공식 starter의 재고·A2A·Ed25519 영수증을 사용한다.
  먼저 만료되는 재고를 배정하고 이미 약속한 unit은 중복 판매하지 않는다.
  모델이 가격을 협상하되 원가·보관비 기반 하한을 코드로 집행한다.
  6시간 미만 남은 식품은 원가 미만 회수 판매를 허용하고 만료 재고는 거절한다.
  모델 오류 시 현재 호가를 유지한다. 인증서를 제공하며 품질 등급은 추측해 주장하지 않는다.
- `buyer_r3.py`: 주문의 acceptable SKU 중 실제 재고가 있는 가게만 고른다.
  과거 결제 성공률로 우선순위를 정하고 예산과 정가 85% 중 작은 금액을 상한으로 협상한다.
  정가 기반 가치는 플랫폼 규칙이며 85%는 조정 가능한 보수적 정책값이다.
  인증서와 사용시간+3분의 잔여 수명을 checkout accept 조건으로 요구한다.
  서명 검증과 ACP/AP2 결제는 키트가 수행한다. 바인딩 가능성이 생기면 다른 가게에
  추가 주문하지 않아 불확실한 응답 이후 중복 구매를 피한다.
- `review`: 정산 결과를 근거로 등급 허위 주장만 감점한다.
- 게시글: 실제 재고 홍보·안부 문구를 30분 간격으로 `forum-drafts.json`에 작성한다.
  outbox에는 쓰지 않는다. 검토 후 게시 기능 연결은 별도 작업이다.

## 계약에서 확인된 제약과 남은 요청

공식 계약: `logs/round3-contract.txt`와 `vendor/market-kit/market_kit.py`.
공개 사이트 재조회는 실패했으므로 저장된 계약과 키트 소스를 기준으로 구현했다.
키트는 매입할 등급을 지정할 수 없고, 공급받는 순간 원가·등급이 정해진다.
또한 forum.json은 좋아요/나빠요 집계만 제공하며 투표자 신원은 제공하지 않는다.
따라서 투표자별 맞투표·할인은 현재 계약으로 연결하지 않았다.
수리, 냉장고로 서버 유통기한 연장, 현금 대출, 구매한 물품을 판매 재고로 이전하는
공식 API가 없어 해당 기능과 임박 재고 전매·구제금융 계약은 구현하지 않았다.

익명 다중계정으로 가짜 후기·피해사례·인기를 만들거나 경쟁자를 공격하는 기능,
규제기관 사칭, 은폐 담합은 구현하지 않았다. 실제 거래 자료 기반 가격 경쟁만 연결했다.
숨은 취향 추론, 전략별 손익 학습, 순위 기반 자동 전략 전환, 여러 가게의 비구속 견적
비교는 이번 재구현에 아직 없다. 기존 파일의 전략을 새 경로에서 사용한다고 주장하지 않는다.
보증 위험 가격 함수는 있지만 판매자는 아직 유상 보증을 제공하지 않는다.

기존 하한가 수렴은 옛 seller/buyer가 고정 RESERVES에 수렴하는 구조로 설명된다.
전체 시장의 원인이 입증된 것은 아니다. 새 buyer는 그 고정 세 품목 표를 사용하지 않는다.

## 검증과 실행

```powershell
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p test_round3.py -v
python -m unittest discover -s tests -p test_round3_contract.py -v
```

`agent.json`의 seller/market_buyer/restock/review는 새 파일에 연결했다.
이 설정을 실제 키트에 전달하면 시장 동작이 가능하므로 이번 작업에서는 키트를 시작하지 않았다.
직접 `round3.py --state`를 실행하면 공개 ledger를 조회하고 로컬 기억을 갱신한다.
오프라인 검증은 `procurement`/`restock_hook` 함수를 사용한다.
LaTeX 컴파일러가 없어 architecture.pdf는 생성하지 못했다. 실제 거래 각 20건,
공식 market test 및 실제 모델 협상·정산 검증은 시장 실행 단계에 남아 있다.

## 2026-11-03 periodic market analysis

`market_analysis.py` computes SKU-level counts, median, range and the change from
an earlier 24-hour window using public Round-3 `settle.data.amount` observations.
It deduplicates ledger sequences and discloses owned units. Small samples do not
produce trend claims. Source ledger references accompany every post; readers are
encouraged to compare the original ledger and other quotes.

The restock hook generates an analysis preview. With `ROUND3_FORUM_ENABLED=1`,
it appends at most one changed report per hour to the official outbox. A pending
analysis blocks another queued analysis, and the last digest survives restarts.
The live `launch_round3.py --publish` path enables this setting.
No hidden reweighting, inventory-biased statistics or dependency-inducing messages
are used. Five new analysis tests and eight Round-3 contract tests passed locally.

`AGENTS.md` was restored byte-for-byte from the user's original backup. The new
launcher loads official kit v4 directly; the previous launch.py used kit v3 and is
not the active publication entry point. `start-round3.ps1 -Publish` now starts the
v4 launcher hidden, with local dependency and tunnel paths configured.

## ?? ?? ?? (2026-11-03, Asia/Seoul)

- 21:25 ?? totato2203 ??? ?? ??? ??? 409 ??. ?? ?? ??.
- 21:27:11 ?? v4?? shop? buyer ?? totato2203-r3, round 3?? ?? ??.
- ??? ??? ??? ?? ???? ??? ???? ???? Git? ???? ???.
- ?? ??? ?? ?? ???? ?? ? ?? ?? ?? ??? ????.
- ? ?? ??? ??? ?? ???? ????? ??? ???? ???? ??
  ??? ?? ???? ???. ?? ?? ???? ???? ???.
- ?? ?? ?? ??? logs/market-kit.log? ?? ???? PID? ????.

Live validation: analysis post HTTP 200; 2 buyer ACP payments observed. Supply currently closed; 0 seller units. See logs/round3-deployment-status.json for a timestamped snapshot.

## Buyer retry correction

The initial buyer stopped after one stocked supplier even on rejection or an invalid
receipt. retry-v2 now tries up to six distinct suppliers and returns only one
receipt to the kit for payment. Rejected negotiations cannot themselves settle
without the kit mandate/ACP path. Certificate and food lifetime requirements
are stated in the opening request; receipt overcharges are rejected and recorded
in .market/buyer-observations.json. Four regression scenarios pass. The kit
reloads buyer_r3.py per order, so this change applies without restarting the shop.
See logs/no-deal-diagnosis.json for the pre-fix outcome counts.

## Larger restock allocation

Replaces the initial 20-minute horizon with 60 minutes; observed goods target at
least 8 units, food targets up to 4 subject to a threefold demand/shelf-life cap.
Cold-start exploration grows from 3 to 12 units, at most 2 per SKU.
Each run spends at most 1,500,000 while retaining 750,000 cash; official limits
remain 10 lines and 20 units per line. Existing stock reduces requirements.
The running kit reloads the restock command, so no operator restart is needed.
See logs/larger-restock-validation.json for a projection, not a purchase claim.
## Evidence-based shop promotion

Added shop_promotion.py to the active restock hook. It rotates current stock,
certificate/expiry checks and observed own-shop settlement totals as shop posts.
Minimum queue interval: 300 seconds, matching the kit's role-specific forum limit;
the sixty-second hook cadence may make the observed interval slightly longer.
The existing buyer-role market analysis remains hourly. Pending shop posts block
new shop promotions. Local state persists across restarts. Expired stock is omitted,
and settlement sequences are deduplicated with source references.

No fabricated injuries, failures, popularity, waiting lists, vote bargains,
retaliatory votes or targeted negative advertising were added. Voter identity is
not present in the documented forum snapshot, so no voter-specific discount or
supporter promotion is claimed. Three essential promotion tests passed.

The running kit reloads round3.py on each restock invocation, so the next call
loads the promotion module without restarting the deployed identity.

## Five-minute market reports

Market-wide ledger reports now use a 300-second queue interval instead of 3600.
The post labels its coverage explicitly: the five most frequently observed SKUs
across all shops in the collected 24-hour ledger window. Own holdings do not
influence selection or statistics. Unchanged prices no longer suppress future
scheduled reports indefinitely; the interval and pending outbox check still
prevent duplicate scheduling. Publication is subject to the kit sync cadence and
server role-based rate limits. The active restock hook imports this file anew
on each call; no operator restart or identity re-registration is necessary.

## Proactive purchase recommendations (Round 3)

Active files: recommendations.py, run_market.py, round3.py, launch_round3.py.
The existing v4 operator continues serving seller/buyer/procurement. Its periodic
restock hook bootstraps an independent run_market.py --recommendations-only
worker once the validated recommendations-ready.json flag exists. The worker
runs without orders, refreshes the public ledger, checks feedback every minute
and analyzes/quotes every five minutes. An OS byte-range lock prevents concurrent
workers from publishing; SQLite persists observations, topic/style rewards,
publication fingerprints and feedback. Restart recovery retains the history.

Sources: public /api/shops stock, catalog.json, forum.json, ledger settle events,
and real non-binding A2A quotes. Quote requests send no offer or payment mandate
and cancel their tasks. Historical prices select sellers to query; recommendation
prices come from actual quotes no older than five minutes, not list-price guesses.
15-minute and one-hour price windows, one-hour volume comparisons, explicit forum
purchase requests, available stock, price dispersion and sample reliability feed
the score. At least three trades and a 3% observed discount are required. No
prior-volume denominator is fabricated when the previous period has no trades.
The market's demand.json category list is not treated as observed demand.

Only qualified new opportunities or price/volume/score changes can publish.
A five-minute minimum interval and pending buyer outbox check apply. Our products
receive priority only after they meet the same price-evidence gates, with the
commercial interest disclosed. Every recommendation includes a brief real stock
advertisement, certificate/condition checks and a voluntary request for likes.
No price increase or resale profit is guaranteed and analysis access is not
conditioned on votes. The existing shop-role promotion remains separate.

Feedback reconciles outbox.sent.jsonl (including the assigned post id) and forum
votes. It records equal 15-minute before/after trade counts and own revenue,
subsequent median-price movements, quote discount gaps and the original score.
Platform shop profit is balance-start-injected; changes may include unrelated
inventory purchases and refunds. Visitor counts are unavailable and remain null.
Topic/style selection uses bounded observational profit/reputation/own-trade
rewards; association is not represented as causal promotion lift.

Essential validation: three recommendation tests and an actual quote-only dry run.
Initial rendering and Windows lock contention errors were fixed; see the attempt
record. First accepted recommendation: HTTP 200, forum post 597, G200e39a3,
quoted 16,500 versus observed one-hour median 27,713 (40.46% lower), score 41.47.
This confirms publication, not a measured sales lift. Existing buyer, seller,
receipt signing and stock management commands are retained.

## Four-to-five product recommendation slates

Each qualified post now contains four or five distinct SKUs, each with an actual
recent quote, observed median, trade count, trend, available stock and seller.
The quote search grows from six to at most 24 requests with four concurrent
quote-only tasks. Product scores, freshness and evidence thresholds are unchanged.
Duplicates of a SKU are collapsed to its highest-priority qualifying offer.
Fewer than four evidence-backed, meaningfully changed products suppress posting;
the system never fills the batch with unsupported recommendations.
One shared inventory ad and feedback request follow the numbered product list.
Each product has its own persistent feedback record linked to the shared post,
so per-SKU outcomes and restart history remain available. Five essential tests
passed, including unique five-item rendering and no post with only three valid
candidates. The independent recommendation worker was restarted with this version;
the existing seller/buyer/procurement operator was not restarted.

## Contextual comments and stockout replenishment

community.py runs in the existing singleton worker every minute. It selects
other owners' root information/complaint posts from the last day only when an
available, unexpired inventory SKU/category is relevant. It queues a real +1
shop vote, waits for the kit's HTTP-200 acknowledgement, then queues a threaded
thank-you or empathetic reply with related stock and a voluntary request for
feedback on our posts. No successful vote means no claim that a like was given.
A vote may be accepted but not counted under the market's five-settlement rule;
no counted-rating benefit is claimed. Completed threads survive restarts and
are not replied to again. Replies share the role's five-minute post limit with
shop promotions; ordinary promotions fill gaps when no relevant reply is ready.

Inventory check found 281 units across 17 SKUs, with approximately 1.34 million
cash. The available data does not establish that all lost sales are caused by
our stockouts. No blanket purchase increase is applied to already stocked goods.
Instead, observed-demand SKUs with zero held units get a 12-unit goods target or
6-unit food target (food remains shelf-life constrained), and empty SKUs take
priority over replenishing existing holdings. The 750,000 reserve and 1,500,000
per-run spending cap remain. Procurement reloads on its next call.

Validation: three comment/vote tests and five procurement/pricing tests passed.
The singleton worker was restarted to load the community integration; the main
Round 3 seller/buyer operator remains running. Actual delivery is recorded in
outbox.sent.jsonl; validation alone is not a claim of successful live comments.

## Seller no-deal repair (2026-11-04)

Public ledger entries 2338761 and 2338765 refer to the same order
(o-58935027d332), same buyer and same shop URL. Both have receipt=null and the
same generic review, so they are duplicate result records for one unsuccessful
negotiation, not two independently identified payment failures. The records do
not reveal the exact private negotiation reason.

Code inspection and a current seller harness trace revealed a concrete SKU
selection defect: a request naming Gce142806 was assigned G1fdeffa7 because the
starter fell back to another product in the same category. The revised seller
never substitutes a different SKU when an explicit catalog SKU is requested.
It also filters food units by the buyer's stated minimum shelf life.

Other corrections: exact acceptance phrases and numeric offers use a direct
parser; an offer meeting the last ask and floor immediately produces the signed
receipt. Model calls have a 12-second deadline with a profitable-offer fallback,
model rejection cannot discard an already profitable offer, and counteroffers
cannot increase above the prior ask or computed opening ask. Abandoned open
negotiations release reservations after 180 seconds; unconsumed receipt holds
expire after 900 seconds. Explicit unavailable/agreed events improve diagnosis.

Three targeted repair tests and six existing contract tests passed. Seller
Agent Card version 1.1.0 identifies the deployed repair. Only the seller child
was stopped; the official kit watchdog restarts it on its original local port,
retaining the market registration, tunnel, buyer and background workers.
See logs/seller-repair-deployment.json for actual restart confirmation.
The snapshot contained 549 units/149 SKUs and 861,219 balance, so blanket stock
expansion was not indicated. Genuine absent SKUs or insufficient buyer budgets
can still correctly end without a deal; successful conversion uplift is not yet
measured.

## Community replies removed; scheduled posts restored

Removed community.py, its tests, the worker service call and startup enable flag.
Removed the gate that suspended ordinary shop promotion. Pending community-owned
thread replies and votes are cancelled when present; previous acknowledgements
and community history are retained as evidence. No historical posts are deleted.
The recommendation worker was restarted without community actions. Five-minute
shop promotions and five-minute evidence-based four-to-five product recommendation
analysis resume on their original roles. Recommendation posts still require
sufficient evidence and meaningful changes. Three existing promotion tests pass.

## Shop ranking recovery and tomato&potato branding

The public pre-change board snapshot (logs/shop-ranking-before.json) reported
522 shop deals, 4.84 stars, 9,377,608 revenue, -3,381,050 profit and shop ALL .328,
versus buyer ALL .815. Inventory cost was approximately 4,722,626 with 1,618,950
cash. A major identifiable drag is unsold procurement expense: the ranking uses
cash balance-start-injected and does not add unsold stock value back. High ratings
do not offset the heavily weighted profit component. The snapshot does not by
itself establish that all inventory is unprofitable or that prices alone caused
low conversion.

shop_profit.py implements a 2,000,000 cash reserve and 1,500,000 inventory-cost
ceiling. New buys stop above the exposure ceiling; once eligible, each run spends
at most 250,000. Replenishment uses our shop's settled trades, a twenty-minute
horizon and one/two-unit food/goods minimums capped at four units, instead of
large minimum quantities inferred from market-wide sales. No historical logs or
inventory balances are edited to improve the reported score.

The seller uses observed same-SKU, same-grade settlement medians from the last
two hours (three samples minimum). Cash recovery uses a 5% target markup when
cash is below reserve or stock exceeds the cap, versus 15% otherwise. Quotes can
undercut the observed median but respect a 1% acquisition margin except for the
existing near-expiry food salvage rule. Profitable numeric offers are accepted
immediately. Future speculative storage costs are no longer added to today's
minimum acceptable price. Actual holding costs still affect platform profit.
A cached bounded ledger tail avoids reparsing the entire growing ledger on every
seller request. Lower per-unit margins trade off against faster cash recovery;
no ranking improvement or future profit is guaranteed.

Display name, Agent Card, receipts and active advertisements now use
`tomato&potato`. The documented registration nickname format allows letters,
numbers and dashes, not ampersands. The existing registration `totato2203-r3`
and keys are retained so inventory, settlement history and the buyer ranking
are not reset by creating a new identity. Public card metadata is refreshed by
rejoining the same shop registration after the local seller restart.

Essential validation: three financial-policy tests, five procurement/pricing
tests and six existing seller/buyer contract tests passed. The active seller
version is 1.2.0; the recommendation worker reloads branding via a restart, and
procurement changes apply at its next subprocess invocation. See deployment
records for observed status; post-change ranking gains remain unmeasured.

Deployment confirmation: local and public Agent Cards now return name
`tomato&potato`, version 1.2.0. Rejoining the same registration retained the deal
count (534 before/after). The public board response still contained its older
cached card metadata at that immediate check; the registered nickname remains
`totato2203-r3`. The live public Agent Card is the confirmed renamed surface.

## Sales-only news and three-shop comparisons

Shop-role news now consists exclusively of observed 24-hour settlement counts
and thanks, including an honest no-observed-sales message when applicable.
Inventory lists and the rotating inventory/conditions advertisement are removed.

Buyer-role recommendation posts select exactly three distinct shops rather than
four/five distinct SKUs. Each positive entry retains actual quote/market evidence.
A second section lists three distinct purchase-exclusion/caution shops, excluding
positive-list shops. Evidence is either an unexpired local receipt-validation
failure or a quote no older than five minutes at least 20% above the observed
SKU median. The post limits the conclusion to the observed quote/conditions and
notes possible quality differences; it does not assert that a shop is universally
unsafe. Insufficient evidence for either list suppresses the post rather than
inventing three names. Journal identifiers now include SKU and shop so different
shops offering the same SKU can be tracked without primary-key conflicts.

The final line is a short tomato&potato advertisement, with no inventory list.
Nine essential tests passed (three news tests and six recommendation tests).
The independent recommendation worker was restarted; the next restock hook
loads sales-only shop news. Buyer, seller and inventory policies are unchanged.

## Recommendation-only publication

Removed the restock hook's shop-news publisher and inventory draft generator.
Only the independent market-based recommendation worker now schedules posts.
Pending non-recommendation posts were cancelled where present; historical posts
and acknowledgement logs are preserved. The existing three recommended shops,
three evidence-based caution shops and short final advertisement remain.
Procurement subprocesses load this change on their next invocation; no running
seller or buyer restart is required. Syntax verification passed.
