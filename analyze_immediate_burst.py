"""
Immediate burst signal detection.

기존 (backward): 직전 5분 누적 vol/tv가 baseline 대비 큼
새 (immediate): 현재 봉 자체가 vol burst + 양봉

정의:
  signal at i if:
    - candle[i] vol >= base_vol_30 * X (e.g. 10x)
    - candle[i] is up bar (close > open)
    - candle[i] gain >= Y% (e.g. 3%)
    - candle[i] tv >= Z (e.g. 50M)

이게 ENJ 00:15, 00:16 같은 가속 시작점을 잡는가?
"""
import json
import os
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta
from analyze_realistic_simulation import load_candles_1m, apply_costs
from analyze_adaptive_trailing import simulate_adaptive_trailing

KST = timezone(timedelta(hours=9))


def find_immediate_burst(coins, vol_x=10, min_gain=3, min_tv=50e6, baseline=30, dedupe=10):
    """Immediate burst signals — 봉 자체의 vol burst + 양봉"""
    signals = []
    for coin, candles in coins.items():
        n = len(candles)
        last = -1000
        for i in range(baseline + 5, n - 30):
            if i - last < dedupe:
                continue
            ts, o, c, h, l, v = candles[i]
            if c <= o or v <= 0 or o <= 0:
                continue
            gain = (c - o) / o * 100
            if gain < min_gain:
                continue
            tv = c * v
            if tv < min_tv:
                continue
            base_vol = sum(candles[j][5] for j in range(max(0, i - baseline), i)) / baseline
            if base_vol <= 0:
                continue
            ratio = v / base_vol
            if ratio < vol_x:
                continue
            signals.append({
                'coin': coin, 'i': i, 'ts': ts,
                'vol_x': ratio, 'tv': tv, 'gain': gain,
            })
            last = i
    return signals


def main():
    coins = load_candles_1m()
    print(f'Loaded {len(coins)} coins')

    # 다양한 임계 시도
    print('\n=== Immediate burst detection grid ===')
    print(f'  {"vol_x":<6} {"min_gain":<10} {"min_tv":<8} {"n":>5} {"days":>5} {"sig/day":>9} {"win%":>6} {"gross":>8} {"@0.3%":>8}')

    stages_D = [(5, 4, 2), (10, 3, 6), (20, 2, 15), (35, 1.5, 28)]

    grid = [
        (5, 2, 30e6),
        (5, 3, 30e6),
        (5, 5, 30e6),
        (10, 3, 30e6),
        (10, 5, 30e6),
        (10, 3, 50e6),
        (10, 5, 50e6),
        (10, 3, 100e6),
        (10, 5, 100e6),
        (15, 3, 50e6),
        (15, 5, 50e6),
        (15, 5, 100e6),
        (20, 5, 50e6),
        (20, 5, 100e6),
        (30, 5, 50e6),
        (30, 5, 100e6),
        (30, 7, 100e6),
        (50, 5, 100e6),
        (50, 7, 100e6),
    ]

    for vol_x, min_gain, min_tv in grid:
        sigs = find_immediate_burst(coins, vol_x=vol_x, min_gain=min_gain, min_tv=min_tv)
        if not sigs:
            continue

        # 시뮬
        gross = []
        days = set()
        for s in sigs:
            r = simulate_adaptive_trailing(coins[s['coin']], s['i'] + 1, stages_D, 5, 60)
            if r is not None:
                gross.append(r)
                dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
                days.add(dt.date())
        if not gross:
            continue
        n = len(gross)
        wins = sum(1 for x in gross if x > 0)
        avg_g = sum(gross) / n
        avg03 = sum(apply_costs(x, 0.003) for x in gross) / n
        marker = ''
        if avg03 > 0 and len(days) >= 15:
            marker = ' *'
        if avg03 > 1 and len(days) >= 15:
            marker = ' **'
        print(f'  {vol_x:<6} {min_gain:<10} {min_tv/1e6:<6.0f}M {n:>5} {len(days):>5} {n/30:>8.1f} {wins/n*100:>5.0f}% {avg_g:>+7.2f}% {avg03:>+7.2f}%{marker}')

    # 사용자 사례 검증 (10x, 3%, 50M)
    print('\n=== User case detection: vol_x=10, gain>=3%, tv>=50M ===')
    sigs = find_immediate_burst(coins, vol_x=10, min_gain=3, min_tv=50e6)
    print(f'Total: {len(sigs)}')

    target_pumps = [
        ('ENJ', '2026-04-09', 0),  # 00시 펌프
        ('ENJ', '2026-04-09', 11),
        ('JOE', '2026-04-08', 6),
        ('XION', '2026-04-07', 14),
        ('XYO', '2026-03-31', 18),
    ]
    for coin, date, hour in target_pumps:
        matched = []
        for s in sigs:
            if s['coin'] != coin:
                continue
            dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
            if dt.strftime('%Y-%m-%d') == date and dt.hour == hour:
                matched.append((s, dt))
        if matched:
            print(f'  {coin} {date} {hour}시: {len(matched)} signals')
            for s, dt in matched[:3]:
                r = simulate_adaptive_trailing(coins[s['coin']], s['i'] + 1, stages_D, 5, 60)
                print(f'    {dt:%H:%M} vol_x={s["vol_x"]:.0f}x gain={s["gain"]:+.1f}% tv={s["tv"]/1e6:.0f}M → exit {r:+.2f}%')
        else:
            print(f'  {coin} {date} {hour}시: NOT FOUND')

    # 매일 신호 분포
    print('\n=== Daily signal distribution (vol_x=10, gain>=3%, tv>=50M) ===')
    daily = defaultdict(int)
    for s in sigs:
        dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
        daily[dt.date()] += 1
    for d in sorted(daily.keys()):
        print(f'  {d}: {daily[d]}')


if __name__ == '__main__':
    main()
