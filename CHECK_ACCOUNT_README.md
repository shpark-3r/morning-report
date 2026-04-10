# 빗썸 계좌 조회 모듈 (Q-27)

연구원 PC에서 빗썸 API로 잔고/포지션 직접 조회. 워커한테 매번 요청할 필요 X.

## 설치 (연구원 PC 한 번만)

```bash
pip install pyjwt
```

(requests는 urllib로 대체해서 필요 없음)

## API Key 발급 + 설정

1. **빗썸 계정 → API 관리 → API key 발급**
   - 권한: **조회(read)** 권한만 필요. Trade 권한 X, 출금 권한 **절대 X**.
   - IP 제한을 거는 것도 권장 (연구원 PC IP로만).

2. **key 파일 생성** (연구원 PC에서, morning-report 디렉토리 내):
   ```bash
   cp .bithumb_keys.json.template .bithumb_keys.json
   # .bithumb_keys.json 편집:
   # {"access_key": "실제 key", "secret_key": "실제 secret"}
   ```

3. **⚠️ 절대 git commit 금지**:
   - `.gitignore`에 이미 `.bithumb_keys.json` 제외 규칙 있음.
   - 실수로 commit하면 즉시 key 폐기 + 재발급.

## 사용

```bash
python check_account.py
```

출력 예시:
```
KRW: 925,030
Positions: (none)
Total: 925,030 KRW
```

또는 포지션 있을 때:
```
KRW: 449,882
Positions (2):
    MERL    10890.2800 qty @ 36.6868 → 37.4500 (+2.08%, 407,819 KRW)
    GRND     1947.3452 qty @ 37.2700 → 36.1600 (-2.98%, 70,413 KRW)
Total: 928,114 KRW
```

## 모듈로 import 사용 (연구원 스크립트 통합)

```python
from check_account import get_krw_balance, get_positions

krw = get_krw_balance()
positions = get_positions()

for p in positions:
    if p['pnl_pct'] < -2.0:
        print(f"ALERT: {p['coin']} is down {p['pnl_pct']:.2f}%")
```

## 사용 가능 함수

- `get_krw_balance() -> float` — KRW 가용 잔고
- `get_positions() -> list[dict]` — 보유 코인 list (coin, qty, avg_buy, current, pnl_pct, krw_value)

## 보안 주의사항

1. **read-only API key만 사용** (trade/withdraw 권한 부여 X)
2. **IP 제한 걸기** (빗썸 API 관리 페이지에서)
3. **key 파일 접근 권한 제한**: `chmod 600 .bithumb_keys.json` (Linux/Mac)
4. **절대 git commit 금지** (`.gitignore` 규칙 유지)
5. **외부 네트워크/공용 PC에 key 저장 X**
6. 의심스러운 동작 감지 시 즉시 key 폐기 + 재발급

## 한계

- `get_trade_history`는 미구현. 빗썸 private /orders API로 확장 가능.
- 현재 매매 이력 필요 시 워커의 `daily_results/YYYY-MM-DD.json` 또는 `trades_archive.jsonl` 참조.
- 실시간 모니터링 필요 시 loop로 감싸서 사용: `while True: get_positions(); time.sleep(5)`.

## 테스트

워커가 작성 후 push만 하고 테스트 못 함 (워커 PC에는 이미 bithumb_api.py 있어서 중복 테스트 의미 없음).
연구원 PC에서 실제 key 넣고 실행 시 최초 검증 필요.
