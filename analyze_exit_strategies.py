"""
Phase C: 출구 규율 시뮬레이션.

신호: 3일 lookback macro pattern (cv<=any, log_tv>=10, vol_trend>=5x, bar<=0.5)
진입: 신호 발생 캔들 다음 봉 시가
시뮬: 다양한 TP/SL/Time exit으로 청산 → EV 측정

목표:
- per-trade EV (평균 수익률)
- 일별 자본 운용 시뮬: 매일 K개 신호 진입, 자본 N% 베팅
- 최종 자본 분포

실용 전제:
- 슬리피지 0.3% 양쪽 (시장가 진입/청산)
- 수수료 0.04% 양쪽 (빗썸 일반 수수료)
"""
import json
import os
import sys
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

SLIPPAGE = 0.003  # 0.3%
FEE = 0.0004  # 0.04% × 2 = 0.08% per round trip


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
                o = float(row[1]); c = float(row[2]); h = float(row[3]); l = float(row[4]); v = float(row[5])
                candles.append((ts, o, c, h, l, v))
            except (ValueError, IndexError):
                continue
        if len(candles) >= 200:
            coins[coin] = candles
    return coins


def find_signals(coins, lookback_bars=144):
    """3일 lookback 매크로 신호 찾기"""
    signals = []  # list of (coin, i, ts)

    for coin, candles in coins.items():
        n = len(candles)
        for i in range(lookback_bars + 10, n - 10):
            window = candles[i - lookback_bars:i]
            closes = [x[2] for x in window]
            vols = [x[5] for x in window]
            tvs = [x[2] * x[5] for x in window]
            highs = [x[3] for x in window]
            lows = [x[4] for x in window]

            if not closes or sum(closes) == 0:
                continue

            sum_tv = sum(tvs)
            if sum_tv <= 0:
                continue
            log_tv = math.log10(sum_tv)
            if log_tv < 10:  # 1억 KRW 미만 누적이면 skip
                continue

            half = lookback_bars // 2
            vol_first = sum(vols[:half]) / half
            vol_second = sum(vols[half:]) / (lookback_bars - half)
            if vol_first <= 0:
                continue
            vol_trend = vol_second / vol_first
            if vol_trend < 5.0:
                continue

            # max bar range filter
            max_bar = 0
            for x in window:
                if x[1] > 0:
                    r = (x[3] - x[4]) / x[1]
                    if r > max_bar:
                        max_bar = r
            if max_bar > 0.5:
                continue

            signals.append({
                'coin': coin,
                'i': i,
                'ts': candles[i][0],
                'vol_trend': vol_trend,
                'log_tv': log_tv,
            })

    return signals


def simulate_exit(candles, entry_i, tp_pct, sl_pct, max_hold_bars):
    """
    신호 캔들 i에서 다음 봉 시가로 진입.
    이후 max_hold_bars 봉 동안 관찰:
      - high >= entry * (1+tp): TP 청산 (tp_pct에서 -슬리피지)
      - low <= entry * (1-sl): SL 청산 (-sl에서 -슬리피지)
      - 시간 만료: 마지막 봉 종가에서 청산
    Returns: gross_pct (수수료/슬리피지 차감 전)
    """
    if entry_i + 1 >= len(candles):
        return None
    entry_price = candles[entry_i + 1][1]  # 다음 봉 시가
    if entry_price <= 0:
        return None

    tp_price = entry_price * (1 + tp_pct / 100)
    sl_price = entry_price * (1 - sl_pct / 100)

    end_i = min(entry_i + 1 + max_hold_bars, len(candles))
    for j in range(entry_i + 1, end_i):
        h = candles[j][3]
        l = candles[j][4]
        # 보수적: 같은 봉에 SL/TP 다 닿으면 SL 우선 (worst case)
        if l <= sl_price:
            return -sl_pct
        if h >= tp_price:
            return tp_pct
    # 시간 만료
    last_close = candles[end_i - 1][2]
    return (last_close - entry_price) / entry_price * 100


def apply_costs(gross_pct):
    """슬리피지 + 수수료 차감 (양쪽 합)"""
    return gross_pct - (SLIPPAGE * 2 + FEE * 2) * 100


