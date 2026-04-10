# ⚡ QUICK START — 워커 클로드 (30초 컨텍스트 회복)

세션 재시작 시 가장 먼저 읽기. Full 컨텍스트는 `HANDOFF_PUMP_RESEARCH.md` 참조.

## 한 줄 요약

빗썸 펌프 신호 검증 — **immediate burst 신호 (vol≥20x + gain≥5% + tv≥50M)가 EV @0.3% +1.49%, n=77, 20/29 day cover**. 사용자(박성현)의 "매일 작전 day" 직관 데이터로 입증됨.

## 사용자 컨텍스트

- 박성현, 빗썸 자동매매 봇으로 600만 손실 (잔고 ~725k)
- "매일 80% 수익" 시도 중 (수학적 불가능, 사용자도 인지)
- TRAC/XTER 1~2분 폭발 타입 ❌, JOE/XION/ENJ 점진 펌프 ✅
- **손실 회복 베팅 spiral 위험** — 어떤 결과도 베팅 사이즈 늘리는 근거 X

## 가장 먼저 할 일 (재개 직후)

```bash
git pull origin master                    # 1. 최신 받기
cat RESEARCH_QUESTIONS.md                 # 2. 처리할 질문 (Q-6, Q-7 우선)
cat WORKER_LOG.md | tail -50              # 3. 직전 세션 마지막 entry
```

## 검증된 신호 (4/9 23시 발견)

```python
# Immediate burst — 4/10 default
def signal(candle, base_vol_30):
    return (
        candle.close > candle.open                    # 양봉
        and (candle.close - candle.open) / candle.open >= 0.05  # gain ≥ 5%
        and candle.close * candle.volume >= 50e6      # tv ≥ 50M
        and candle.volume / base_vol_30 >= 20          # vol burst 20x
    )
```

**실행**:
```bash
python live_pump_scanner.py --burst --watch       # 추천 (sig/day 2.6, EV +1.49%)
python live_pump_scanner.py --burst --strong      # 더 strict (vol≥30x, EV +1.60%)
```

## 검증된 사용자 사례

| 코인 | 신호 시각 | 실측 결과 |
|---|---|---|
| ENJ 4/9 00:15 | (사용자가 본 펌프) | exit **+33.27%** ⭐ |
| XYO 3/31 18:01 | | +12.31% |
| XION 4/7 14:38 | | +2.00% |

## 🚨 베팅 사이즈 룰 (Q-22 RESOLVED, 4/10 11:15 사용자 동의) — 절대 준수

| Tier | 조건 | 사이즈 | 결정자 |
|---|---|---|---|
| **S** | 검증신호 + 차트OK + 작전시간 + tv≥500M + Claude일치 | **80~95%** | **사용자 `'ALLIN'` 명시 필수** |
| **A** | 검증신호 + (차트 OR 시간대) + tv≥200M | **봇 자동 ≤20%**, 수동 30~50% | 사용자 + Claude |
| **B** | 검증신호만 (vol≥30x, gain≥7%, tv≥100M) | **15~20%** | 봇 자동 |
| **C** | 약한 신호 or chop | **0% 차단** | 봇 차단 |

**핵심**: 봇/워커 자동 매매는 **무조건 `MAX_AUTO_POSITION_PCT = 0.20` 이하**. 전액은 사용자가 "ALLIN"으로 명시했을 때만. 매 세션 새로 시작하는 워커는 **이 룰을 먼저 읽고 적용**. `midnight_bot.py`에 `classify_tier()`, `decide_position_size()`, `is_chop()` 구현됨.

**실측 슬리피지 (Q-18, n=2)**: 매수 slip ≈ 1.07% (기존 가정 0.3%의 3.6배). net EV ≈ 0. 전액 진입은 슬리피지 추가 훼손 → 사이즈 작을수록 유리.

## 🔥 손실 최소화 10원칙 (Q-28, 4/10 12:46)

1. **BE 룰 제거** — `be_enabled=false` default. Hard SL만 신뢰.
2. **Hard SL tight + hold** — SL -3~5% (점진형은 -4~5% wider). 이동 금지.
3. **Trailing stop wide** — 점진형은 **drop 3%** (1.5%는 너무 tight, CFG 교훈).
4. **부분 익절** — TP1 절반, TP2 1/3, 나머지 trail.
5. **시간 기반 청산 금지** — "5분 안에 +2%" 같은 시간 조건 X. **신호 기반 출구만**.
6. **패턴 기반 출구** — 음봉 3연속, vol dying, MA15 깨짐 → 매도.
7. **사용자 override 우선** — `user_override: "HOLD"/"EXIT"` positions.json 필드.
8. **chop 차단** — `is_chop()` 필터. NOM 같은 fake accumulation 자동 차단.
9. **상폐 코인 3% 이하** — 24h peak 돌파 + vol 10M burst 시만. 도박 영역.
10. **역추세 매수 금지** — 1분봉 -4% dump에 매수 X. trend pullback만 허용.

## 🔥 차트 시각 판독 필수 + Quiet Gradual 감시

- **burst만 감시 X** — 조용한 계단식 증강(CFG/MERL/MON)도 반드시 탐지
- `chart_snapshot.py` PNG → Read tool 이미지 인식 → 시각 패턴 판독
- **진입 전 반드시 차트 1장 이상 판독** (숫자 데이터만으로 결정 금지)
- live_pump_scanner에 Type D (quiet_gradual) 구현됨: MA정배열 + R²>0.65 + gain 3~20%

## 절대 금지

1. ❌ **봇 자동 매매 20% 초과** — Q-22 Kelly 6배 over-betting 경고.
2. ❌ **시간대 기반 전액 권고** — 이전 워커 실수.
3. ❌ **swap (포지션 교체)** — NOM→GRND 연쇄 손실.
4. ❌ **TRAC/XTER 1~2분 폭발 타입** — 시간 낭비.
5. ❌ **chop 종목 진입** — `is_chop()` 필터 필수.
6. ❌ **차트 안 보고 진입** — 숫자만 보면 fakeout 놓침.
7. ❌ **trail 1.5% (점진형)** — 점진 대장은 3%+ wide 필수.

## 협업 (연구원 ↔ 워커)

```
워커 (저쪽 PC): 매일 paper trading + WORKER_LOG.md 업데이트 + push
연구원 (이쪽 PC): WORKER_LOG.md 읽고 새 가설 → RESEARCH_QUESTIONS.md → push
```

## 핵심 파일

| 파일 | 용도 |
|---|---|
| `HANDOFF_QUICK.md` | 30초 컨텍스트 회복 (이 파일) |
| `HANDOFF_PUMP_RESEARCH.md` | full 컨텍스트 |
| `RESEARCH_QUESTIONS.md` | 처리할 질문 list |
| `WORKER_LOG.md` | 매일 작업 기록 |
| `live_pump_scanner.py` | 라이브 신호 스캐너 |
| `daily_results/` | 일별 결과 JSON |
