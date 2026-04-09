"""
1. 사용자 사례 D vs A 비교 (큰 winner 잡기)
2. 신호 강도별 분기 전략 (vol_ratio 큰 신호는 A, 작은 신호는 D)
3. Train/test 분할 (cherry pick 검증)
4. Bootstrap 95% CI (통계적 신뢰성)
"""
import json
import os
import random
from datetime import datetime, timezone, timedelta
from analyze_adaptive_trailing import simulate_adaptive_trailing
from analyze_realistic_simulation import load_candles_1m, find_adaptive_signals, apply_costs

KST = timezone(timedelta(hours=9))
random.seed(42)


def enrich(coins, s):
    candles = coins[s['coin']]
    i = s['i']
    if i < 35:
        return None
    tv_5 = sum(candles[j][2] * candles[j][5] for j in range(i - 5, i))
    past_5 = sum(candles[j][5] for j in range(i - 5, i))
    base_30 = sum(candles[j][5] for j in range(i - 35, i - 5)) / 30
    vr = (past_5 / 5) / base_30 if base_30 > 0 else 0
    o, c, h = candles[i][1], candles[i][2], candles[i][3]
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
    return {**s, 'tv_5': tv_5, 'vr5': vr, 'bar_gain': bar_gain, 'triggered_gain': triggered_gain, 'dt': dt, 'hour': dt.hour}


