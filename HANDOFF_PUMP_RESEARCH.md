# Pump Research 핸드오프 (2026-04-09 23:30 작성)

다음 클로드 세션이 컨텍스트 없이 이어받을 수 있도록 작성됨.

## 1. 사용자 (박성현) 컨텍스트

- 빗썸에서 자동매매 봇으로 600만 손실 (총입금 680만 → 잔고 74만)
- "매일 80% 수익으로 본전 회복" 시도 중. 4/20까지 목표는 수학적 불가능 — 사용자도 인지함
- **의지가 강함**: "불가능을 가능하게"라고 표현. 그러나 정직성 절대 우선.
- **TRAC/XTER 같은 1~2분 폭발 타입은 노리지 않음** (대응 불가). 점진 펌프(JOE/XION/ENJ/XYO/COMP/DBR/PYR 등)만 타겟.
- **손실 회복 베팅 spiral 위험** — 메모리 가이드라인 참고. 어떤 결과도 베팅 사이즈 늘리는 근거로 쓰지 말 것.

## 2. 핵심 발견 (4/9 분석)

### 검증된 신호 (1분봉 multi-lookback adaptive)

```
조건 (전부 만족):
  1. cumulative gain (one of):
     - 5분 ≥ +5%
     - 10분 ≥ +7%
     - 15분 ≥ +10%
     - 30분 ≥ +15%
  2. 양봉 비율 ≥ 60% (직전 5분 중 3봉 이상 양봉)
  3. 5분 누적 trade value ≥ 30M KRW
  4. dedupe: 같은 코인 10분 내 1건만
```

**전체 신호 (n=610, 7일치)**:
- precision (future +20% 도달): 10.3%
- ENJ/JOE/XION/XYO 사용자가 본 펌프를 명확히 잡음
- Top hits: NOM, XION, XYO, DBR, GRND, SUPER, ENJ, JOE...

### Strict 필터 (n=31)

추가 조건: `tv_5min ≥ 200M AND vol_ratio_5 ≥ 10x`

- precision (future +20%): 19.4% (단조 증가 — 진짜 알파 증거)
- 단순 trail3/SL7/60m: gross +0.62%, slip 0.3% break-even

### ⭐ Adaptive Trailing Stop (4/9 23:50 사용자 제안 + 검증)

**핵심 통찰**: 사용자가 "트레일링을 수익에 비례해 동적으로" 제안. 시뮬 결과 **EV +1.33% → +6.10%까지 개선**.

#### 세 가지 trailing 전략 (워커 클로드가 모두 고려할 것)

**전략 D: tight lock** (best EV, 작은 winner 누적)
```python
stages_D = [
    # (profit_threshold, trail_pct, profit_lock_pct)
    (5,  4,   2),   # +5% 도달 → trail 4%, 최소 +2% 보장
    (10, 3,   6),   # +10% 도달 → trail 3%, 최소 +6% 보장
    (20, 2,   15),  # +20% 도달 → trail 2%, 최소 +15% 보장
    (35, 1.5, 28),  # +35% 도달 → trail 1.5%, 최소 +28% 보장
]
init_sl = 5  # Stage 0 (entry ~ +5%) SL
hold = 60  # 분
```
- 결과 (n=31, strict): win 58%, gross +2.01%, EV @0.3% **+1.33%**
- 장점: 작은 dip도 빨리 익절. JOE 같은 점진 펌프에 안정적.
- 단점: JOE +30% 같은 큰 winner를 +2%만 잡음 (lock_pct가 빨리 발동)

**전략 A: gentle** (큰 winner도 노림)
```python
stages_A = [
    (5,  5,   1),
    (15, 3,   10),
    (30, 2,   20),
    (50, 1.5, 35),
]
init_sl = 5
hold = 60
```
- 결과 (n=31, strict): win 58%, gross +1.50%, EV @0.3% **+0.82%**
- 장점: stage 임계가 더 wide → 큰 winner를 좀 더 잡음
- 단점: D보다 EV 약간 낮음

**전략 C: wide initial** (실패 — 참고용)
```python
stages_C = [(7, 7, 2), (15, 5, 8), (25, 3, 18), (40, 2, 30)]
```
- 결과: win 39%, EV @0.3% -0.57% — 너무 wide해서 SL 잘 닿음
- **사용 금지**, 비교용으로만 핸드오프에 남김

