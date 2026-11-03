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
