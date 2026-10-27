## What I built

실제 모델이 묶음 가격·구매 정책을 정하고 빠른 A2A 도구가 실행하는 가게와
구매자를 구현했습니다. ACP 안내에서 checkout 도구를 구성하고, AP2 형태
mandate·서명·총액·주문 재사용을 검사합니다.

## What I tried and discarded

- 허위 소문·가짜 단속 권한 대신 검증된 결제 기능과 실제 거래 경험을 활용했습니다.
- 거래마다 모델을 부르는 구조를 배치 정책으로 바꿔 지연과 호출 수를 줄였습니다.
- 첫 통합 검사에서 이벤트 인자 이름 충돌이 발생했고 원본 로그를 보존해 수정했습니다.
- 로컬 정산 결과를 실제 Round 3 실적으로 표시하지 않았습니다.

## How to run

Python 3.12, Codex `gpt-5.6-terra`, low를 사용합니다. 배포하지 않는 준비 확인:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File submissions/26512074/week-08/start-round3.ps1
```

실제 공개 명령·로컬 검사·신원 파일 설정은 README.md에 있습니다.

## Checklist

- [x] 로컬 핵심 검사 12개 통과
- [x] 실제 모델 정책·실패·수정 후 로그 보존
- [x] 개인키·claim code·API 키 제외
- [x] 기존 기록을 스쿼시하지 않음
- [ ] 실제 판매 정산 20건과 구매 정산 20건 확보
- [ ] 실제 Round 3 순위·가격 전후·거부 사유를 REPORT.md에 반영
- [ ] 배포 로그를 커밋하고 제출 PR 생성