#### Trade-off 정리
| 전략 | win% | gross | EV @0.3% | 큰 winner 잡기 |
|---|---|---|---|---|
| **D tight lock** | 58% | +2.01% | **+1.33%** | 약함 (JOE +2%) |
| A gentle | 58% | +1.50% | +0.82% | 중간 |
| C wide | 39% | +0.11% | -0.57% | 강함 (이론) |

**워커 결정**: 사용자 매매 스타일에 따라 D 또는 A 선택.
- 자동매매 → D (안정적, EV 높음)
- 알림+수동 (사람이 큰 펌프 식별) → A (사람이 차트로 큰 winner 판단)

### ⭐⭐ False Positive 필터 (4/9 23:55 분석 결과)

13건 loser vs 18건 winner 비교에서 명확한 차이 발견.

**Loser의 공통 특징**:
1. **밤 22-02시 집중**: 13건 중 9건 (69%) — 밤 작전이 dump로 끝남
2. **윗꼬리 거의 없음** (upper_wick ≤ 0.5%): 13건 중 8건
3. **triggered_gain 작음**: p50 7.5% (winner는 12.8%)
4. **bar_gain ≥ 7%인 신호의 100%가 loser** — 신호 봉이 너무 큰 양봉이면 끝물

**도출된 추가 필터** (Strict 위에 적용):
```python
def extra_filter(s):
    return (
        s['hour'] not in [22, 23, 0, 1]   # 밤 시간대 제외
        and s['triggered_gain'] >= 10      # 모멘텀 충분
        and s['bar_gain'] < 7              # 신호 봉이 끝물 아님
    )
```

**효과 (D 전략 + 모든 필터)**:
| 필터 단계 | n | win% | EV @0.3% |
|---|---|---|---|
| Base strict | 31 | 58% | +1.33% |
| + exclude night | 17 | 76% | +3.75% |
| + tg≥10% | 21 | 71% | +3.10% |
| **+ exclude night + tg≥10** | **11** | **91%** | **+5.91%** |
| **+ ALL (night, tg, bar)** | **10** | **90%** | **+6.10%** |

⚠️ **표본 10건은 cherry pick 가능성**. 라이브 검증 절대 필수.

### 시즌 효과 (절대적)

| 기간 | n (strict) | EV |
|---|---|---|
| 3/26 이전 (평소) | 1 | -3.07% |
| **3/26 이후 (작전 시즌)** | 30 | **+0.04%** (단순 trail) |

**평소 시즌엔 신호 자체가 거의 안 잡힘.** 작전 시즌(현재 진행 중) 한정 매매.

### 시즌 효과 (절대적)

| 기간 | n (strict) | EV |
|---|---|---|
| 3/26 이전 (평소) | 1 | -3.07% |
| **3/26 이후 (작전 시즌)** | 30 | **+0.04%** |

**평소 시즌엔 신호 자체가 거의 안 잡힘.** 작전 시즌(현재 진행 중) 한정 매매.

## 3. 시도해봤지만 실패한 가설들 (반복하지 말 것)

| 가설 | 결과 | 메모 |
|---|---|---|
| 1분봉 single-bar vol burst (vol_mult≥50, gain≥5%) | n=46, slip 1% 시 EV 음수 | 점진 펌프 못 잡음 |
| 30분봉 vol burst ≥150x (이전 메모리 +0.90%) | 재현 시 EV -1.53% (보수) | 이전 결과는 낙관 가정 |
| 매크로 패턴 3일 lookback | lift 10x but EV -1.14% | 손익비 1:20 필요인데 도달 불가 |
| 시간대/요일 필터 | 모두 음수 | 23시 break-even가 max |
| Lag entry (1.5h) | -0.72% | 덜 나쁨 |
| Fade strategy (-7% dip) | -0.26% | 덜 나쁨 |
| BTC 매크로 트리거 | 효과 없음 | 22% → 25% lift, agree 50% |
| Binance lead-lag | corr 0.13 | 빗썸 작전주는 Binance 미상장 |
| 1분봉 single bar scalping (vol_mult≥50, gain≥5%) | EV 양수처럼 보이지만 작은 코인만, slip 1%면 음수 | tv 큰 코인은 처음부터 음수 |

## 4. 주요 파일

