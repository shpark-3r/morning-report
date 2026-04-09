"""
신호 강도(vol_trend, log_tv)별로 EV가 어떻게 변하는지 측정.
강한 신호일수록 EV가 양수로 가는지 확인.
"""
import json
import os
import math
from analyze_exit_strategies import (
    load_candles, simulate_exit, apply_costs, SLIPPAGE, FEE
)
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def find_signals_layered(coins, lookback_bars=144):
    """모든 매크로 후보 신호를 vol_trend 강도와 함께 반환"""
    signals = []
    for coin, candles in coins.items():
        n = len(candles)
        for i in range(lookback_bars + 10, n - 10):
            window = candles[i - lookback_bars:i]
            closes = [x[2] for x in window]
            vols = [x[5] for x in window]
            tvs = [x[2] * x[5] for x in window]

            if not closes or sum(closes) == 0:
                continue
            sum_tv = sum(tvs)
            if sum_tv <= 0:
                continue
            log_tv = math.log10(sum_tv)
            if log_tv < 9:  # 1천만 KRW 미만 누적이면 너무 작음
                continue

            half = lookback_bars // 2
            vol_first = sum(vols[:half]) / half
            vol_second = sum(vols[half:]) / (lookback_bars - half)
            if vol_first <= 0:
                continue
            vol_trend = vol_second / vol_first
            if vol_trend < 2.0:  # 더 넓은 후보
                continue

            max_bar = 0
            for x in window:
                if x[1] > 0:
                    r = (x[3] - x[4]) / x[1]
                    if r > max_bar:
                        max_bar = r

            signals.append({
                'coin': coin,
                'i': i,
                'ts': candles[i][0],
                'vol_trend': vol_trend,
                'log_tv': log_tv,
                'max_bar': max_bar,
            })
    return signals


def main():
    coins = load_candles('data/bithumb_30m')
    print(f'Loaded {len(coins)} coins')

    print('Finding layered signals...')
    signals = find_signals_layered(coins, lookback_bars=144)
    print(f'Total raw signals: {len(signals)}')

    # Dedupe per coin (24h cluster = 48 bars)
    signals.sort(key=lambda s: (s['coin'], s['i']))
    deduped = []
    last_coin = None
    last_i = -10000
    for s in signals:
        if s['coin'] != last_coin or s['i'] - last_i >= 48:
            deduped.append(s)
            last_coin = s['coin']
            last_i = s['i']
    print(f'After dedupe (24h cluster): {len(deduped)} signals')

    # Layering: vol_trend × log_tv 그리드별 EV
    vol_buckets = [(2, 5), (5, 10), (10, 20), (20, 50), (50, 100), (100, 1e9)]
    log_tv_buckets = [(9, 10), (10, 11), (11, 12), (12, 1e9)]

    # Best strategy from previous: TP10/SL3/4h
    print(f'\n=== EV by layered signal strength (TP10/SL3/4h, dedupe 24h) ===')
    print(f'{"vol_trend":<15} {"log_tv":<12} {"n":>5} {"win%":>7} {"avg_net":>10} {"med_net":>10}')
    print('-' * 70)

    for vlo, vhi in vol_buckets:
        for tlo, thi in log_tv_buckets:
            bucket = [s for s in deduped if vlo <= s['vol_trend'] < vhi and tlo <= s['log_tv'] < thi]
            if len(bucket) < 5:
                continue
            net_pcts = []
            for s in bucket:
                r = simulate_exit(coins[s['coin']], s['i'], 10, 3, 8)
                if r is not None:
                    net_pcts.append(apply_costs(r))
            if not net_pcts:
                continue
            n = len(net_pcts)
            wins = sum(1 for x in net_pcts if x > 0)
            avg = sum(net_pcts) / n
            med = sorted(net_pcts)[n // 2]
            print(f'  {vlo}-{vhi}{"":<10} {tlo}-{thi}{"":<6} {n:>5} {wins/n*100:>6.1f}% {avg:>+9.2f}% {med:>+9.2f}%')

    # 다양한 TP/SL 조합 × 강한 신호만
    print(f'\n=== Strong signals only (vol_trend>=20x, log_tv>=10) ===')
    strong = [s for s in deduped if s['vol_trend'] >= 20 and s['log_tv'] >= 10]
    print(f'  n={len(strong)}')
    if strong:
        strategies = [
            ('TP5/SL2/2h', 5, 2, 4),
            ('TP10/SL2/2h', 10, 2, 4),
            ('TP10/SL3/4h', 10, 3, 8),
            ('TP15/SL3/4h', 15, 3, 8),
            ('TP20/SL3/4h', 20, 3, 8),
            ('TP30/SL5/4h', 30, 5, 8),
            ('TP50/SL5/4h', 50, 5, 8),
            ('TP100/SL5/8h', 100, 5, 16),
            ('TP10/SL3/8h', 10, 3, 16),
            ('TP20/SL5/8h', 20, 5, 16),
        ]
        print(f'  {"strategy":<18} {"win%":>7} {"avg_net":>10} {"med":>10}')
        for name, tp, sl, hold in strategies:
            net_pcts = []
            for s in strong:
                r = simulate_exit(coins[s['coin']], s['i'], tp, sl, hold)
                if r is not None:
                    net_pcts.append(apply_costs(r))
            if not net_pcts:
                continue
            n = len(net_pcts)
            wins = sum(1 for x in net_pcts if x > 0)
            avg = sum(net_pcts) / n
            med = sorted(net_pcts)[n // 2]
            print(f'  {name:<18} {wins/n*100:>6.1f}% {avg:>+9.2f}% {med:>+9.2f}%')

    # 매우 강한 신호 (vol_trend >= 50, log_tv >= 11)
    print(f'\n=== Very strong signals (vol_trend>=50x, log_tv>=11) ===')
    very_strong = [s for s in deduped if s['vol_trend'] >= 50 and s['log_tv'] >= 11]
    print(f'  n={len(very_strong)}')
    for s in very_strong[:30]:
        ts = datetime.fromtimestamp(s['ts'] / 1000, KST)
        print(f'    {s["coin"]:>10} {ts:%m-%d %H:%M} vol_trend={s["vol_trend"]:>6.1f}x log_tv={s["log_tv"]:.2f}')

    if very_strong:
        for tp, sl, hold in [(10, 3, 8), (20, 3, 8), (30, 5, 8), (50, 5, 16)]:
            net_pcts = []
            for s in very_strong:
                r = simulate_exit(coins[s['coin']], s['i'], tp, sl, hold)
                if r is not None:
                    net_pcts.append(apply_costs(r))
            if net_pcts:
                avg = sum(net_pcts) / len(net_pcts)
                wins = sum(1 for x in net_pcts if x > 0) / len(net_pcts)
                print(f'  TP{tp}/SL{sl}/{hold//2}h: n={len(net_pcts)} win={wins*100:.1f}% avg={avg:+.2f}%')


if __name__ == '__main__':
    main()
