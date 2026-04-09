"""
Filter 완화 vs day coverage vs EV trade-off.

목표: 매일 1건 이상 신호 발생하면서 EV 양수 유지하는 임계 찾기
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from analyze_realistic_simulation import load_candles_1m, find_adaptive_signals, apply_costs
from analyze_adaptive_trailing import simulate_adaptive_trailing

KST = timezone(timedelta(hours=9))


def main():
    coins = load_candles_1m()
    sigs = find_adaptive_signals(coins)
    print(f'Loaded {len(coins)} coins, {len(sigs)} adaptive signals')

    # 모든 신호 enrich
    enriched = []
    for s in sigs:
        candles = coins[s['coin']]
        i = s['i']
        if i < 35:
            continue
        tv_5 = sum(candles[j][2] * candles[j][5] for j in range(i - 5, i))
        past_5 = sum(candles[j][5] for j in range(i - 5, i))
        base_30 = sum(candles[j][5] for j in range(i - 35, i - 5)) / 30
        vr = (past_5 / 5) / base_30 if base_30 > 0 else 0
        o, c = candles[i][1], candles[i][2]
        bar_gain = (c - o) / o * 100 if o > 0 else 0
        triggered_gain = 0
        for lb_min, min_g in [(5, 5), (10, 7), (15, 10), (30, 15)]:
            if i >= lb_min:
                sc = candles[i - lb_min][2]
                if sc > 0:
                    cg = (c - sc) / sc * 100
                    if cg >= min_g:
                        triggered_gain = cg
                        break
        dt = datetime.fromtimestamp(candles[i][0] / 1000, KST)
        enriched.append({
            **s,
            'tv_5': tv_5, 'vr5': vr, 'bar_gain': bar_gain,
            'triggered_gain': triggered_gain,
            'date': dt.date(), 'hour': dt.hour, 'dt': dt,
        })

    print(f'Enriched: {len(enriched)}')
    total_days = len(set(s['date'] for s in enriched))
    print(f'Total days with any signal: {total_days}')

    stages_D = [(5, 4, 2), (10, 3, 6), (20, 2, 15), (35, 1.5, 28)]

    # ===== Filter 완화 grid =====
    print('\n=== Filter loosening grid (D adaptive trailing) ===')
    print(f'  {"tv_min":<10} {"vr_min":<10} {"FP_filter":<12} {"n":>5} {"days":>5} {"day_cov":>8} {"win%":>6} {"gross":>8} {"@0.3%":>8} {"@1%":>8}')
    print('  ' + '-' * 100)

    fp_filter_fn = lambda s: (
        s['hour'] not in [22, 23, 0, 1]
        and s['triggered_gain'] >= 10
        and s['bar_gain'] < 7
    )

    grid = [
        (30e6, 0, False),    # base
        (30e6, 5, False),
        (50e6, 0, False),
        (50e6, 5, False),
        (50e6, 10, False),
        (100e6, 0, False),
        (100e6, 5, False),
        (100e6, 10, False),
        (200e6, 0, False),
        (200e6, 5, False),
        (200e6, 10, False),  # 기존 strict
        # FP filter 적용
        (30e6, 0, True),
        (50e6, 0, True),
        (50e6, 5, True),
        (100e6, 0, True),
        (100e6, 5, True),
        (200e6, 0, True),
        (200e6, 10, True),  # best EV
    ]

    for tv_min, vr_min, fp in grid:
        matched = [s for s in enriched if s['tv_5'] >= tv_min and s['vr5'] >= vr_min]
        if fp:
            matched = [s for s in matched if fp_filter_fn(s)]
        if not matched:
            continue

        # 시뮬
        gross = []
        for s in matched:
            r = simulate_adaptive_trailing(coins[s['coin']], s['i'] + 1, stages_D, 5, 60)
            if r is not None:
                gross.append(r)
        if not gross:
            continue

        n = len(gross)
        wins = sum(1 for x in gross if x > 0)
        avg_g = sum(gross) / n
        avg03 = sum(apply_costs(x, 0.003) for x in gross) / n
        avg10 = sum(apply_costs(x, 0.010) for x in gross) / n
        days_with_sig = len(set(s['date'] for s in matched))
        day_cov = days_with_sig / 20  # 20일 데이터

        marker = ''
        if avg03 > 0 and day_cov >= 0.5:
            marker = ' *'
        if avg03 > 1 and day_cov >= 0.7:
            marker = ' **'
        if avg03 > 0 and day_cov >= 0.9:
            marker = ' ***'

        fp_str = 'YES' if fp else 'no'
        tv_str = f'{tv_min/1e6:.0f}M'
        print(f'  {tv_str:<10} {vr_min:<10} {fp_str:<12} {n:>5} {days_with_sig:>5} {day_cov*100:>6.0f}% {wins/n*100:>5.0f}% {avg_g:>+7.2f}% {avg03:>+7.2f}% {avg10:>+7.2f}%{marker}')

    # ===== "매일 1건 이상" 조건 만족하는 best filter =====
    print('\n=== Sweet spot: day coverage >= 90% AND EV @0.3% > 0 ===')
    best_combos = []
    for tv_min in [10e6, 30e6, 50e6, 80e6, 100e6, 150e6, 200e6]:
        for vr_min in [0, 3, 5, 10]:
            for fp in [False, True]:
                matched = [s for s in enriched if s['tv_5'] >= tv_min and s['vr5'] >= vr_min]
                if fp:
                    matched = [s for s in matched if fp_filter_fn(s)]
                if not matched:
                    continue

                gross = []
                for s in matched:
                    r = simulate_adaptive_trailing(coins[s['coin']], s['i'] + 1, stages_D, 5, 60)
                    if r is not None:
                        gross.append(r)
                if len(gross) < 10:
                    continue

                n = len(gross)
                wins = sum(1 for x in gross if x > 0)
                avg03 = sum(apply_costs(x, 0.003) for x in gross) / n
                days_with_sig = len(set(s['date'] for s in matched))
                day_cov = days_with_sig / 20

                if day_cov >= 0.7 and avg03 > 0:
                    best_combos.append({
                        'tv': tv_min, 'vr': vr_min, 'fp': fp,
                        'n': n, 'days': days_with_sig, 'day_cov': day_cov,
                        'win': wins / n, 'ev03': avg03,
                        'sig_per_day': n / 20,
                    })

    best_combos.sort(key=lambda x: -x['ev03'])
    print(f'  Found {len(best_combos)} sweet spot combos (day_cov>=70%, EV>0):')
    print(f'  {"tv":<8} {"vr":<5} {"fp":<5} {"n":>5} {"days":>5} {"sig/day":>9} {"win%":>6} {"EV@0.3%":>10}')
    for c in best_combos[:20]:
        print(f'  {c["tv"]/1e6:>5.0f}M  {c["vr"]:<4} {"YES" if c["fp"] else "no":<5} {c["n"]:>5} {c["days"]:>5} {c["sig_per_day"]:>8.1f} {c["win"]*100:>5.0f}% {c["ev03"]:>+9.2f}%')


if __name__ == '__main__':
    main()
