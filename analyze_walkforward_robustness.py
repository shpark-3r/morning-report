"""
Walk-forward 검증 + 슬리피지 민감도.

신호: vol_mult=50, gain>=5%, tv>=10M, dedupe 5min
전략: TP15/SL5/15m, TP20/SL5/30m, TP10/SL5/10m

검증:
1. 7일 데이터를 train(처음 5일) / test(마지막 2일) 분할
2. train EV vs test EV 비교
3. 슬리피지 0.3% / 1% / 2% / 3% 민감도
4. 신호별 코인 분포 (편향?)
5. 시간대 분포 (boom 시즌?)
"""
import json
import os
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

FEE = 0.0004


def load_candles(out_dir):
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
        if len(candles) >= 100:
            coins[coin] = candles
    return coins


def find_signals(coins, vol_mult=50, baseline=30, min_gain=5.0, min_tv=10e6):
    signals = []
    for coin, candles in coins.items():
        n = len(candles)
        for i in range(baseline + 5, n - 30):
            ts, o, c, h, l, v = candles[i]
            if c <= 0 or o <= 0 or v <= 0:
                continue
            if c <= o:
                continue
            gain = (c - o) / o * 100
            if gain < min_gain:
                continue
            tv = c * v
            if tv < min_tv:
                continue
            base_vol = sum(candles[j][5] for j in range(i - baseline, i)) / baseline
            if base_vol <= 0:
                continue
            ratio = v / base_vol
            if ratio < vol_mult:
                continue
            signals.append({
                'coin': coin, 'i': i, 'ts': ts,
                'vol_ratio': ratio, 'gain': gain, 'tv': tv,
            })
    return signals


def simulate(candles, signal_i, tp, sl, hold_min):
    if signal_i + 1 >= len(candles):
        return None
    entry = candles[signal_i + 1][1]
    if entry <= 0:
        return None
    tp_p = entry * (1 + tp / 100)
    sl_p = entry * (1 - sl / 100)
    end = min(signal_i + 1 + hold_min, len(candles))
    for j in range(signal_i + 1, end):
        if candles[j][4] <= sl_p:
            return -sl
        if candles[j][3] >= tp_p:
            return tp
    return (candles[end - 1][2] - entry) / entry * 100


def apply_costs(g, slippage):
    return g - (slippage * 2 + FEE * 2) * 100


