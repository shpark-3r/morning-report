"""
4/9 백테스트 결과 재현:
- 신호: 30분봉 vol >= 직전 30개 봉 mean의 150x + 양봉 + 거래액 >= 10M KRW
- 진입: 신호 캔들 종료 후 다음 봉 시가
- 출구: TP +10% / SL -3% / max hold 4시간 (8 봉)

목표: 이전 메모리의 EV +0.90%/trade가 현재 데이터로 재현되는지 검증.
"""
import json
import os
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

SLIPPAGE = 0.003
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


def find_burst_signals(coins, vol_mult, baseline_bars=30, min_tv_krw=10e6):
    """vol >= baseline_mean * vol_mult, 양봉, 거래액 조건"""
    signals = []
    for coin, candles in coins.items():
        n = len(candles)
        for i in range(baseline_bars + 5, n - 8):
            ts, o, c, h, l, v = candles[i]
            if c <= 0 or o <= 0 or v <= 0:
                continue
            # 양봉
            if c <= o:
                continue
            # 거래액 (이 봉의)
            tv = c * v
            if tv < min_tv_krw:
                continue
            # 직전 baseline_bars 평균
            base_vol = sum(candles[j][5] for j in range(i - baseline_bars, i)) / baseline_bars
            if base_vol <= 0:
                continue
            ratio = v / base_vol
            if ratio < vol_mult:
                continue
            signals.append({
                'coin': coin, 'i': i, 'ts': ts,
                'vol_ratio': ratio, 'tv': tv,
                'open': o, 'close': c,
            })
    return signals


def simulate(candles, entry_i, tp_pct, sl_pct, max_hold, optimistic=False):
    """다음 봉 시가 진입, TP/SL/시간 만료
    optimistic=True: 같은 봉에 TP/SL 다 닿으면 TP 우선 (낙관)
    optimistic=False: SL 우선 (보수)
    """
    if entry_i + 1 >= len(candles):
        return None
    entry_price = candles[entry_i + 1][1]
    if entry_price <= 0:
        return None
    tp_p = entry_price * (1 + tp_pct / 100)
    sl_p = entry_price * (1 - sl_pct / 100)
    end = min(entry_i + 1 + max_hold, len(candles))
    for j in range(entry_i + 1, end):
        h = candles[j][3]
        l = candles[j][4]
        if optimistic:
            if h >= tp_p:
                return tp_pct
            if l <= sl_p:
                return -sl_pct
        else:
            if l <= sl_p:
                return -sl_pct
            if h >= tp_p:
                return tp_pct
    last = candles[end - 1][2]
    return (last - entry_price) / entry_price * 100


def apply_costs(g):
    return g - (SLIPPAGE * 2 + FEE * 2) * 100


def main():
    coins = load_candles('data/bithumb_30m')
    print(f'Loaded {len(coins)} coins')

    # 다양한 vol_mult로 단조 증가 검증
    print(f'\n{"=" * 90}')
    print('Vol burst replication test (TP+10/SL-3/4h, dedupe by coin within 4h)')
    print(f'{"=" * 90}')
    print(f'{"vol_mult":<10} {"n_raw":>8} {"n_dedup":>8} {"win%":>7} {"avg_gross":>11} {"avg_net":>10} {"med":>10}')

    for vm in [10, 20, 30, 50, 100, 150, 200, 300]:
        signals = find_burst_signals(coins, vol_mult=vm)
        # dedupe per coin within 8 bars (4h)
        signals.sort(key=lambda s: (s['coin'], s['i']))
        deduped = []
        last_coin = None
        last_i = -1000
        for s in signals:
            if s['coin'] != last_coin or s['i'] - last_i >= 8:
                deduped.append(s)
                last_coin = s['coin']
                last_i = s['i']

        gross_pcts = []
        for s in deduped:
            r = simulate(coins[s['coin']], s['i'], 10, 3, 8)
            if r is not None:
                gross_pcts.append(r)

        if not gross_pcts:
            print(f'{vm:<10} {len(signals):>8} {len(deduped):>8}     -       -          -          -')
            continue
        net = [apply_costs(g) for g in gross_pcts]
        n = len(net)
        wins = sum(1 for x in net if x > 0)
        avg_g = sum(gross_pcts) / n
        avg_n = sum(net) / n
        med = sorted(net)[n // 2]
        print(f'{vm:<10} {len(signals):>8} {len(deduped):>8} {wins/n*100:>6.1f}% {avg_g:>+10.2f}% {avg_n:>+9.2f}% {med:>+9.2f}%')

    # 가장 strict 신호의 케이스 자세히
    print(f'\n=== vol>=150x detail ===')
    sigs_150 = find_burst_signals(coins, vol_mult=150)
    sigs_150.sort(key=lambda s: (s['coin'], s['i']))
    deduped = []
    last_coin = None
    last_i = -1000
    for s in sigs_150:
        if s['coin'] != last_coin or s['i'] - last_i >= 8:
            deduped.append(s)
            last_coin = s['coin']
            last_i = s['i']
    print(f'  raw signals: {len(sigs_150)}, deduped: {len(deduped)}')
    print(f'\n  Sample:')
    for s in deduped[:25]:
        candles = coins[s['coin']]
        gross = simulate(candles, s['i'], 10, 3, 8)
        net = apply_costs(gross) if gross is not None else None
        ts = datetime.fromtimestamp(s['ts'] / 1000, KST)
        net_str = f'{net:+.2f}%' if net is not None else 'n/a'
        print(f'    {s["coin"]:>10} {ts:%m-%d %H:%M} vr={s["vol_ratio"]:>7.1f}x tv={s["tv"]/1e6:>6.0f}M result={net_str}')

    # 다양한 TP/SL로 vol>=150x 결과
    print(f'\n=== vol>=150x with various exit strategies ===')
    print(f'  {"strategy":<18} {"win%":>7} {"avg_net":>10}')
    for name, tp, sl, hold in [
        ('TP10/SL3/4h', 10, 3, 8),
        ('TP10/SL5/4h', 10, 5, 8),
        ('TP15/SL3/4h', 15, 3, 8),
        ('TP20/SL3/4h', 20, 3, 8),
        ('TP30/SL3/4h', 30, 3, 8),
        ('TP10/SL3/8h', 10, 3, 16),
        ('TP20/SL5/8h', 20, 5, 16),
        ('TP50/SL5/8h', 50, 5, 16),
        ('TP10/SL3/2h', 10, 3, 4),
    ]:
        gross_pcts = []
        for s in deduped:
            r = simulate(coins[s['coin']], s['i'], tp, sl, hold)
            if r is not None:
                gross_pcts.append(r)
        if not gross_pcts:
            continue
        net = [apply_costs(g) for g in gross_pcts]
        n = len(net)
        wins = sum(1 for x in net if x > 0)
        avg = sum(net) / n
        print(f'  {name:<18} {wins/n*100:>6.1f}% {avg:>+9.2f}%')


if __name__ == '__main__':
    main()
