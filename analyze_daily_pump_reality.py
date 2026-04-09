"""
사용자 반박 검증: "매일이 작전 day"

확인할 것:
1. 일별 펌프 카운트 (1분봉 60일치): +30%/+50%/+80% 임계로
2. 사용자가 본 코인 사례 (D, OGN, NOM, SWAP 등)가 어느 day에 발생했는지
3. 우리 strict 신호가 일별로 몇 건 잡았는지 vs 매일 발생한 펌프
4. Strict filter를 완화하면 더 잡을 수 있는가
"""
import json
import os
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
from analyze_realistic_simulation import load_candles_1m, find_adaptive_signals, apply_costs
from analyze_adaptive_trailing import simulate_adaptive_trailing

KST = timezone(timedelta(hours=9))


def find_pump_starts_dedupe(candles, window_min, threshold_pct, dedupe_min=60):
    """1분봉에서 펌프 시작점만 (dedupe). 시작 캔들의 close 기준 future_max +X% 도달."""
    pumps = []
    last_pump = -10000
    n = len(candles)
    for i in range(n - window_min):
        c = candles[i][2]
        if c <= 0 or i - last_pump < dedupe_min:
            continue
        future_max = max(candles[j][3] for j in range(i + 1, min(i + 1 + window_min, n)))
        gain = (future_max - c) / c * 100
        if gain >= threshold_pct:
            pumps.append({'i': i, 'ts': candles[i][0], 'gain': gain, 'price': c})
            last_pump = i
    return pumps


def main():
    coins = load_candles_1m()
    print(f'Loaded {len(coins)} coins')

    # ===== 1. 일별 펌프 카운트 (60분 윈도우, +30%/+50%/+80%) =====
    print('\n=== Daily pump count (1분봉, 60min window, dedupe 1h) ===')
    daily_30 = defaultdict(int)
    daily_50 = defaultdict(int)
    daily_80 = defaultdict(int)
    pump_30_examples = defaultdict(list)

    for coin, candles in coins.items():
        # +30% in 60min
        for p in find_pump_starts_dedupe(candles, 60, 30, dedupe_min=120):
            dt = datetime.fromtimestamp(p['ts'] / 1000, KST)
            daily_30[dt.date()] += 1
            pump_30_examples[dt.date()].append((coin, dt, p['gain']))
        # +50% in 60min
        for p in find_pump_starts_dedupe(candles, 60, 50, dedupe_min=120):
            dt = datetime.fromtimestamp(p['ts'] / 1000, KST)
            daily_50[dt.date()] += 1
        # +80% in 60min
        for p in find_pump_starts_dedupe(candles, 60, 80, dedupe_min=120):
            dt = datetime.fromtimestamp(p['ts'] / 1000, KST)
            daily_80[dt.date()] += 1

    # 출력
    all_dates = sorted(set(daily_30.keys()) | set(daily_50.keys()) | set(daily_80.keys()))
    print(f'\n{"date":<12} {"+30%":>6} {"+50%":>6} {"+80%":>6}  examples (+30%, top 5)')
    for d in all_dates:
        ex = sorted(pump_30_examples[d], key=lambda x: -x[2])[:5]
        ex_str = ', '.join(f'{c}+{g:.0f}%' for c, _, g in ex)
        print(f'  {str(d):<12} {daily_30[d]:>6} {daily_50[d]:>6} {daily_80[d]:>6}  {ex_str}')

    # 합계
    print(f'\n  TOTAL    +30%: {sum(daily_30.values())}, +50%: {sum(daily_50.values())}, +80%: {sum(daily_80.values())}')
    print(f'  per-day  +30%: {sum(daily_30.values())/len(all_dates):.1f}/day, +50%: {sum(daily_50.values())/len(all_dates):.1f}/day, +80%: {sum(daily_80.values())/len(all_dates):.1f}/day')

    # ===== 2. 사용자가 본 코인들 일별 발생 =====
    print('\n=== User-mentioned coins (presence in pumps) ===')
    target_coins = ['ENJ', 'JOE', 'XION', 'XYO', 'TRAC', 'D', 'NOM', 'OGN', 'SWAP', 'XVS', 'CTSI', 'SOLV', 'COMP', 'PEAQ', 'JTO']
    for coin in target_coins:
        if coin not in coins:
            print(f'  {coin}: not in data')
            continue
        candles = coins[coin]
        # +30% pumps
        pumps = find_pump_starts_dedupe(candles, 60, 30, dedupe_min=120)
        if pumps:
            print(f'  {coin}: {len(pumps)} pumps (+30% in 60min)')
            for p in pumps[:5]:
                dt = datetime.fromtimestamp(p['ts'] / 1000, KST)
                print(f'    {dt:%m-%d %H:%M} +{p["gain"]:.1f}%')
        else:
            print(f'  {coin}: NO +30% pumps detected')

    # ===== 3. 우리 신호 일별 분포 =====
    print('\n=== Our signals (Adaptive multi-lookback): daily ===')
    sigs = find_adaptive_signals(coins)

    daily_sigs_all = defaultdict(int)
    daily_sigs_strict = defaultdict(int)

    for s in sigs:
        candles = coins[s['coin']]
        i = s['i']
        if i < 35:
            continue
        tv_5 = sum(candles[j][2] * candles[j][5] for j in range(i - 5, i))
        past_5 = sum(candles[j][5] for j in range(i - 5, i))
        base_30 = sum(candles[j][5] for j in range(i - 35, i - 5)) / 30
        vr = (past_5 / 5) / base_30 if base_30 > 0 else 0
        dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
        daily_sigs_all[dt.date()] += 1
        if tv_5 >= 200e6 and vr >= 10:
            daily_sigs_strict[dt.date()] += 1

    print(f'\n{"date":<12} {"all_sig":>8} {"strict":>7} {"+30%pumps":>10} {"+50%pumps":>10}')
    for d in all_dates:
        print(f'  {str(d):<12} {daily_sigs_all[d]:>8} {daily_sigs_strict[d]:>7} {daily_30[d]:>10} {daily_50[d]:>10}')

    # ===== 4. 매일 1건은 잡는가? =====
    print('\n=== Days with at least 1 strict signal ===')
    days_with_strict = sum(1 for d in all_dates if daily_sigs_strict[d] >= 1)
    days_with_pump = sum(1 for d in all_dates if daily_30[d] >= 1)
    print(f'Days with +30% pump: {days_with_pump}/{len(all_dates)}')
    print(f'Days with strict signal: {days_with_strict}/{len(all_dates)}')


if __name__ == '__main__':
    main()