def main():
    coins = load_candles('data/bithumb_1m')
    print(f'Loaded {len(coins)} coins (1m)')

    sigs = find_signals(coins, vol_mult=50, min_gain=5.0, min_tv=10e6)
    sigs.sort(key=lambda s: (s['coin'], s['i']))
    dedup = []
    last_coin, last_i = None, -100
    for s in sigs:
        if s['coin'] != last_coin or s['i'] - last_i >= 5:
            dedup.append(s)
            last_coin, last_i = s['coin'], s['i']
    print(f'Total deduped signals: {len(dedup)}')

    if not dedup:
        return

    # 시간 범위
    timestamps = sorted(s['ts'] for s in dedup)
    t_min = datetime.fromtimestamp(timestamps[0] / 1000, KST)
    t_max = datetime.fromtimestamp(timestamps[-1] / 1000, KST)
    print(f'Time range: {t_min} → {t_max}')

    # 1. 코인 분포
    print(f'\n=== Signal coin distribution ===')
    coin_counter = Counter(s['coin'] for s in dedup)
    print(f'Unique coins: {len(coin_counter)}')
    print('Top 15:')
    for c, n in coin_counter.most_common(15):
        print(f'  {c}: {n}')

    # 2. 시간대 분포
    print(f'\n=== Signal hour distribution ===')
    hour_counter = Counter()
    date_counter = Counter()
    for s in dedup:
        dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
        hour_counter[dt.hour] += 1
        date_counter[dt.date()] += 1
    for h in range(24):
        if hour_counter[h]:
            print(f'  {h:02d}시: {hour_counter[h]}')

    print(f'\n=== Signal date distribution ===')
    for d in sorted(date_counter.keys()):
        print(f'  {d}: {date_counter[d]}')

    # 3. Walk-forward: train/test split
    print(f'\n=== Walk-forward (train: first 70%, test: last 30%) ===')
    n_total = len(dedup)
    split = int(n_total * 0.7)
    sigs_sorted_by_ts = sorted(dedup, key=lambda s: s['ts'])
    train = sigs_sorted_by_ts[:split]
    test = sigs_sorted_by_ts[split:]
    print(f'Train: {len(train)} signals ({datetime.fromtimestamp(train[0]["ts"]/1000, KST):%m-%d %H:%M} ~ {datetime.fromtimestamp(train[-1]["ts"]/1000, KST):%m-%d %H:%M})')
    print(f'Test:  {len(test)} signals ({datetime.fromtimestamp(test[0]["ts"]/1000, KST):%m-%d %H:%M} ~ {datetime.fromtimestamp(test[-1]["ts"]/1000, KST):%m-%d %H:%M})')

    strategies = [
        ('TP10/SL3/10m', 10, 3, 10),
        ('TP10/SL5/10m', 10, 5, 10),
        ('TP15/SL5/15m', 15, 5, 15),
        ('TP20/SL5/30m', 20, 5, 30),
        ('TP30/SL5/30m', 30, 5, 30),
    ]

    print(f'\n  {"strategy":<18} {"train_win%":>11} {"train_EV":>10} {"test_win%":>10} {"test_EV":>10}')
    for name, tp, sl, hold in strategies:
        train_results = [simulate(coins[s['coin']], s['i'], tp, sl, hold) for s in train]
        train_results = [r for r in train_results if r is not None]
        test_results = [simulate(coins[s['coin']], s['i'], tp, sl, hold) for s in test]
        test_results = [r for r in test_results if r is not None]

        if not train_results or not test_results:
            continue

        train_net = [apply_costs(r, 0.003) for r in train_results]
        test_net = [apply_costs(r, 0.003) for r in test_results]
        tw = sum(1 for x in train_net if x > 0) / len(train_net)
        tew = sum(1 for x in test_net if x > 0) / len(test_net)
        tev = sum(train_net) / len(train_net)
        teev = sum(test_net) / len(test_net)
        print(f'  {name:<18} {tw*100:>10.1f}% {tev:>+9.2f}% {tew*100:>9.1f}% {teev:>+9.2f}%')

    # 4. 슬리피지 민감도
    print(f'\n=== Slippage sensitivity (best strategy: TP15/SL5/15m) ===')
    print(f'  {"slippage":<10} {"win%":>7} {"avg_net":>10}')
    all_results = [simulate(coins[s['coin']], s['i'], 15, 5, 15) for s in dedup]
    all_results = [r for r in all_results if r is not None]
    for slip in [0.001, 0.003, 0.005, 0.01, 0.02, 0.03]:
        nets = [apply_costs(r, slip) for r in all_results]
        wins = sum(1 for x in nets if x > 0)
        avg = sum(nets) / len(nets)
        print(f'  {slip*100:.1f}%      {wins/len(nets)*100:>6.1f}% {avg:>+9.2f}%')

    # 5. 일별 수익 분포
    print(f'\n=== Daily PnL (best strategy: TP15/SL5/15m, 0.3% slippage) ===')
    daily = defaultdict(list)
    for s, r in zip(dedup, all_results):
        if r is not None:
            net = apply_costs(r, 0.003)
            dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
            daily[dt.date()].append(net)
    for d in sorted(daily.keys()):
        trades = daily[d]
        total = sum(trades)
        avg = sum(trades) / len(trades)
        print(f'  {d}  n={len(trades):>3}  avg={avg:>+6.2f}%  total={total:>+7.1f}%')

    # 6. 신호 가격 범위 (작은 코인 vs 큰 코인)
    print(f'\n=== Signal trade value distribution ===')
    tvs = sorted(s['tv'] for s in dedup)
    print(f'  p25: {tvs[len(tvs)//4]/1e6:.1f}M')
    print(f'  p50: {tvs[len(tvs)//2]/1e6:.1f}M')
    print(f'  p75: {tvs[len(tvs)*3//4]/1e6:.1f}M')
    print(f'  p90: {tvs[len(tvs)*9//10]/1e6:.1f}M')


if __name__ == '__main__':
    main()
