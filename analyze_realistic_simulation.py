"""
현실적 시뮬: 사용자의 매매 방식 반영.

기본 가정 변경:
1. SL 더 넓게 (5~7%) — 봉 안 dip 견딤
2. Entry 1~2봉 지연 가능
3. Reversal exit: 음봉 발생 시 다음 봉 시가 청산
4. Trailing stop: 최고가 대비 -X% 떨어지면 청산
5. 봉 안 OHLC 순서 추정 (양봉: O→L→H→C, 음봉: O→H→L→C)
"""
import json
import os
from collections import Counter
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
    signals = []
    for coin, candles in coins.items():
        n = len(candles)
        last_signal = -1000
        for i in range(35, n - 60):
            if i - last_signal < dedupe_min:
                continue
            ts = candles[i][0]
            close_now = candles[i][2]
            if close_now <= 0:
                continue
            tv_5 = sum(candles[j][2] * candles[j][5] for j in range(max(0, i - 5), i))
            if tv_5 < min_tv_5min:
                continue
            up_count = sum(1 for j in range(max(0, i - 5), i) if candles[j][2] > candles[j][1])
            up_ratio = up_count / 5
            if up_ratio < min_up_ratio:
                continue
            triggered = False
            for lb_min, min_gain in lookbacks:
                if i < lb_min + 1:
                    continue
                start_close = candles[i - lb_min][2]
                if start_close <= 0:
                    continue
                cum_gain = (close_now - start_close) / start_close * 100
                if cum_gain >= min_gain:
                    triggered = True
                    break
            if not triggered:
                continue
            signals.append({'coin': coin, 'i': i, 'ts': ts})
            last_signal = i
    return signals


def simulate_ohlc_order(candles, entry_i, tp, sl, hold_min):
    """봉 안 OHLC 순서 추정:
    양봉(C>=O): O → L → H → C
    음봉(C<O): O → H → L → C
    이걸로 SL/TP 충돌 시 어느 쪽이 먼저 닿았는지 추정
    """
    if entry_i >= len(candles):
        return None
    entry = candles[entry_i][1]
    if entry <= 0:
        return None
    tp_p = entry * (1 + tp / 100)
    sl_p = entry * (1 - sl / 100)
    end = min(entry_i + hold_min, len(candles))
    for j in range(entry_i, end):
        ts, o, c, h, l, v = candles[j]
        is_up = c >= o
        # 진입 봉(j == entry_i)이면 시작 가격은 entry, 그 외는 o
        if j == entry_i:
            # 진입 직후, 가격 경로: entry → ... → close
            # 양봉이면 entry → 약간 dip → high → close (보수: dip이 SL 닿는지)
            # 음봉이면 entry → 약간 up → low → close (보수: 약간 up이 TP 닿는지)
            if is_up:
                if l <= sl_p:
                    return -sl
                if h >= tp_p:
                    return tp
            else:
                if h >= tp_p:
                    return tp
                if l <= sl_p:
                    return -sl
        else:
            if is_up:
                # O → L → H → C
                if l <= sl_p:
                    return -sl
                if h >= tp_p:
                    return tp
            else:
                # O → H → L → C
                if h >= tp_p:
                    return tp
                if l <= sl_p:
                    return -sl
    return (candles[end - 1][2] - entry) / entry * 100


def simulate_reversal_exit(candles, entry_i, sl, hold_min, max_tp=None):
    """진입 후, 음봉 발생 시 다음 봉 시가에 청산.
    SL은 보호용 (음봉 전에 -SL% 닿으면 즉시 청산).
    """
    if entry_i >= len(candles):
        return None
    entry = candles[entry_i][1]
    if entry <= 0:
        return None
    sl_p = entry * (1 - sl / 100)
    end = min(entry_i + hold_min, len(candles))
    for j in range(entry_i, end):
        ts, o, c, h, l, v = candles[j]
        # SL 체크 먼저 (양봉이든 음봉이든)
        if l <= sl_p:
            return -sl
        # max_tp 체크 (안전 익절)
        if max_tp is not None and h >= entry * (1 + max_tp / 100):
            return max_tp
        # 음봉이면 다음 봉 시가에 청산
        if c < o and j > entry_i:  # 진입 봉은 제외 (방금 진입)
            if j + 1 < len(candles):
                exit_price = candles[j + 1][1]
                return (exit_price - entry) / entry * 100
            return (c - entry) / entry * 100
    # 시간 만료
    return (candles[end - 1][2] - entry) / entry * 100


def simulate_trailing(candles, entry_i, trail_pct, sl, hold_min):
    """트레일링 스탑: 최고가에서 trail_pct% 떨어지면 청산"""
    if entry_i >= len(candles):
        return None
    entry = candles[entry_i][1]
    if entry <= 0:
        return None
    sl_p = entry * (1 - sl / 100)
    max_high = entry
    end = min(entry_i + hold_min, len(candles))
    for j in range(entry_i, end):
        ts, o, c, h, l, v = candles[j]
        if h > max_high:
            max_high = h
        # 트레일링 stop 가격
        trail_p = max_high * (1 - trail_pct / 100)
        # SL 체크
        if l <= sl_p:
            return -sl
        # 트레일링 (단 진입 봉 제외)
        if j > entry_i and l <= trail_p:
            return (trail_p - entry) / entry * 100
    return (candles[end - 1][2] - entry) / entry * 100