def main():
    coins = load_candles('data/bithumb_30m')
    print(f'Loaded {len(coins)} coins')

    print('Finding macro signals (3-day lookback, log_tv>=10, vol_trend>=5x, max_bar<=50%)...')
    signals = find_signals(coins, lookback_bars=144)
    print(f'Total signals: {len(signals)}')

    # Dedupe: 같은 코인의 인접 8봉(=4시간) 신호는 첫 1건만
    signals.sort(key=lambda s: (s['coin'], s['i']))
    deduped = []
    last_coin = None
    last_i = -1000
    for s in signals:
        if s['coin'] != last_coin or s['i'] - last_i >= 8:
            deduped.append(s)
            last_coin = s['coin']
            last_i = s['i']
    print(f'After dedupe (4h cluster): {len(deduped)} signals')

    # 다양한 exit 전략
    strategies = [
        # (tp, sl, max_hold_bars)
        ('TP10/SL3/4h', 10, 3, 8),
        ('TP15/SL3/4h', 15, 3, 8),
        ('TP20/SL3/4h', 20, 3, 8),
        ('TP30/SL3/4h', 30, 3, 8),
        ('TP50/SL3/4h', 50, 3, 8),
        ('TP10/SL5/4h', 10, 5, 8),
        ('TP20/SL5/4h', 20, 5, 8),
        ('TP30/SL5/4h', 30, 5, 8),
        ('TP10/SL3/8h', 10, 3, 16),
        ('TP20/SL3/8h', 20, 3, 16),
        ('TP30/SL3/8h', 30, 3, 16),
        ('TP50/SL5/8h', 50, 5, 16),
        ('TP10/SL3/12h', 10, 3, 24),
        ('TP20/SL3/12h', 20, 3, 24),
        ('TP100/SL3/12h', 100, 3, 24),
    ]

    print(f'\n{"strategy":<18} {"n":>5} {"win%":>7} {"avg":>9} {"med":>9} {"net":>9} {"max":>9} {"min":>9}  EV/trade')
    print('-' * 110)

    results = {}
    for name, tp, sl, hold in strategies:
        gross_pcts = []
        for s in deduped:
            candles = coins[s['coin']]
            r = simulate_exit(candles, s['i'], tp, sl, hold)
            if r is not None:
                gross_pcts.append(r)

        if not gross_pcts:
            continue

        net_pcts = [apply_costs(g) for g in gross_pcts]
        n = len(net_pcts)
        wins = sum(1 for x in net_pcts if x > 0)
        win_rate = wins / n
        avg = sum(net_pcts) / n
        med = sorted(net_pcts)[n // 2]
        mx = max(net_pcts)
        mn = min(net_pcts)

        results[name] = {
            'n': n, 'win_rate': win_rate, 'avg_net': avg,
            'gross_pcts': gross_pcts, 'net_pcts': net_pcts,
        }

        print(f'{name:<18} {n:>5} {win_rate*100:>6.1f}% {sum(gross_pcts)/n:>+8.2f}% {med:>+8.2f}% {avg:>+8.2f}% {mx:>+8.2f}% {mn:>+8.2f}%  {avg:>+5.2f}%')

    # Best strategy 기준으로 일별 분포
    if results:
        best_name = max(results.keys(), key=lambda k: results[k]['avg_net'])
        print(f'\n=== Best strategy: {best_name} (EV {results[best_name]["avg_net"]:+.2f}%/trade) ===')
        best = results[best_name]
        net_pcts = best['net_pcts']

        # 일별 EV
        daily_pnl = defaultdict(list)
        for s, net in zip(deduped, net_pcts):
            dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
            daily_pnl[dt.date()].append(net)

        print(f'\nDaily PnL distribution (best strategy):')
        days_sorted = sorted(daily_pnl.keys())
        daily_sums = []
        for day in days_sorted:
            trades = daily_pnl[day]
            day_sum_eq_pct = sum(trades) / max(len(trades), 1)  # 매일 균등 분배
            daily_sums.append((day, len(trades), day_sum_eq_pct, sum(trades)))

        # 자본 운용 시뮬: 매일 모든 신호에 자본 K%씩 베팅
        for K in [5, 10, 20, 50]:
            print(f'\n--- Capital sim: bet {K}% per signal, daily compounding ---')
            cap = 1.0
            for day, n, _, day_sum in daily_sums[:30]:
                # day_sum = 모든 트레이드의 net% 합
                # K% 베팅이면 자본 변화 = K/100 × day_sum/100 (per trade)
                day_change = (K / 100) * sum(daily_pnl[day]) / 100
                cap *= (1 + day_change)
            print(f'  After {min(30, len(daily_sums))} days: cap = {cap:.3f} ({(cap-1)*100:+.1f}%)')

        # 일별 자세히
        print(f'\nFull daily breakdown:')
        for day, n, avg, total in daily_sums:
            bar = '+' if total >= 0 else '-'
            print(f'  {day}  n={n:>2}  total={total:>+7.1f}%  avg={avg:>+6.2f}%')

    out = {
        'n_signals': len(deduped),
        'strategies': {k: {'n': v['n'], 'win_rate': v['win_rate'], 'avg_net': v['avg_net']} for k, v in results.items()},
    }
    with open('exit_strategies.json', 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print('\nSaved exit_strategies.json')


if __name__ == '__main__':
    main()
