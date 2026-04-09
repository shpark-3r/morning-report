"""
Phase 3: 시간대별 펌프 분포 분석.

질문:
1. 시간대별(0~23시 KST) 펌프 발생 빈도
2. 요일별 펌프 분포
3. "작전 시즌"의 패턴 (3월 말 폭발의 시간대 분포)
4. 평소(noise) vs 시즌(spike) 분리
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def load_candles(out_dir: str):
    coins = {}
    for fn in os.listdir(out_dir):
        if not fn.endswith('.json'):
            continue
        coin = fn[:-5]
        with open(os.path.join(out_dir, fn)) as f:
            raw = json.load(f)
        if not raw:
            continue
        candles = []
        for row in raw:
            try:
                ts = int(row[0])
                o, c, h, l, v = float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
                candles.append((ts, o, c, h, l, v))
            except (ValueError, IndexError):
                continue
        if candles:
            coins[coin] = candles
    return coins


def find_pumps_dedupe(candles, window, threshold, dedupe_min=120):
    """펌프 시작점만 (dedupe). returns list of (ts_ms, gain)"""
    pumps = []
    last_i = -10000
    n = len(candles)
    for i in range(n - window):
        c = candles[i][2]
        if c <= 0:
            continue
        future_max = max(candles[j][3] for j in range(i + 1, i + 1 + window))
        gain = (future_max - c) / c * 100
        if gain >= threshold and i - last_i >= dedupe_min // (1 if window == 1 else window):
            pumps.append((candles[i][0], gain, candles[i][2]))
            last_i = i
    return pumps


def find_pumps_30m(candles, window_bars, threshold, dedupe_bars=8):
    """30분봉용. window_bars=2 → 1시간 윈도우"""
    pumps = []
    last_i = -10000
    n = len(candles)
    for i in range(n - window_bars):
        c = candles[i][2]
        if c <= 0:
            continue
        future_max = max(candles[j][3] for j in range(i + 1, i + 1 + window_bars))
        gain = (future_max - c) / c * 100
        if gain >= threshold and i - last_i >= dedupe_bars:
            pumps.append((candles[i][0], gain, c))
            last_i = i
    return pumps


def main():
    print('=' * 80)
    print('Time distribution analysis: 30m candles (4개월 데이터)')
    print('=' * 80)

    coins_30m = load_candles('data/bithumb_30m')
    print(f'Loaded {len(coins_30m)} coins (30m)')

    # 30분봉으로 펌프 시작점 (1시간 내 +50%)
    all_pumps = []  # (ts_ms, coin, gain)
    for coin, candles in coins_30m.items():
        pumps = find_pumps_30m(candles, window_bars=2, threshold=50, dedupe_bars=8)
        for ts, gain, _ in pumps:
            all_pumps.append((ts, coin, gain))

    print(f'Total pump starts (1h +50%, deduped 4h): {len(all_pumps)}')

    if not all_pumps:
        return

    # 시간대 분포 (KST 시 단위)
    hour_count = defaultdict(int)
    for ts, _, _ in all_pumps:
        dt = datetime.fromtimestamp(ts / 1000, KST)
        hour_count[dt.hour] += 1

    total = sum(hour_count.values())
    print(f'\n[Hour distribution] Total {total} pumps')
    print(f'{"hour":>6} {"count":>8} {"pct":>8}  bar')
    for h in range(24):
        n = hour_count[h]
        pct = n / total * 100
        bar = '#' * int(pct * 2)
        print(f'  {h:02d}시 {n:>6} {pct:>6.1f}% {bar}')

    # 요일 분포 (월=0)
    dow_count = defaultdict(int)
    dow_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    for ts, _, _ in all_pumps:
        dt = datetime.fromtimestamp(ts / 1000, KST)
        dow_count[dt.weekday()] += 1
    print(f'\n[Day-of-week distribution]')
    for d in range(7):
        n = dow_count[d]
        pct = n / total * 100
        bar = '#' * int(pct)
        print(f'  {dow_names[d]:>6} {n:>6} {pct:>6.1f}% {bar}')

    # 시즌 분리: 일별 펌프 카운트로 boom/normal day 구분
    daily_count = defaultdict(int)
    for ts, _, _ in all_pumps:
        dt = datetime.fromtimestamp(ts / 1000, KST)
        daily_count[dt.date()] += 1

    daily_sorted = sorted(daily_count.items())
    counts = sorted(daily_count.values(), reverse=True)
    if counts:
        median = counts[len(counts) // 2]
        p90 = counts[len(counts) // 10] if len(counts) >= 10 else counts[0]
        p10 = counts[len(counts) * 9 // 10] if len(counts) >= 10 else counts[-1]
        print(f'\n[Daily pump count stats]')
        print(f'  median={median}, p10={p10}, p90={p90}, max={counts[0]}, min={counts[-1]}')
        print(f'  total days={len(counts)}, total pumps={sum(counts)}')

        # boom day = top 10%
        boom_threshold = p90
        boom_days = [d for d, c in daily_count.items() if c >= boom_threshold]
        normal_days = [d for d, c in daily_count.items() if c < boom_threshold]
        boom_total = sum(c for d, c in daily_count.items() if c >= boom_threshold)
        normal_total = sum(c for d, c in daily_count.items() if c < boom_threshold)
        print(f'\n[Boom vs Normal]')
        print(f'  Boom days (count>={boom_threshold}): {len(boom_days)}, total {boom_total} pumps ({boom_total/total*100:.1f}%)')
        print(f'  Normal days: {len(normal_days)}, total {normal_total} pumps ({normal_total/total*100:.1f}%)')
        print(f'  Boom day avg: {boom_total/len(boom_days):.1f}/day')
        print(f'  Normal day avg: {normal_total/len(normal_days):.1f}/day')

        # boom day 시간대 vs normal day 시간대 비교
        boom_hours = defaultdict(int)
        normal_hours = defaultdict(int)
        for ts, _, _ in all_pumps:
            dt = datetime.fromtimestamp(ts / 1000, KST)
            if dt.date() in set(boom_days):
                boom_hours[dt.hour] += 1
            else:
                normal_hours[dt.hour] += 1

        print(f'\n[Hour distribution: BOOM days vs NORMAL days]')
        print(f'{"hour":>6} {"boom":>8} {"normal":>8}  boom%   normal%')
        for h in range(24):
            b = boom_hours[h]
            nm = normal_hours[h]
            bp = b / boom_total * 100 if boom_total else 0
            np_pct = nm / normal_total * 100 if normal_total else 0
            print(f'  {h:02d}시 {b:>6}  {nm:>6}  {bp:>6.1f}%  {np_pct:>6.1f}%')

    # ----- 1m 데이터로도 시간대 검증 -----
    print(f'\n{"=" * 80}')
    print('1m candles (7일치)')
    print('=' * 80)
    coins_1m = load_candles('data/bithumb_1m')
    print(f'Loaded {len(coins_1m)} coins (1m)')

    all_pumps_1m = []
    for coin, candles in coins_1m.items():
        pumps = find_pumps_dedupe(candles, window=30, threshold=50, dedupe_min=60)
        for ts, gain, _ in pumps:
            all_pumps_1m.append((ts, coin, gain))

    if all_pumps_1m:
        hour_count_1m = defaultdict(int)
        for ts, _, _ in all_pumps_1m:
            dt = datetime.fromtimestamp(ts / 1000, KST)
            hour_count_1m[dt.hour] += 1
        total_1m = len(all_pumps_1m)
        print(f'\n[1m hour distribution: 30min +50%, deduped] Total {total_1m}')
        for h in range(24):
            n = hour_count_1m[h]
            pct = n / total_1m * 100 if total_1m else 0
            bar = '#' * int(pct * 2)
            print(f'  {h:02d}시 {n:>5} {pct:>6.1f}% {bar}')

    # 저장
    out = {
        'total_pumps_30m': total,
        'hour_distribution_30m': dict(hour_count),
        'dow_distribution_30m': dict(dow_count),
        'daily_distribution_30m': {str(d): c for d, c in daily_sorted},
    }
    with open('pump_time_distribution.json', 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print('\nSaved pump_time_distribution.json')


if __name__ == '__main__':
    main()