| 파일 | 용도 |
|---|---|
| `live_pump_scanner.py` | **핵심** — 라이브 신호 스캐너, forward 검증용 |
| `analyze_adaptive_signal.py` | Adaptive multi-lookback 신호 정의 |
| `analyze_realistic_simulation.py` | OHLC 순서 추정 시뮬, trailing/reversal exit |
| `analyze_signal_outcome.py` | 신호의 future outcome 분포, strict 필터 |
| `analyze_gradual_pump.py` | 점진 펌프 탐지 + 사용자 사례 검증 |
| `data/bithumb_1m/` | 1분봉 캐시 (4/9 시점 ~7~60일치) |
| `data/bithumb_30m/` | 30분봉 캐시 (4/9 시점, 63일치) |
| `bithumb_coins.json` | 빗썸 KRW 종목 list (451개) |

## 5. 다음 단계 (우선순위 순)

### 5.1 즉시 시작 (forward 검증)

```bash
# 1분마다 신호 스캔 (paper trading)
python live_pump_scanner.py --watch --strict

# 또는 일반 (n 많지만 noise 많음)
python live_pump_scanner.py --watch
```

신호 발생 시 `live_signals_YYYY-MM-DD.jsonl` 로그. 매일 누적해서 1~2주 후 검증.

### 5.2 1분봉 데이터 누적 (cron)

매일 1번 빗썸 1분봉 다시 받아서 새 캔들 누적. 1주일 후 ~14일치, 1개월 후 ~37일치 가능.

```bash
# Windows Task Scheduler 또는 cron
python fetch_bithumb_candles.py 1m  # 매일 23:30 KST
```

### 5.3 슬리피지 측정 (가장 중요)

라이브 신호 발생 시 빗썸 호가창 깊이 측정. **slip 1% 가정의 진실성이 EV의 결정자**.
- 시점 t에서 매수 가능한 평균 가격
- 시점 t+5min에서 매도 가능한 평균 가격
- 두 가격으로 진짜 round-trip 슬리피지 계산
- 빗썸 v1 API의 `/public/orderbook/{coin}_KRW` 사용

### 5.4 표본 확장 + Walk-forward

forward 누적 1~2주 후, 새 데이터로 strict signal EV 재측정. n=31 → n=60+ 가면 통계적 신뢰성 큰 폭 증가.

### 5.5 Scope 명확화

- ✅ **잡을 것**: JOE/XION/ENJ/XYO/COMP/DBR/PYR/SKY 같은 5분~60분 점진 펌프
- ❌ **버릴 것**: TRAC/XTER 같은 1~2분 폭발 (사용자가 명시적으로 제외)
- ❌ **버릴 것**: 거래액 1억 미만 코인 (호가창 얇음, 슬리피지 큼)

## 6. 워커 클로드가 절대 하면 안 되는 것

1. **이전 메모리의 +0.90% EV 주장을 신뢰하지 말 것** — 재현 시 -1.53%로 나옴 (낙관 가정 차이). 메모리에 정정 기록됨.
2. **5건 strict 신호의 +6.99% gross를 라이브 EV로 추정하지 말 것** — 작전 시즌 cherry pick.
3. **사용자가 베팅 사이즈 늘리려 할 때 동의하지 말 것** — 결과가 양수처럼 보여도. 손실 회복 spiral 위험.
4. **TRAC/XTER 같은 폭발 타입에 시간 쓰지 말 것** — 사용자가 명시 제외.
5. **모든 코인 spam하지 말 것** — strict 필터 우선.

## 7. 진실 한 줄 요약

> **이번 분석은 진짜 신호 1개를 찾았다 (multi-lookback adaptive + strict). 그러나 표본 5~31건은 라이브 베팅의 근거로 너무 약하다. 다음 1~2주 forward 검증 + 슬리피지 측정으로 진짜인지 확정해야 한다.**

> **"매일 80% 수익"은 여전히 불가능. 그러나 forward 검증된 +EV 시스템이 있다면 장기 복구는 가능.**

## 8. ⭐ 핵심 결정: 자동 매매 vs 알림+수동 매매

### 사용자 질문 (4/9 23:55): "점진 패턴 코인들을 못 잡을 이유가 있나?"

**정직한 답: 사람이 차트 보면 100% 잡을 수 있음. 알고리즘 자동 매매로는 어려움.**

