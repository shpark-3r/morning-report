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

## 절대 금지

1. ❌ 이전 메모리 "EV +0.90%" 신뢰 — 재현 시 -1.53% (낙관 가정 차이)
2. ❌ "EV +6.10% (n=10)" 라이브 EV로 추정 — cherry pick 위험
3. ❌ **봇 자동 매매 20% 초과** — Q-22 Kelly 6배 over-betting 경고. 사용자 'ALLIN' 없이는 절대 X.
4. ❌ **"22~01시 전액 베팅" 같은 시간대 기반 전액 권고** — 이전 워커 실수. Kelly 기반 10~15% 범위 초과 금지.
5. ❌ "더 강한 돌파로 갈아타기" (swap) — NOM→GRND swap 연쇄 손실 사례. 포지션 교체는 추가 손실 지뢰.
6. ❌ TRAC/XTER 1~2분 폭발 타입 시간 낭비
7. ❌ chop 종목 진입 — NOM 같은 6h 약한 추세 + 높은 양봉비율. `is_chop()` 필터 필수.

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
