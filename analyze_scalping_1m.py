"""
1분봉 스캘핑 백테스트.
가설: 펌프 시작 캔들에 즉시 진입 → 1~3분 안에 +1~5% 빠른 익절
- 작은 winner를 많이 잡는 게 큰 winner 1건보다 EV 높을 수 있음
- 1분봉 데이터는 7일치 (표본 작음)
"""
import json
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

SLIPPAGE = 0.003  # 0.3%
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


def find_1m_signals(coins, vol_mult=20, baseline=30, min_candle_gain=2.0, min_tv_krw=5e6):
    """1분봉 신호: 직전 baseline봉 평균 vol의 N배 + 양봉 + 신호 캔들 자체 +X% 이상 + 거래액"""
    signals = []
    for coin, candles in coins.items():
        n = len(candles)
        for i in range(baseline + 5, n - 30):
            ts, o, c, h, l, v = candles[i]
            if c <= 0 or o <= 0 or v <= 0:
                continue
            if c <= o:
                continue  # 양봉
            gain = (c - o) / o * 100
            if gain < min_candle_gain:
                continue
            tv = c * v
            if tv < min_tv_krw:
                continue
            base_vol = sum(candles[j][5] for j in range(i - baseline, i)) / baseline
            if base_vol <= 0:
                continue
            ratio = v / base_vol
            if ratio < vol_mult:
                continue
            signals.append({
                'coin': coin, 'i': i, 'ts': ts,
                'vol_ratio': ratio, 'tv': tv, 'gain': gain,
            })
    return signals


def simulate_scalping(candles, signal_i, tp_pct, sl_pct, max_hold_min):
    """신호 캔들 다음 1분봉 시가 진입, TP/SL/시간 만료"""
    if signal_i + 1 >= len(candles):
        return None
    entry_price = candles[signal_i + 1][1]
    if entry_price <= 0:
        return None
    tp_p = entry_price * (1 + tp_pct / 100)
    sl_p = entry_price * (1 - sl_pct / 100)
    end = min(signal_i + 1 + max_hold_min, len(candles))
    for j in range(signal_i + 1, end):
        h = candles[j][3]
        l = candles[j][4]
        # 보수: SL 우선
        if l <= sl_p:
            return -sl_pct
        if h >= tp_p:
            return tp_pct
    last = candles[end - 1][2]
    return (last - entry_price) / entry_price * 100


def apply_costs(g):
    return g - (SLIPPAGE * 2 + FEE * 2) * 100


