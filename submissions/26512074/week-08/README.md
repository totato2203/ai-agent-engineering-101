# Week 08 — 정산 신뢰와 비용 통제를 결합한 시장 에이전트

**현재 상태: 공개 직전 준비. 시장 등록·실거래·정산·PR 생성은 하지 않았습니다.**
현재 공개 보드는 Round 3 요청에도 Round 2를 반환했습니다. 실제 Round 3의
판매 20건·구매 20건, 순위와 전후 평균가는 아직 결과가 아닙니다.

## 준비한 것

- 실제 Codex 모델이 1회 생성한 배치 정책: 기본 호가 115/195/275.
- 빠른 A2A 판매·구매와 서명 영수증, 후기·자기 정산 경험·공급 편중을 쓰는 선택.
- ACP descriptor로 만든 checkout 도구와 AP2 형태 mandate 검증·서명·정산.
- 결제 총액 바뀜·초과·위조·재사용·응답 손실 방어.
- 토큰 제한: 일반 거래는 정책 실행, 모호한 가격은 시간당 최대 6회 의미 해석
  요청(교정 포함 모델 호출은 최대 12회), 운영 정책 갱신은 하루 최대 6회.
- 공유 파일과 기존 7주차 운영을 교체하지 않는 별도 키트 v3 사본·배포 게이트.

전략 비교는 STRATEGY.md, 설계·구조도·검증 범위는 REPORT.md를 봅니다.
모델의 자연어 rationale에는 항목별 가격 설명과 구조화 수치가 다른 부분이 있어
원문을 그대로 보존했습니다. 실행 권한은 검증된 구조화 수치이며 위 기본 호가는
`reserve + opening_markup`으로 계산한 값입니다.

## 로컬 준비·검사

Python 3.12와 로그인된 Codex CLI (`gpt-5.6-terra`, low)가 필요합니다.

```powershell
python -m venv submissions/26512074/week-08/.venv
submissions/26512074/week-08/.venv/Scripts/python.exe -m pip install -r submissions/26512074/week-08/requirements.txt
cd submissions/26512074/week-08
# model-policy.json은 실제 모델 호출로 이미 생성돼 있으므로 다시 생성할 필요 없음
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s tests -v
./.venv/Scripts/python.exe -X utf8 launch.py
```

실제 검증은 핵심 10개와 구매자 2개로 나눠 통과했습니다. 통합 실패 원본은
`logs/core-tests.log`, 수정 후 통과는 `core-tests-final.log`, 구매자 통과는
`buyer-tests.log`입니다. 전부 로컬 가상 정산 기관이며 실제 시장 실적이 아닙니다.

## 나중에 승인받고 공개할 때만

기본 명령은 공개하지 않고 준비 상태만 출력합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File submissions/26512074/week-08/start-round3.ps1
```

다음은 **실제로 시장에 등록하고 기존 7주차 운영을 교체하는 명령**입니다.
이번 작업에서는 실행하지 않았습니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File submissions/26512074/week-08/start-round3.ps1 -Publish -ReplaceWeek07
```

스크립트는 먼저 준비 상태와 Round 3 개시 여부를 검사합니다. 그 후에만 기존
운영 PID를 확인해 종료하고 새 운영자를 숨김 창으로 띄웁니다. 기존 7주차의
이름·개인키·claim code와 cloudflared를 재사용하므로 해당 로컬 파일이 필요합니다.
개인키는 공개 시작 때만 새 폴더로 복사하며 Git에서 제외됩니다.

실행 후 `logs/market-kit.log`의 `[acp] paid`, `[acp] settled`, `verified True`를
실제 보드와 대조해야 합니다. 완료 판단은 실제 정산과 시장 응답으로만 합니다.
`metrics.json`은 정산 수·판매 마진·매출·구매 지출·지갑 순유입을 집계하며 공개
로그에는 주문 예산을 표시하지 않습니다. 키트의 실패한 정산은 성공으로 세지 않습니다.

PC 전원·네트워크·로그인을 유지해야 합니다. 프로그램 실행 중 자동 절전을
방지하지만 재부팅 후 자동 로그인·자동 실행까지 설치한 것은 아닙니다.
응답을 잃은 결제의 journal 상태가 `unknown`이면 같은 complete를 재전송하지
않고 조회·시장 기록으로 먼저 조정해야 합니다.

## 제출 전 남은 실제 운영 작업

1. 승인 후 Round 3에 공개해 판매·구매 정산을 각각 20건 이상 확보.
2. 모델 정책 변경 전후 첫 호가·품목별 평균 거래가와 순위를 수집.
3. 실제 거부 사유와 정산 로그로 REPORT.md의 결과 표를 채우기.
4. 비밀 파일을 제외하고 운영 로그를 커밋한 뒤 제출 PR 생성.

코드만 준비한 상태를 실적 충족이나 최종 과제 제출 완료로 표현하지 않습니다.
