"""
신호의 future outcome 분포 측정.
- 610개 신호 각각의 진입 후 30/60/120분 max_high 변화율
- "진짜 펌프"(future +20% 이상) vs false positive 분류
- 신호 강도(triggered_lb_min, triggered_gain, vol_ratio, tv 등)별 precision
- 더 strict 신호로 precision 끌어올리기
"""
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from analyze_realistic_simulation import load_candles_1m, find_adaptive_signals, apply_costs

KST = timezone(timedelta(hours=9))


def measure_outcome(candles, signal_i, hold_min):
    """signal_i부터 hold_min 동안 max gain (close 기준)"""
    if signal_i + 1 >= len(candles):
        return None
    entry = candles[signal_i + 1][1]
    if entry <= 0:
        return None
    end = min(signal_i + 1 + hold_min, len(candles))
    max_h = max(candles[j][3] for j in range(signal_i + 1, end))
    min_l = min(candles[j][4] for j in range(signal_i + 1, end))
    return {
        'entry': entry,
        'max_gain_pct': (max_h - entry) / entry * 100,
        'max_drawdown_pct': (min_l - entry) / entry * 100,
    }


def main():
    coins = load_candles_1m()
    print(f'Loaded {len(coins)} coins')

    sigs = find_adaptive_signals(coins)
    print(f'Adaptive signals: {len(sigs)}')

    # 각 신호의 future outcome (60분)
    enriched = []
    for s in sigs:
        out = measure_outcome(coins[s['coin']], s['i'], 60)
        if out is None:
            continue
        # 신호 메타 다시 계산
        candles = coins[s['coin']]
        i = s['i']
        close = candles[i][2]
        # tv_5
        tv_5 = sum(candles[j][2] * candles[j][5] for j in range(max(0, i - 5), i))
        # cumulative gain in 5/10/15/30 min
        gains = {}
        for lb in [5, 10, 15, 30]:
            if i >= lb:
                sc = candles[i - lb][2]
                if sc > 0:
                    gains[lb] = (close - sc) / sc * 100
        # vol_ratio
        past_5 = sum(candles[j][5] for j in range(max(0, i - 5), i))
        base_30 = sum(candles[j][5] for j in range(max(0, i - 35), max(0, i - 5))) / 30 if i >= 35 else 0
        vol_ratio_5 = (past_5 / 5) / base_30 if base_30 > 0 else 0

        enriched.append({
            **s,
            'future_max_gain': out['max_gain_pct'],
            'future_max_dd': out['max_drawdown_pct'],
            'tv_5min': tv_5,
            'gains': gains,
            'vol_ratio_5': vol_ratio_5,
        })

    print(f'Enriched signals: {len(enriched)}')

    # ===== Distribution of future max gain =====
    print('\n=== Future max gain distribution (60min) ===')
    fg = sorted(s['future_max_gain'] for s in enriched)
    n = len(fg)
    print(f'  p10:  {fg[n//10]:>+6.1f}%')
    print(f'  p25:  {fg[n//4]:>+6.1f}%')
    print(f'  p50:  {fg[n//2]:>+6.1f}%')
    print(f'  p75:  {fg[n*3//4]:>+6.1f}%')
    print(f'  p90:  {fg[n*9//10]:>+6.1f}%')
    print(f'  p95:  {fg[n*95//100]:>+6.1f}%')
    print(f'  max:  {fg[-1]:>+6.1f}%')

    # 진짜 펌프 비율
    for thr in [5, 10, 15, 20, 30, 50]:
        count = sum(1 for x in fg if x >= thr)
        print(f'  signal로 future +{thr}% 도달: {count}/{n} = {count/n*100:.1f}%')

    # ===== False positive vs true pump 분류 =====
    print('\n=== Classification: future +20% threshold ===')
    true_pumps = [s for s in enriched if s['future_max_gain'] >= 20]
    fps = [s for s in enriched if s['future_max_gain'] < 20]
    print(f'True pumps (future +20%): {len(true_pumps)}')
    print(f'False positives (future <+20%): {len(fps)}')

    # 두 그룹의 신호 강도 비교
    print('\n  Feature comparison (true vs FP):')
    keys = ['tv_5min', 'vol_ratio_5']
    for k in keys:
        tv = sorted(s[k] for s in true_pumps)
        fv = sorted(s[k] for s in fps)
        if not tv or not fv:
            continue
        tp50 = tv[len(tv) // 2]
        fp50 = fv[len(fv) // 2]
        tp75 = tv[len(tv) * 3 // 4]
        fp75 = fv[len(fv) * 3 // 4]
        if k == 'tv_5min':
            print(f'    {k:>15}: true_p50={tp50/1e6:>6.0f}M true_p75={tp75/1e6:>6.0f}M | fp_p50={fp50/1e6:>6.0f}M fp_p75={fp75/1e6:>6.0f}M')
        else:
            print(f'    {k:>15}: true_p50={tp50:>6.2f} true_p75={tp75:>6.2f} | fp_p50={fp50:>6.2f} fp_p75={fp75:>6.2f}')

    # 신호 lookback 분포
    print('\n  Triggered lookback distribution:')
    true_lb = Counter(s.get('triggered_lb_min') for s in true_pumps)
    fp_lb = Counter(s.get('triggered_lb_min') for s in fps)
    # NOTE: triggered_lb_min은 enriched에 안 들어 있을 수 있음, 다시 계산 필요
    # find_adaptive_signals에 추가하지 않음. 여기서는 패스.

    # ===== 더 strict 신호 시도 =====
    print('\n=== Stricter signals: tv_5min >= 100M, vol_ratio_5 >= 5x ===')
    strict_sigs = [s for s in enriched if s['tv_5min'] >= 100e6 and s['vol_ratio_5'] >= 5.0]
    print(f'  n={len(strict_sigs)}')
    if strict_sigs:
        sg = sorted(s['future_max_gain'] for s in strict_sigs)
        print(f'  median future_gain: {sg[len(sg)//2]:+.1f}%')
        print(f'  +20% rate: {sum(1 for x in sg if x >= 20)/len(sg)*100:.1f}%')
        print(f'  +50% rate: {sum(1 for x in sg if x >= 50)/len(sg)*100:.1f}%')

    print('\n=== Stricter: tv_5min >= 200M, vol_ratio_5 >= 10x ===')
    very_strict = [s for s in enriched if s['tv_5min'] >= 200e6 and s['vol_ratio_5'] >= 10.0]
    print(f'  n={len(very_strict)}')
    if very_strict:
        sg = sorted(s['future_max_gain'] for s in very_strict)
        print(f'  median future_gain: {sg[len(sg)//2]:+.1f}%')
        print(f'  +20% rate: {sum(1 for x in sg if x >= 20)/len(sg)*100:.1f}%')
        print(f'  +50% rate: {sum(1 for x in sg if x >= 50)/len(sg)*100:.1f}%')

    print('\n=== Stricter: tv_5min >= 500M ===')
    huge_tv = [s for s in enriched if s['tv_5min'] >= 500e6]
    print(f'  n={len(huge_tv)}')
    if huge_tv:
        sg = sorted(s['future_max_gain'] for s in huge_tv)
        print(f'  median future_gain: {sg[len(sg)//2]:+.1f}%')
        print(f'  +20% rate: {sum(1 for x in sg if x >= 20)/len(sg)*100:.1f}%')
        print(f'  +50% rate: {sum(1 for x in sg if x >= 50)/len(sg)*100:.1f}%')

    # ===== Strict 신호로 EV 다시 측정 =====
    print('\n=== EV with strict signals (tv>=200M, vol_ratio>=10x) ===')
    print(f'  {"strategy":<22} {"n":>5} {"win%":>7} {"avg_gross":>11} {"EV@0.3%":>10} {"EV@1%":>10}')

    from analyze_realistic_simulation import simulate_ohlc_order, simulate_reversal_exit, simulate_trailing

    if very_strict:
        strategies = [
            ('TP10/SL5/30m', 10, 5, 30),
            ('TP15/SL5/30m', 15, 5, 30),
            ('TP20/SL5/30m', 20, 5, 30),
            ('TP30/SL7/60m', 30, 7, 60),
            ('TP50/SL10/120m', 50, 10, 120),
        ]
        for name, tp, sl, hold in strategies:
            gross = []
            for s in very_strict:
                r = simulate_ohlc_order(coins[s['coin']], s['i'] + 1, tp, sl, hold)
                if r is not None:
                    gross.append(r)
            if not gross:
                continue
            n = len(gross)
            wins = sum(1 for x in gross if x > 0)
            avg_g = sum(gross) / n
            avg03 = sum(apply_costs(x, 0.003) for x in gross) / n
            avg10 = sum(apply_costs(x, 0.010) for x in gross) / n
            marker = ' ***' if avg03 > 0 else (' *' if avg_g > 0 else '')
            print(f'  {name:<22} {n:>5} {wins/n*100:>6.1f}% {avg_g:>+10.2f}% {avg03:>+9.2f}% {avg10:>+9.2f}%{marker}')

        # Trailing stops도
        print(f'\n  Trailing stops (strict signals):')
        for trail, sl, hold in [(3, 7, 60), (3, 10, 60), (5, 10, 60), (5, 10, 120)]:
            gross = []
            for s in very_strict:
                r = simulate_trailing(coins[s['coin']], s['i'] + 1, trail, sl, hold)
                if r is not None:
                    gross.append(r)
            if not gross:
                continue
            n = len(gross)
            wins = sum(1 for x in gross if x > 0)
            avg_g = sum(gross) / n
            avg03 = sum(apply_costs(x, 0.003) for x in gross) / n
            marker = ' ***' if avg03 > 0 else (' *' if avg_g > 0 else '')
            print(f'  trail{trail}/SL{sl}/{hold}m{"":<5} {n:>5} {wins/n*100:>6.1f}% {avg_g:>+10.2f}% {avg03:>+9.2f}%{marker}')


if __name__ == '__main__':
    main()
