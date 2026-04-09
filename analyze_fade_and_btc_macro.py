"""
1) Fade strategy: 신호 후 dip을 기다리고 진입.
   - 신호 후 N봉 안에 가격이 -X% dip → 그 시점 시가 진입
   - dip 안 오면 진입 안 함 (no trade)
   - 출구: TP +10 / SL -3 / 4h hold

2) BTC/ETH 매크로 트리거:
   - BTC가 직전 N분 ±X% 움직임 → 이후 N분 빗썸 작전 발생 빈도 측정
   - BTC 매크로 움직임이 작전 timing trigger인지 확인
"""
import json
import os
import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from analyze_vol_burst_replicate import (
    load_candles, find_burst_signals, simulate, apply_costs
)

KST = timezone(timedelta(hours=9))


def simulate_fade(candles, signal_i, dip_pct, max_wait_bars, tp, sl, hold):
    """
    신호 캔들 i에서 시작.
    이후 max_wait_bars 봉 동안 가격이 (close[i] * (1 - dip_pct/100)) 이하로 떨어지면 그 봉의 시가 진입.
    진입 후 TP/SL/hold 적용.
    dip 안 오면 None 반환 (no trade).
    """
    if signal_i + 1 >= len(candles):
        return None, None
    signal_close = candles[signal_i][2]
    if signal_close <= 0:
        return None, None
    dip_target = signal_close * (1 - dip_pct / 100)

    end_wait = min(signal_i + 1 + max_wait_bars, len(candles))
    entry_i = None
    for j in range(signal_i + 1, end_wait):
        if candles[j][4] <= dip_target:  # low가 dip target 이하
            entry_i = j
            break
    if entry_i is None:
        return None, 'no_dip'

    # 진입가: dip_target (limit order 가정)
    entry_price = dip_target
    tp_p = entry_price * (1 + tp / 100)
    sl_p = entry_price * (1 - sl / 100)
    end_hold = min(entry_i + hold, len(candles))
    for j in range(entry_i, end_hold):
        h = candles[j][3]
        l = candles[j][4]
        if l <= sl_p:
            return -sl, 'sl'
        if h >= tp_p:
            return tp, 'tp'
    last = candles[end_hold - 1][2]
    return (last - entry_price) / entry_price * 100, 'time'


def main():
    coins = load_candles('data/bithumb_30m')
    print(f'Loaded {len(coins)} coins')

    # ===== 1. Fade strategy =====
    print('\n=== Fade strategy: 신호 후 dip 기다림 진입 ===')
    sigs = find_burst_signals(coins, vol_mult=100, min_tv_krw=10e6)
    sigs.sort(key=lambda s: (s['coin'], s['i']))
    deduped = []
    last_coin, last_i = None, -1000
    for s in sigs:
        if s['coin'] != last_coin or s['i'] - last_i >= 8:
            deduped.append(s)
            last_coin, last_i = s['coin'], s['i']
    print(f'Total signals: {len(deduped)}')

    print(f'\n{"dip%":<7} {"max_wait":<10} {"TP/SL/hold":<14} {"n_trade":>8} {"win%":>7} {"avg_net":>10} {"trade_rate":>11}')
    print('-' * 80)
    for dip in [1, 2, 3, 5, 7]:
        for wait in [4, 8, 16]:
            for tp, sl, hold in [(10, 3, 8), (10, 5, 8), (15, 5, 8)]:
                results = []
                no_dip = 0
                for s in deduped:
                    r, why = simulate_fade(coins[s['coin']], s['i'], dip, wait, tp, sl, hold)
                    if r is None:
                        if why == 'no_dip':
                            no_dip += 1
                        continue
                    results.append(apply_costs(r))
                if not results:
                    continue
                n = len(results)
                wins = sum(1 for x in results if x > 0)
                avg = sum(results) / n
                trade_rate = n / len(deduped) * 100
                print(f'  -{dip}%   {wait}봉      TP{tp}/SL{sl}/{hold//2}h   {n:>6} {wins/n*100:>6.1f}% {avg:>+9.2f}% {trade_rate:>10.1f}%')

    # ===== 2. BTC 매크로 트리거 =====
    print('\n\n=== BTC macro trigger: BTC 큰 움직임 → 빗썸 작전 발생 빈도 ===')
    btc = coins.get('BTC')
    if not btc:
        print('No BTC data')
        return

    # 펌프 시작점 (1h +50%) 모두 수집
    all_pump_ts = set()  # ts_ms
    for coin, candles in coins.items():
        if coin == 'BTC':
            continue
        for i in range(2, len(candles) - 2):
            c = candles[i][2]
            if c <= 0:
                continue
            future_max = max(candles[j][3] for j in range(i + 1, i + 3))
            gain = (future_max - c) / c * 100
            if gain >= 50:
                all_pump_ts.add(candles[i][0])

    print(f'Total pump start timestamps: {len(all_pump_ts)}')

    # BTC 30분봉 변화율 계산
    btc_changes = {}  # ts_ms → change_%
    for i in range(1, len(btc)):
        if btc[i - 1][2] > 0:
            ch = (btc[i][2] - btc[i - 1][2]) / btc[i - 1][2] * 100
            btc_changes[btc[i][0]] = ch

    # 각 BTC 캔들마다: 그 시점부터 N봉 안에 펌프가 발생했는가
    print(f'\nBTC change vs subsequent pump probability:')
    for btc_thr in [0.5, 1.0, 2.0, 3.0]:
        for direction in ['up', 'down', 'abs']:
            for forward_bars in [2, 4, 8]:  # 1h, 2h, 4h 윈도우
                up_btc_with_pump = 0
                up_btc_total = 0
                for ts, ch in btc_changes.items():
                    if direction == 'up' and ch < btc_thr:
                        continue
                    if direction == 'down' and ch > -btc_thr:
                        continue
                    if direction == 'abs' and abs(ch) < btc_thr:
                        continue
                    up_btc_total += 1
                    # 향후 forward_bars 30분봉 안에 다른 코인에서 펌프가 발생?
                    found = False
                    for j in range(forward_bars + 1):
                        check_ts = ts + j * 30 * 60_000
                        if check_ts in all_pump_ts:
                            found = True
                            break
                    if found:
                        up_btc_with_pump += 1
                if up_btc_total >= 10:
                    rate = up_btc_with_pump / up_btc_total * 100
                    print(f'  BTC {direction:<4} >={btc_thr}% in 30m → pump in next {forward_bars*30}m: '
                          f'{up_btc_with_pump:>4}/{up_btc_total:>4} = {rate:>5.1f}%')

    # 베이스 레이트
    total_btc_candles = len(btc_changes)
    base_pumps = 0
    for ts in btc_changes:
        for j in range(9):  # 4h forward
            if ts + j * 30 * 60_000 in all_pump_ts:
                base_pumps += 1
                break
    base_rate = base_pumps / total_btc_candles * 100
    print(f'\nBase pump-in-4h rate (any BTC candle): {base_rate:.1f}% ({base_pumps}/{total_btc_candles})')


if __name__ == '__main__':
    main()