def apply_costs(g, slip=SLIPPAGE):
    return g - (slip * 2 + FEE * 2) * 100


def main():
    coins = load_candles_1m()
    print(f'Loaded {len(coins)} coins (1m)')

    sigs = find_adaptive_signals(coins)
    print(f'Adaptive signals: {len(sigs)}')

    # ===== 1. SL 확장 효과 =====
    print('\n=== SL 확장 효과 (entry: signal_i+1, OHLC order sim) ===')
    print(f'  {"strategy":<22} {"n":>5} {"win%":>7} {"EV@0.3%":>10} {"EV@1%":>10}')
    for tp in [10, 15, 20, 30]:
        for sl in [3, 5, 7, 10]:
            for hold in [15, 30, 60]:
                gross = []
                for s in sigs:
                    r = simulate_ohlc_order(coins[s['coin']], s['i'] + 1, tp, sl, hold)
                    if r is not None:
                        gross.append(r)
                if not gross:
                    continue
                n = len(gross)
                wins = sum(1 for x in gross if x > 0)
                avg03 = sum(apply_costs(x, 0.003) for x in gross) / n
                avg10 = sum(apply_costs(x, 0.010) for x in gross) / n
                marker = ' *' if avg03 > 0 else ''
                print(f'  TP{tp}/SL{sl}/{hold}m{"":<10} {n:>5} {wins/n*100:>6.1f}% {avg03:>+9.2f}% {avg10:>+9.2f}%{marker}')

    # ===== 2. Entry delay =====
    print('\n=== Entry delay (TP15/SL5/30m, OHLC order) ===')
    print(f'  {"delay":<10} {"n":>5} {"win%":>7} {"EV@0.3%":>10}')
    for delay in [1, 2, 3, 5]:
        gross = []
        for s in sigs:
            r = simulate_ohlc_order(coins[s['coin']], s['i'] + delay, 15, 5, 30)
            if r is not None:
                gross.append(r)
        if not gross:
            continue
        n = len(gross)
        wins = sum(1 for x in gross if x > 0)
        avg03 = sum(apply_costs(x, 0.003) for x in gross) / n
        marker = ' *' if avg03 > 0 else ''
        print(f'  +{delay}봉      {n:>5} {wins/n*100:>6.1f}% {avg03:>+9.2f}%{marker}')

    # ===== 3. Reversal exit =====
    print('\n=== Reversal exit: 음봉 → 다음 봉 시가 청산 (SL 보호) ===')
    print(f'  {"strategy":<22} {"n":>5} {"win%":>7} {"avg_gross":>11} {"EV@0.3%":>10} {"EV@1%":>10}')
    for sl in [3, 5, 7]:
        for hold in [15, 30, 60]:
            for max_tp in [None, 30, 50]:
                gross = []
                for s in sigs:
                    r = simulate_reversal_exit(coins[s['coin']], s['i'] + 1, sl, hold, max_tp)
                    if r is not None:
                        gross.append(r)
                if not gross:
                    continue
                n = len(gross)
                wins = sum(1 for x in gross if x > 0)
                avg_g = sum(gross) / n
                avg03 = sum(apply_costs(x, 0.003) for x in gross) / n
                avg10 = sum(apply_costs(x, 0.010) for x in gross) / n
                tp_str = f'mtp{max_tp}' if max_tp else 'no_mtp'
                marker = ' *' if avg03 > 0 else ''
                print(f'  SL{sl}/{hold}m/{tp_str:<8} {n:>5} {wins/n*100:>6.1f}% {avg_g:>+10.2f}% {avg03:>+9.2f}% {avg10:>+9.2f}%{marker}')

    # ===== 4. Trailing stop =====
    print('\n=== Trailing stop ===')
    print(f'  {"strategy":<22} {"n":>5} {"win%":>7} {"avg_gross":>11} {"EV@0.3%":>10}')
    for trail in [3, 5, 7, 10]:
        for sl in [5, 7, 10]:
            for hold in [30, 60]:
                gross = []
                for s in sigs:
                    r = simulate_trailing(coins[s['coin']], s['i'] + 1, trail, sl, hold)
                    if r is not None:
                        gross.append(r)
                if not gross:
                    continue
                n = len(gross)
                wins = sum(1 for x in gross if x > 0)
                avg_g = sum(gross) / n
                avg03 = sum(apply_costs(x, 0.003) for x in gross) / n
                marker = ' *' if avg03 > 0 else ''
                print(f'  trail{trail}/SL{sl}/{hold}m{"":<5} {n:>5} {wins/n*100:>6.1f}% {avg_g:>+10.2f}% {avg03:>+9.2f}%{marker}')


if __name__ == '__main__':
    main()