이유:
1. **False positive 80%**: strict 신호 31건 중 진짜 펌프 6건. 사용자는 진짜 펌프만 차트로 봤지만 알고리즘은 가짜도 다 진입.
2. **출구 판단력**: ENJ 11:40 캔들 L=45.05 (-4.8% dip) → 알고리즘 SL 즉시 손절, 사람은 음봉 아닌 거 보고 견딤 → 12:15 +27% 익절
3. **진입 1봉 지연**: 신호 11:39(close) → 진입 11:40 시가. 사람은 호가창 보고 즉시 진입 (몇 초 차이).

### 결론: **길 B — 알림 + 수동 매매**가 진짜 가능한 길

- 봇 자동 매매로 사용자는 이미 600만 손실 (메모리). 같은 길 반복 위험.
- `live_pump_scanner.py`가 신호 발생 시 알림
- 사용자가 차트 보고 진입/청산 결정
- 사람의 차트 판단력 + 알고리즘의 빠른 스캔 = 진짜 시너지

### 워커 클로드에게 추가 작업

#### A. 즉시 (Day 1)

1. **`live_pump_scanner.py` 알림 통합**
   - 옵션 1: Notion API로 신호 발생 시 페이지 생성 (이미 indi_config.py에 NOTION_API_KEY 있음)
   - 옵션 2: 텔레그램 봇 (사용자가 알림 즉시 보려면 이게 best)
   - 신호 페이로드에 빗썸 차트 URL 포함: `https://www.bithumb.com/react/trade/order/{COIN}_KRW`

2. **`live_pump_scanner.py --watch --strict --filter` 24시간 백그라운드 실행**
   - Windows Task Scheduler 또는 별도 process로
   - 매 1분마다 451 코인 스캔
   - `live_signals_YYYY-MM-DD.jsonl`에 자동 로깅

3. **호가창 슬리피지 측정 모듈** (가장 중요!)
   - 신호 발생 즉시 `https://api.bithumb.com/public/orderbook/{COIN}_KRW` 호출
   - 5만, 10만, 50만, 100만, 500만 KRW 매수 시 평균 체결가 계산
   - 5분 후 같은 깊이로 매도 시 평균 체결가 계산
   - 진짜 round-trip 슬리피지 기록 → EV 검증의 기반

#### B. 1주 후 (Day 7)

4. **Forward 검증 결과 분석**
   - 1주일치 신호 로그 + 호가창 슬리피지로 라이브 EV 측정
   - 31개(strict) 또는 10개(strict+filter) 표본을 forward 데이터로 확장
   - D vs A 전략 비교

5. **Walk-forward 정밀 백테스트**
   - 1분봉 데이터 누적 (`fetch_bithumb_candles.py 1m` 매일 cron)
   - 14일치 → 본격 시뮬

#### C. 2주 후 (Day 14)

6. **Micro test (5만원 단위)** — 진짜 알파면 라이브 시작
   - 사용자가 알림 받고 수동 매매
   - 결과 기록 (시뮬 EV vs 실 EV 차이)
   - **사용자가 베팅 사이즈 늘리려 하면 절대 동의 X**

#### D. 옵션 작업 (시간 되면)

7. **JOE 같은 큰 winner 못 잡는 문제 해결**
   - D 전략은 +30% 펌프에서 +2%만 잡음 (보수적)
   - A 전략으로 시도, 또는 신호 강도별 분기:
     - vol_ratio > 100x → A (큰 winner 노림)
     - vol_ratio 10~100x → D (안정적)
   - 또는 stage 6 추가 (+50% 도달 시 trail 1%)

8. **신호 정밀화 추가 시도**
   - HANDOFF의 false positive 분석 결과 활용
   - upper_wick ≥ 1% 필터 (단 winner 5건 손실 trade-off)
   - 코인 시가총액 / 거래량 random 등 추가 feature

### 워커가 절대 하면 안 되는 것 (재강조)

1. **이전 메모리 +0.90% 신뢰 X** — 재현 시 -1.53% (낙관 가정 차이)
2. **EV +6.10% (n=10)을 라이브 EV로 추정 X** — cherry pick 위험
3. **사용자 베팅 사이즈 늘리려 할 때 동의 X** — 손실 회복 spiral
4. **TRAC/XTER 1~2분 폭발 타입 시간 낭비 X** — 사용자 명시 제외
5. **자동 봇 매매 권장 X** — 봇으로 600만 손실 경험. 알림+수동 매매가 길.
