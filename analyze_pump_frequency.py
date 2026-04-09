"""
Phase 1: 펌프 빈도 측정.
'펌프'를 여러 임계로 정의하고 4개월(30분봉) / 2일(1분봉)에서 발생 빈도를 측정.

펌프 정의:
  - 단일 캔들: 1봉의 (high - open) / open >= threshold
  - N봉 윈도우: 임의 시작점에서 N봉 안에 (max_high - start_open) / start_open >= threshold

임계: +30%, +50%, +80%, +100%
윈도우: 1봉, 5봉, 10봉, 20봉, 30봉

빗썸 candle 형식: [timestamp_ms, open, close, high, low, volume]
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def load_candles(out_dir: str):
    """모든 코인 캔들 로드. {coin: [(ts, o, c, h, l, v), ...]}"""
    coins = {}
    for fn in os.listdir(out_dir):
        if not fn.endswith('.json'):
            continue
        coin = fn[:-5]
        with open(os.path.join(out_dir, fn)) as f:
            raw = json.load(f)
        if not raw:
            continue
        # cast
        candles = []
        for row in raw:
            try:
                ts = int(row[0])
                o = float(row[1])
                c = float(row[2])
                h = float(row[3])
                l = float(row[4])
                v = float(row[5])
                candles.append((ts, o, c, h, l, v))
            except (ValueError, IndexError):
                continue
        if candles:
            coins[coin] = candles
    return coins


def count_pumps(coins: dict, thresholds: list, windows: list):
    """
    각 (window, threshold) 조합에 대해 펌프 발생 카운트.
    Returns: dict[(window, thr)] = list of (coin, ts_kst, gain_pct)
    """
    results = defaultdict(list)

    for coin, candles in coins.items():
        n = len(candles)
        for i in range(n):
            start_ts, start_open = candles[i][0], candles[i][1]
            if start_open <= 0:
                continue
            for w in windows:
                end_idx = min(i + w, n)
                # 윈도우 안에서의 max high
                max_high = max(candles[j][3] for j in range(i, end_idx))
                gain = (max_high - start_open) / start_open * 100
                for thr in thresholds:
                    if gain >= thr:
                        ts_kst = datetime.fromtimestamp(start_ts / 1000, KST)
                        results[(w, thr)].append((coin, ts_kst, gain))
    return results


def summarize(results: dict, total_days: float, n_coins: int, label: str):
    print(f'\n{"="*70}')
    print(f'{label}  |  {n_coins} coins, {total_days:.1f} days')
    print(f'{"="*70}')
    print(f'{"window":>10} {"+30%":>12} {"+50%":>12} {"+80%":>12} {"+100%":>12}')
    print('-' * 70)
    windows = sorted({w for (w, _) in results.keys()})
    thresholds = sorted({t for (_, t) in results.keys()})
    for w in windows:
        row = f'{w:>10}봉 '
        for t in thresholds:
            cnt = len(results.get((w, t), []))
            per_day = cnt / total_days
            row += f' {cnt:>6}({per_day:>3.1f}/d)'
        print(row)


def show_top_pumps(results: dict, key: tuple, top_n: int = 20):
    items = results.get(key, [])
    items.sort(key=lambda x: -x[2])
    w, thr = key
    print(f'\nTop {top_n} pumps (window={w}봉, ≥{thr}%):')
    for coin, ts, gain in items[:top_n]:
        print(f'  {coin:>10}  {ts:%Y-%m-%d %H:%M}  +{gain:.1f}%')


def main():
    interval = sys.argv[1] if len(sys.argv) > 1 else '30m'
    out_dir = f'data/bithumb_{interval}'
    if not os.path.exists(out_dir):
        print(f'Error: {out_dir} not found')
        return

    print(f'Loading {interval} candles from {out_dir}/...')
    coins = load_candles(out_dir)
    print(f'Loaded {len(coins)} coins')

    if not coins:
        return

    # 시간 범위 (sample 코인 기준)
    sample_coin = next(iter(coins))
    sample = coins[sample_coin]
    first_ts = sample[0][0] / 1000
    last_ts = sample[-1][0] / 1000
    total_days = (last_ts - first_ts) / 86400
    print(f'Time range: {datetime.fromtimestamp(first_ts, KST)} → {datetime.fromtimestamp(last_ts, KST)}')
    print(f'Total span: {total_days:.1f} days')

    # Phase 1: 펌프 카운트
    thresholds = [30, 50, 80, 100]
    if interval == '1m':
        windows = [1, 5, 10, 30, 60]  # 1분, 5분, 10분, 30분, 60분
    else:  # 30m
        windows = [1, 2, 4, 8, 16]  # 30분, 60분, 2시간, 4시간, 8시간

    results = count_pumps(coins, thresholds, windows)
    summarize(results, total_days, len(coins), f'Bithumb {interval} pump frequency')

    # Top pumps for key thresholds
    if interval == '1m':
        show_top_pumps(results, (1, 30), top_n=15)  # 1분 +30%
        show_top_pumps(results, (10, 50), top_n=15)  # 10분 +50%
        show_top_pumps(results, (60, 80), top_n=15)  # 60분 +80%
    else:
        show_top_pumps(results, (1, 30), top_n=15)  # 30분 +30%
        show_top_pumps(results, (2, 50), top_n=15)  # 60분 +50%
        show_top_pumps(results, (4, 80), top_n=15)  # 2시간 +80%
        show_top_pumps(results, (8, 100), top_n=15)  # 4시간 +100%

    # 일별 분포 (특정 임계 기준)
    if interval == '30m':
        key = (4, 50)  # 2시간 +50%
    else:
        key = (10, 50)  # 10분 +50%

    items = results.get(key, [])
    daily = defaultdict(int)
    for _, ts, _ in items:
        daily[ts.date()] += 1
    print(f'\nDaily pump count (key={key}):')
    for day in sorted(daily.keys()):
        bar = '#' * daily[day]
        print(f'  {day}  {daily[day]:>3} {bar}')

    # 저장
    out_file = f'pump_frequency_{interval}.json'
    summary = {
        'interval': interval,
        'n_coins': len(coins),
        'total_days': total_days,
        'time_range': [
            datetime.fromtimestamp(first_ts, KST).isoformat(),
            datetime.fromtimestamp(last_ts, KST).isoformat(),
        ],
        'counts': {
            f'window={w}_thr={t}': len(items) for (w, t), items in results.items()
        },
        'per_day': {
            f'window={w}_thr={t}': round(len(items) / total_days, 2)
            for (w, t), items in results.items()
        },
    }
    with open(out_file, 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f'\nSaved {out_file}')


if __name__ == '__main__':
    main()