def main():
    coins = load_candles('data/bithumb_1m')
    print(f'Loaded {len(coins)} coins (1m)')

    # 다양한 신호 강도
    print(f'\n{"=" * 90}')
    print('1m signal candidates (vol_mult, candle_gain, tv) → scalping EV')
    print(f'{"=" * 90}')

    # 다양한 조합 시도
    print(f'{"vol_mult":<10} {"min_gain":<10} {"n_signals":>10}')
    for vm in [5, 10, 20, 50, 100]:
        for mg in [1, 2, 3, 5]:
            sigs = find_1m_signals(coins, vol_mult=vm, min_candle_gain=mg)
            # dedupe per coin within 5 min
            sigs.sort(key=lambda s: (s['coin'], s['i']))
            dedup = []
            last_coin, last_i = None, -100
            for s in sigs:
                if s['coin'] != last_coin or s['i'] - last_i >= 5:
                    dedup.append(s)
                    last_coin, last_i = s['coin'], s['i']
            print(f'  {vm:<10} {mg:<10} {len(dedup):>10}')

    # 가장 합리적인 신호로 본격 시뮬: vol_mult=20, gain>=3, tv>=5M
    print(f'\n=== Scalping EV: vol_mult=20, gain>=3%, tv>=5M ===')
    sigs = find_1m_signals(coins, vol_mult=20, min_candle_gain=3, min_tv_krw=5e6)
    sigs.sort(key=lambda s: (s['coin'], s['i']))
    dedup = []
    last_coin, last_i = None, -100
    for s in sigs:
        if s['coin'] != last_coin or s['i'] - last_i >= 5:
            dedup.append(s)
            last_coin, last_i = s['coin'], s['i']
    print(f'Signals: {len(dedup)}')

    print(f'\n  {"strategy":<20} {"n":>5} {"win%":>7} {"avg_gross":>11} {"avg_net":>10}')
    print('  ' + '-' * 70)
    strategies = [
        ('TP1/SL1/3m', 1, 1, 3),
        ('TP2/SL1/3m', 2, 1, 3),
        ('TP3/SL1/3m', 3, 1, 3),
        ('TP1/SL2/3m', 1, 2, 3),
        ('TP2/SL2/3m', 2, 2, 3),
        ('TP3/SL2/3m', 3, 2, 3),
        ('TP5/SL2/5m', 5, 2, 5),
        ('TP5/SL3/5m', 5, 3, 5),
        ('TP10/SL3/10m', 10, 3, 10),
        ('TP10/SL5/10m', 10, 5, 10),
        ('TP15/SL5/15m', 15, 5, 15),
        ('TP20/SL5/30m', 20, 5, 30),
        ('TP3/SL1/5m', 3, 1, 5),
        ('TP5/SL2/10m', 5, 2, 10),
        ('TP2/SL1/10m', 2, 1, 10),
    ]
    for name, tp, sl, hold in strategies:
        gross_pcts = []
        for s in dedup:
            r = simulate_scalping(coins[s['coin']], s['i'], tp, sl, hold)
            if r is not None:
                gross_pcts.append(r)
        if not gross_pcts:
            continue
        n = len(gross_pcts)
        wins = sum(1 for x in gross_pcts if x > 0)
        avg_g = sum(gross_pcts) / n
        avg_n = avg_g - (SLIPPAGE * 2 + FEE * 2) * 100
        print(f'  {name:<20} {n:>5} {wins/n*100:>6.1f}% {avg_g:>+10.2f}% {avg_n:>+9.2f}%')

    # 더 strict (vol_mult=50, gain>=5%)
    print(f'\n=== Scalping EV: vol_mult=50, gain>=5%, tv>=10M (strict) ===')
    sigs = find_1m_signals(coins, vol_mult=50, min_candle_gain=5, min_tv_krw=10e6)
    sigs.sort(key=lambda s: (s['coin'], s['i']))
    dedup = []
    last_coin, last_i = None, -100
    for s in sigs:
        if s['coin'] != last_coin or s['i'] - last_i >= 5:
            dedup.append(s)
            last_coin, last_i = s['coin'], s['i']
    print(f'Signals: {len(dedup)}')

    if dedup:
        print(f'\n  {"strategy":<20} {"n":>5} {"win%":>7} {"avg_gross":>11} {"avg_net":>10}')
        print('  ' + '-' * 70)
        for name, tp, sl, hold in strategies:
            gross_pcts = []
            for s in dedup:
                r = simulate_scalping(coins[s['coin']], s['i'], tp, sl, hold)
                if r is not None:
                    gross_pcts.append(r)
            if not gross_pcts:
                continue
            n = len(gross_pcts)
            wins = sum(1 for x in gross_pcts if x > 0)
            avg_g = sum(gross_pcts) / n
            avg_n = avg_g - (SLIPPAGE * 2 + FEE * 2) * 100
            print(f'  {name:<20} {n:>5} {wins/n*100:>6.1f}% {avg_g:>+10.2f}% {avg_n:>+9.2f}%')

    # vol_mult=100, gain>=10%
    print(f'\n=== Scalping EV: vol_mult=100, gain>=10%, tv>=20M (very strict) ===')
    sigs = find_1m_signals(coins, vol_mult=100, min_candle_gain=10, min_tv_krw=20e6)
    sigs.sort(key=lambda s: (s['coin'], s['i']))
    dedup = []
    last_coin, last_i = None, -100
    for s in sigs:
        if s['coin'] != last_coin or s['i'] - last_i >= 5:
            dedup.append(s)
            last_coin, last_i = s['coin'], s['i']
    print(f'Signals: {len(dedup)}')

    if dedup:
        for s in dedup[:20]:
            ts = datetime.fromtimestamp(s['ts'] / 1000, KST)
            print(f'    {s["coin"]:>10} {ts:%m-%d %H:%M} vr={s["vol_ratio"]:>7.1f}x gain={s["gain"]:>+5.1f}%')
        print(f'\n  {"strategy":<20} {"n":>5} {"win%":>7} {"avg_gross":>11} {"avg_net":>10}')
        for name, tp, sl, hold in strategies:
            gross_pcts = []
            for s in dedup:
                r = simulate_scalping(coins[s['coin']], s['i'], tp, sl, hold)
                if r is not None:
                    gross_pcts.append(r)
            if not gross_pcts:
                continue
            n = len(gross_pcts)
            wins = sum(1 for x in gross_pcts if x > 0)
            avg_g = sum(gross_pcts) / n
            avg_n = avg_g - (SLIPPAGE * 2 + FEE * 2) * 100
            print(f'  {name:<20} {n:>5} {wins/n*100:>6.1f}% {avg_g:>+10.2f}% {avg_n:>+9.2f}%')


if __name__ == '__main__':
    main()