def main():
    coins = load_candles_1m()
    sigs = find_adaptive_signals(coins)
    enriched = [e for e in (enrich(coins, s) for s in sigs) if e]

    # Strict + FP filter set
    strict_filtered = [s for s in enriched if (
        s['tv_5'] >= 200e6 and s['vr5'] >= 10
        and s['hour'] not in [22, 23, 0, 1]
        and s['triggered_gain'] >= 10
        and s['bar_gain'] < 7
    )]
    print(f'Strict+FP filter signals: {len(strict_filtered)}')

    # Strategies
    stages_D = [(5, 4, 2), (10, 3, 6), (20, 2, 15), (35, 1.5, 28)]
    stages_A = [(5, 5, 1), (15, 3, 10), (30, 2, 20), (50, 1.5, 35)]
    stages_F = [(7, 7, 0), (15, 5, 5), (30, 3, 15), (50, 2, 30), (100, 1.5, 60)]  # 새 시도: 큰 winner 노림
    stages_G = [(10, 7, 0), (25, 5, 5), (50, 3, 25), (100, 2, 50)]  # G: 더 wide

    strategies = [
        ('D', stages_D, 5, 60),
        ('A', stages_A, 5, 60),
        ('F (new wide)', stages_F, 7, 120),
        ('G (very wide)', stages_G, 10, 180),
    ]

    # ===== 1. 사용자 사례 비교 =====
    print('\n=== USER cases (D vs A vs F vs G) ===')
    print(f'  {"coin":>10} {"date_time":<15}', *[f'{name:>15}' for name, _, _, _ in strategies])
    print('  ' + '-' * 90)

    target_pumps = [
        ('ENJ', '2026-04-09', 11),
        ('JOE', '2026-04-08', 6),
        ('XION', '2026-04-07', 14),
        ('XYO', '2026-03-31', 18),
    ]

    for coin, date, hour in target_pumps:
        # find signal
        match = None
        for s in enriched:
            if s['coin'] == coin and s['dt'].strftime('%Y-%m-%d') == date and s['dt'].hour == hour:
                match = s
                break
        if not match:
            print(f'  {coin:>10} {date} {hour}시: NOT FOUND')
            continue
        results = []
        for name, stages, sl, hold in strategies:
            r = simulate_adaptive_trailing(coins[match['coin']], match['i'] + 1, stages, sl, hold)
            results.append(f'{r:>+13.2f}%' if r is not None else '         n/a ')
        print(f'  {coin:>10} {match["dt"]:%m-%d %H:%M}', ' '.join(f'{r:>15}' for r in results))

    # ===== 2. 31개 strict 신호 전체 비교 =====
    print('\n=== All 31 strict signals: D vs A vs F vs G ===')
    strict = [s for s in enriched if s['tv_5'] >= 200e6 and s['vr5'] >= 10]
    for name, stages, sl, hold in strategies:
        gross = []
        for s in strict:
            r = simulate_adaptive_trailing(coins[s['coin']], s['i'] + 1, stages, sl, hold)
            if r is not None:
                gross.append(r)
        if not gross:
            continue
        n = len(gross)
        wins = sum(1 for x in gross if x > 0)
        avg_g = sum(gross) / n
        avg03 = sum(apply_costs(x, 0.003) for x in gross) / n
        avg10 = sum(apply_costs(x, 0.010) for x in gross) / n
        max_w = max(gross)
        print(f'  {name:<15} n={n} win={wins/n*100:>5.1f}% gross={avg_g:>+6.2f}% @0.3%={avg03:>+6.2f}% @1%={avg10:>+6.2f}% max_winner={max_w:>+6.2f}%')

    # ===== 3. Strict + FP filter set 비교 =====
    print(f'\n=== Strict + FP filter (n={len(strict_filtered)}): D vs A vs F vs G ===')
    for name, stages, sl, hold in strategies:
        gross = []
        for s in strict_filtered:
            r = simulate_adaptive_trailing(coins[s['coin']], s['i'] + 1, stages, sl, hold)
            if r is not None:
                gross.append(r)
        if not gross:
            continue
        n = len(gross)
        wins = sum(1 for x in gross if x > 0)
        avg_g = sum(gross) / n
        avg03 = sum(apply_costs(x, 0.003) for x in gross) / n
        max_w = max(gross)
        print(f'  {name:<15} n={n} win={wins/n*100:>5.1f}% gross={avg_g:>+6.2f}% @0.3%={avg03:>+6.2f}% max_winner={max_w:>+6.2f}%')

    # ===== 4. 신호 강도별 분기 전략 =====
    print('\n=== Branch strategy: vol_ratio < 50x → D, >= 50x → A (or F) ===')
    for D_lbl, D_stages, D_sl, D_hold in [('D', stages_D, 5, 60)]:
        for high_lbl, high_stages, high_sl, high_hold in [('A', stages_A, 5, 60), ('F', stages_F, 7, 120), ('G', stages_G, 10, 180)]:
            gross = []
            for s in strict:
                if s['vr5'] < 50:
                    r = simulate_adaptive_trailing(coins[s['coin']], s['i'] + 1, D_stages, D_sl, D_hold)
                else:
                    r = simulate_adaptive_trailing(coins[s['coin']], s['i'] + 1, high_stages, high_sl, high_hold)
                if r is not None:
                    gross.append(r)
            if not gross:
                continue
            n = len(gross)
            wins = sum(1 for x in gross if x > 0)
            avg_g = sum(gross) / n
            avg03 = sum(apply_costs(x, 0.003) for x in gross) / n
            print(f'  vr<50:{D_lbl} vr>=50:{high_lbl}: n={n} win={wins/n*100:>5.1f}% gross={avg_g:>+6.2f}% @0.3%={avg03:>+6.2f}%')

    # ===== 5. Train/test 분할 (3월 vs 4월) =====
    print('\n=== Train/test split (March vs April) ===')
    for name, stages, sl, hold in strategies:
        train = [s for s in strict if s['dt'].month == 3]
        test = [s for s in strict if s['dt'].month == 4]
        train_gross = [simulate_adaptive_trailing(coins[s['coin']], s['i'] + 1, stages, sl, hold) for s in train]
        train_gross = [x for x in train_gross if x is not None]
        test_gross = [simulate_adaptive_trailing(coins[s['coin']], s['i'] + 1, stages, sl, hold) for s in test]
        test_gross = [x for x in test_gross if x is not None]
        if not train_gross or not test_gross:
            continue
        train_avg = sum(apply_costs(x, 0.003) for x in train_gross) / len(train_gross)
        test_avg = sum(apply_costs(x, 0.003) for x in test_gross) / len(test_gross)
        train_w = sum(1 for x in train_gross if x > 0) / len(train_gross)
        test_w = sum(1 for x in test_gross if x > 0) / len(test_gross)
        print(f'  {name:<15} train(3월) n={len(train_gross)} win={train_w*100:.0f}% EV={train_avg:+.2f}% | test(4월) n={len(test_gross)} win={test_w*100:.0f}% EV={test_avg:+.2f}%')

    # ===== 6. Bootstrap 95% CI =====
    print('\n=== Bootstrap 95% CI (D strategy on strict + FP filter) ===')
    if strict_filtered:
        gross_all = []
        for s in strict_filtered:
            r = simulate_adaptive_trailing(coins[s['coin']], s['i'] + 1, stages_D, 5, 60)
            if r is not None:
                gross_all.append(apply_costs(r, 0.003))
        n = len(gross_all)
        if n > 0:
            point_est = sum(gross_all) / n
            # 1000 bootstrap samples
            boot_means = []
            for _ in range(1000):
                sample = [random.choice(gross_all) for _ in range(n)]
                boot_means.append(sum(sample) / n)
            boot_means.sort()
            lo = boot_means[25]
            hi = boot_means[975]
            print(f'  n={n} point estimate: {point_est:+.2f}%')
            print(f'  Bootstrap 95% CI: [{lo:+.2f}%, {hi:+.2f}%]')
            print(f'  P(EV > 0) ≈ {sum(1 for x in boot_means if x > 0) / 10:.1f}%')

    # 같은 검증을 strict (n=31)에도
    print('\n=== Bootstrap 95% CI (D strategy on strict only) ===')
    gross_all = []
    for s in strict:
        r = simulate_adaptive_trailing(coins[s['coin']], s['i'] + 1, stages_D, 5, 60)
        if r is not None:
            gross_all.append(apply_costs(r, 0.003))
    n = len(gross_all)
    if n > 0:
        point_est = sum(gross_all) / n
        boot_means = []
        for _ in range(1000):
            sample = [random.choice(gross_all) for _ in range(n)]
            boot_means.append(sum(sample) / n)
        boot_means.sort()
        lo = boot_means[25]
        hi = boot_means[975]
        print(f'  n={n} point estimate: {point_est:+.2f}%')
        print(f'  Bootstrap 95% CI: [{lo:+.2f}%, {hi:+.2f}%]')
        print(f'  P(EV > 0) ≈ {sum(1 for x in boot_means if x > 0) / 10:.1f}%')


if __name__ == '__main__':
    main()
