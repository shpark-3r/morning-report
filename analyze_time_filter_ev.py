"""
시간대/요일/lag 필터를 적용한 EV 측정.

기준 신호: vol_mult >= 100, 양봉, tv >= 10M (이전과 동일, 보수 가정 유지)
출구: TP+10/SL-3/4h
비용: 슬리피지 0.6% + 수수료 0.08% = 0.68% per round trip
SL 우선 (보수)
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from analyze_vol_burst_replicate import (
    load_candles, find_burst_signals, simulate, apply_costs
)

KST = timezone(timedelta(hours=9))


def main():
    coins = load_candles('data/bithumb_30m')
    print(f'Loaded {len(coins)} coins')

    # 신호 후보들
    print('Finding signals (vol_mult>=100, 양봉, tv>=10M)...')
    sigs = find_burst_signals(coins, vol_mult=100, min_tv_krw=10e6)
    sigs.sort(key=lambda s: (s['coin'], s['i']))
    deduped = []
    last_coin, last_i = None, -1000
    for s in sigs:
        if s['coin'] != last_coin or s['i'] - last_i >= 8:
            deduped.append(s)
            last_coin, last_i = s['coin'], s['i']
    print(f'Total deduped signals: {len(deduped)}')

    # 각 신호의 시뮬 결과 계산 (한 번만)
    rows = []
    for s in deduped:
        gross = simulate(coins[s['coin']], s['i'], 10, 3, 8)
        if gross is None:
            continue
        net = apply_costs(gross)
        dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
        rows.append({**s, 'gross': gross, 'net': net, 'hour': dt.hour, 'dow': dt.weekday(), 'date': dt.date()})

    print(f'Valid rows: {len(rows)}')

    # ========== 1. Hour filter ==========
    print(f'\n=== EV by hour (KST) ===')
    print(f'{"hour":>6} {"n":>6} {"win%":>7} {"avg_net":>10}  bar')
    by_hour = defaultdict(list)
    for r in rows:
        by_hour[r['hour']].append(r['net'])
    for h in range(24):
        v = by_hour[h]
        if not v:
            print(f'  {h:02d}시 {0:>6} {"--":>7} {"--":>10}')
            continue
        n = len(v)
        wins = sum(1 for x in v if x > 0)
        avg = sum(v) / n
        bar = '+' if avg > 0 else '-'
        bar_len = int(abs(avg) * 5)
        print(f'  {h:02d}시 {n:>6} {wins/n*100:>6.1f}% {avg:>+9.2f}%  {bar * min(bar_len, 30)}')

    # ========== 2. DOW filter ==========
    print(f'\n=== EV by day-of-week ===')
    dow_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    by_dow = defaultdict(list)
    for r in rows:
        by_dow[r['dow']].append(r['net'])
    for d in range(7):
        v = by_dow[d]
        if not v:
            continue
        n = len(v)
        wins = sum(1 for x in v if x > 0)
        avg = sum(v) / n
        print(f'  {dow_names[d]:>6} {n:>6} {wins/n*100:>6.1f}% {avg:>+9.2f}%')

    # ========== 3. Hour × DOW combined ==========
    print(f'\n=== Hour × DOW (top filters by EV, n>=10) ===')
    by_hd = defaultdict(list)
    for r in rows:
        by_hd[(r['hour'], r['dow'])].append(r['net'])
    rows_hd = []
    for (h, d), v in by_hd.items():
        if len(v) >= 10:
            avg = sum(v) / len(v)
            wins = sum(1 for x in v if x > 0)
            rows_hd.append((h, d, len(v), wins / len(v), avg))
    rows_hd.sort(key=lambda x: -x[4])
    print(f'  {"hour":>6} {"dow":>5} {"n":>5} {"win%":>7} {"avg_net":>10}')
    for h, d, n, wp, avg in rows_hd[:15]:
        print(f'  {h:02d}시 {dow_names[d]:>5} {n:>5} {wp*100:>6.1f}% {avg:>+9.2f}%')

    # ========== 4. 시간 윈도우 필터 (예: 22~01시만 진입) ==========
    print(f'\n=== Time window filters ===')
    windows = [
        ('all', range(24)),
        ('22-02시 (밤)', [22, 23, 0, 1]),
        ('19-23시 (저녁)', [19, 20, 21, 22, 23]),
        ('15-21시 (오후-저녁)', [15, 16, 17, 18, 19, 20, 21]),
        ('00-09시 (새벽)', list(range(0, 10))),
        ('08-15시 (낮)', list(range(8, 16))),
        ('23시만', [23]),
    ]
    for label, hours in windows:
        v = [r['net'] for r in rows if r['hour'] in hours]
        if not v:
            continue
        n = len(v)
        wins = sum(1 for x in v if x > 0)
        avg = sum(v) / n
        print(f'  {label:<25} n={n:>5} win={wins/n*100:>5.1f}% avg={avg:>+6.2f}%')

    # 평일+밤
    weekday_night = [r['net'] for r in rows if r['dow'] < 5 and r['hour'] in [22, 23, 0, 1]]
    if weekday_night:
        n = len(weekday_night)
        wins = sum(1 for x in weekday_night if x > 0)
        avg = sum(weekday_night) / n
        print(f'  {"평일+밤 22-01시":<25} n={n:>5} win={wins/n*100:>5.1f}% avg={avg:>+6.2f}%')

    # ========== 5. lag 진입 ==========
    print(f'\n=== Lag entry: 신호 후 N봉(30m) 지연 진입 ===')
    print(f'  {"lag":<6} {"n":>5} {"win%":>7} {"avg_net":>10}')
    for lag in [0, 1, 2, 3, 4]:
        nets = []
        for s in deduped:
            entry_i = s['i'] + lag  # lag봉 지연
            gross = simulate(coins[s['coin']], entry_i, 10, 3, 8)
            if gross is not None:
                nets.append(apply_costs(gross))
        if nets:
            n = len(nets)
            wins = sum(1 for x in nets if x > 0)
            avg = sum(nets) / n
            print(f'  +{lag}봉 {n:>5} {wins/n*100:>6.1f}% {avg:>+9.2f}%')


if __name__ == '__main__':
    main()
