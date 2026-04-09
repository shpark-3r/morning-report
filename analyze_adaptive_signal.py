"""
Multi-lookback adaptive 신호:
  cumulative gain in N min >= threshold (어느 N이든 만족하면 trigger)
  + 양봉 비율 >= 60%
  + 5min trade value >= min_tv

검증:
  1. JOE/XION/ENJ/XYO/TRAC 등 사용자 펌프에서 trigger 시점
  2. 전체 1분봉에서 발생 빈도 + EV
  3. 슬리피지 민감도
"""
import json
import os
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

SLIPPAGE = 0.003
FEE = 0.0004


def load_candles_1m():
    coins = {}
    out_dir = 'data/bithumb_1m'
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


def find_adaptive_signals(coins,
                          lookbacks=((5, 5), (10, 7), (15, 10), (30, 15)),
                          min_up_ratio=0.6,
                          min_tv_5min=30e6,
                          dedupe_min=10):
    """
    각 캔들 i에서 (lookback_N, min_gain) 조건을 모두 검사.
    어느 한 (lookback, gain) 쌍이 만족하면 trigger.
    """
    signals = []
    for coin, candles in coins.items():
        n = len(candles)
        last_signal = -1000
        for i in range(35, n - 30):
            if i - last_signal < dedupe_min:
                continue
            ts = candles[i][0]
            close_now = candles[i][2]
            if close_now <= 0:
                continue

            # 5분 trade value (이 시점부터 직전 5분)
            tv_5 = sum(candles[j][2] * candles[j][5] for j in range(max(0, i - 5), i))
            if tv_5 < min_tv_5min:
                continue

            # 양봉 비율 (직전 5봉)
            up_count = sum(1 for j in range(max(0, i - 5), i) if candles[j][2] > candles[j][1])
            up_ratio = up_count / 5
            if up_ratio < min_up_ratio:
                continue

            # multi-lookback gain check
            triggered_lb = None
            for lb_min, min_gain in lookbacks:
                if i < lb_min + 1:
                    continue
                start_close = candles[i - lb_min][2]
                if start_close <= 0:
                    continue
                cum_gain = (close_now - start_close) / start_close * 100
                if cum_gain >= min_gain:
                    triggered_lb = (lb_min, cum_gain)
                    break

            if triggered_lb is None:
                continue

            # vol_ratio (보조)
            past_5_vol = sum(candles[j][5] for j in range(max(0, i - 5), i))
            base_vol_30 = sum(candles[j][5] for j in range(max(0, i - 35), max(0, i - 5))) / 30 if i >= 35 else 0
            vol_ratio_5 = (past_5_vol / 5) / base_vol_30 if base_vol_30 > 0 else 0

            signals.append({
                'coin': coin, 'i': i, 'ts': ts,
                'close': close_now,
                'tv_5min': tv_5,
                'up_ratio': up_ratio,
                'vol_ratio_5': vol_ratio_5,
                'triggered_lb_min': triggered_lb[0],
                'triggered_gain': triggered_lb[1],
            })
            last_signal = i
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


def apply_costs(g, slip=SLIPPAGE):
    return g - (slip * 2 + FEE * 2) * 100


def main():
    coins = load_candles_1m()
    print(f'Loaded {len(coins)} coins (1m)')

    # === 1. 적응형 신호 찾기 ===
    print('\n=== Adaptive signal: any of (5min+5%, 10min+7%, 15min+10%, 30min+15%) ===')
    print('  + up_ratio >= 60% + tv_5min >= 30M')
    sigs = find_adaptive_signals(coins)
    print(f'Total signals: {len(sigs)}')

    # === 2. 사용자 펌프에서 trigger 됐는지 ===
    print('\n=== USER-mentioned pumps - check signal triggers ===')
    target = [
        ('ENJ', '2026-04-09', 11, 13),
        ('JOE', '2026-04-08', 6, 9),
        ('XION', '2026-04-07', 14, 17),
        ('XYO', '2026-03-31', 17, 19),
        ('TRAC', '2026-04-05', 19, 22),
    ]
    for coin, date, h_lo, h_hi in target:
        relevant = [s for s in sigs if s['coin'] == coin]
        relevant_in_window = []
        for s in relevant:
            dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
            if dt.strftime('%Y-%m-%d') == date and h_lo <= dt.hour <= h_hi:
                relevant_in_window.append((dt, s))
        relevant_in_window.sort(key=lambda x: x[1]['ts'])
        print(f'\n  {coin} {date} {h_lo}~{h_hi}시: {len(relevant_in_window)} signals')
        for dt, s in relevant_in_window[:8]:
            print(f'    {dt:%H:%M}  lb={s["triggered_lb_min"]:>2}min gain={s["triggered_gain"]:>+5.1f}% '
                  f'tv5={s["tv_5min"]/1e6:>4.0f}M up={s["up_ratio"]:.1f} vol5x={s["vol_ratio_5"]:>4.1f}')

    # === 3. 전체 EV 측정 ===
    print('\n\n=== EV simulation (multiple TP/SL strategies) ===')
    print(f'  {"strategy":<22} {"n":>5} {"win%":>7} {"avg_gross":>11} {"EV@0.3%":>10} {"EV@1%":>10}')
    print('  ' + '-' * 78)
    strategies = [
        ('TP10/SL3/30m', 10, 3, 30),
        ('TP15/SL5/30m', 15, 5, 30),
        ('TP20/SL5/30m', 20, 5, 30),
        ('TP15/SL5/45m', 15, 5, 45),
        ('TP20/SL5/60m', 20, 5, 60),
        ('TP30/SL5/60m', 30, 5, 60),
        ('TP10/SL3/60m', 10, 3, 60),
        ('TP15/SL3/60m', 15, 3, 60),
        ('TP20/SL3/60m', 20, 3, 60),
        ('TP10/SL5/15m', 10, 5, 15),
        ('TP10/SL3/15m', 10, 3, 15),
    ]
    for name, tp, sl, hold in strategies:
        gross = []
        for s in sigs:
            r = simulate(coins[s['coin']], s['i'], tp, sl, hold)
            if r is not None:
                gross.append(r)
        if not gross:
            continue
        n = len(gross)
        wins = sum(1 for x in gross if x > 0)
        avg_g = sum(gross) / n
        avg_n_03 = sum(apply_costs(x, 0.003) for x in gross) / n
        avg_n_10 = sum(apply_costs(x, 0.010) for x in gross) / n
        print(f'  {name:<22} {n:>5} {wins/n*100:>6.1f}% {avg_g:>+10.2f}% {avg_n_03:>+9.2f}% {avg_n_10:>+9.2f}%')

    # === 4. 코인 분포 ===
    print('\n=== Signal coin distribution ===')
    cnt = Counter(s['coin'] for s in sigs)
    print(f'Unique coins: {len(cnt)}')
    print('Top 15:')
    for c, n in cnt.most_common(15):
        print(f'  {c}: {n}')

    # === 5. 일별 분포 ===
    print('\n=== Signal daily distribution ===')
    daily = Counter()
    for s in sigs:
        dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
        daily[dt.date()] += 1
    for d in sorted(daily.keys()):
        print(f'  {d}: {daily[d]}')


if __name__ == '__main__':
    main()
