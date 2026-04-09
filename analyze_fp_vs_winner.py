"""
False positive 13건 vs Winner 18건 비교 분석.
공통 차이점 찾아 추가 필터 도출.

지표:
- vol_ratio_5
- tv_5min
- triggered_lookback (5/10/15/30)
- triggered_gain
- 시간대
- 직전 30분 변동성
- 직전 30분 누적 가격 변화
- 신호 봉 캔들 모양 (양봉 크기)
- 신호 발생 직전 BTC 변화
"""
import json
import os
import statistics
from collections import Counter
from datetime import datetime, timezone, timedelta
from analyze_adaptive_trailing import simulate_adaptive_trailing
from analyze_realistic_simulation import load_candles_1m, find_adaptive_signals, apply_costs

KST = timezone(timedelta(hours=9))


def enrich_signal(coins, s, btc_30m=None):
    """signal에 추가 메타 붙이기"""
    candles = coins[s['coin']]
    i = s['i']
    if i < 35:
        return None

    # 기본 metric들
    tv_5 = sum(candles[j][2] * candles[j][5] for j in range(i - 5, i))
    past_5_vol = sum(candles[j][5] for j in range(i - 5, i))
    base_30 = sum(candles[j][5] for j in range(i - 35, i - 5)) / 30
    vol_ratio_5 = (past_5_vol / 5) / base_30 if base_30 > 0 else 0

    # 신호의 cumulative gain 측정
    close_now = candles[i][2]
    gains = {}
    for lb in [5, 10, 15, 30]:
        if i >= lb:
            sc = candles[i - lb][2]
            if sc > 0:
                gains[lb] = (close_now - sc) / sc * 100
    triggered_lb = None
    for lb_min, min_gain in [(5, 5), (10, 7), (15, 10), (30, 15)]:
        if lb_min in gains and gains[lb_min] >= min_gain:
            triggered_lb = lb_min
            break

    # 직전 30분 변동성 (close 기준 std/mean)
    closes = [candles[j][2] for j in range(i - 30, i)]
    mean_c = sum(closes) / len(closes)
    std_c = statistics.pstdev(closes) if len(closes) > 1 else 0
    cv_30 = std_c / mean_c if mean_c > 0 else 0

    # 직전 30분 누적 가격 (이미 펌프 진행 중이었나)
    if closes[0] > 0:
        cum_30 = (close_now - closes[0]) / closes[0] * 100
    else:
        cum_30 = 0

    # 신호 봉 자체의 양봉 크기
    o, c = candles[i][1], candles[i][2]
    bar_gain = (c - o) / o * 100 if o > 0 else 0

    # 신호 봉의 high - close (얼마나 위로 갔다가 내려왔나)
    h = candles[i][3]
    upper_wick = (h - c) / c * 100 if c > 0 else 0

    # 시간대
    dt = datetime.fromtimestamp(candles[i][0] / 1000, KST)

    return {
        **s,
        'tv_5': tv_5,
        'vol_ratio_5': vol_ratio_5,
        'triggered_lb': triggered_lb,
        'triggered_gain': gains.get(triggered_lb, 0) if triggered_lb else 0,
        'cv_30': cv_30,
        'cum_30': cum_30,
        'bar_gain': bar_gain,
        'upper_wick': upper_wick,
        'hour': dt.hour,
        'minute': dt.minute,
        'dt': dt,
    }


def main():
    coins = load_candles_1m()
    print(f'Loaded {len(coins)} coins')

    sigs = find_adaptive_signals(coins)
    enriched_all = []
    for s in sigs:
        e = enrich_signal(coins, s)
        if e:
            enriched_all.append(e)

    # Strict filter
    strict = [s for s in enriched_all if s['tv_5'] >= 200e6 and s['vol_ratio_5'] >= 10]
    print(f'Strict signals: {len(strict)}')

    # 각 시뮬 결과 (D tight lock)
    stages_D = [(5, 4, 2), (10, 3, 6), (20, 2, 15), (35, 1.5, 28)]
    for s in strict:
        r = simulate_adaptive_trailing(coins[s['coin']], s['i'] + 1, stages_D, 5, 60)
        s['result'] = r if r is not None else 0

    winners = [s for s in strict if s['result'] > 0]
    losers = [s for s in strict if s['result'] <= 0]
    print(f'Winners: {len(winners)} ({len(winners)/len(strict)*100:.0f}%)')
    print(f'Losers:  {len(losers)} ({len(losers)/len(strict)*100:.0f}%)')

    # === 분포 비교 ===
    print(f'\n{"":<25} {"winner_p25":>12} {"winner_p50":>12} {"winner_p75":>12} {"loser_p25":>12} {"loser_p50":>12} {"loser_p75":>12}')
    print('-' * 110)
    keys = ['tv_5', 'vol_ratio_5', 'triggered_gain', 'cv_30', 'cum_30', 'bar_gain', 'upper_wick']

    def pct(values, p):
        if not values:
            return 0
        s = sorted(values)
        return s[min(int(p * len(s)), len(s) - 1)]

    for k in keys:
        wv = [s[k] for s in winners]
        lv = [s[k] for s in losers]
        if k == 'tv_5':
            print(f'{k:<25} {pct(wv,0.25)/1e6:>11.0f}M {pct(wv,0.5)/1e6:>11.0f}M {pct(wv,0.75)/1e6:>11.0f}M {pct(lv,0.25)/1e6:>11.0f}M {pct(lv,0.5)/1e6:>11.0f}M {pct(lv,0.75)/1e6:>11.0f}M')
        else:
            print(f'{k:<25} {pct(wv,0.25):>12.2f} {pct(wv,0.5):>12.2f} {pct(wv,0.75):>12.2f} {pct(lv,0.25):>12.2f} {pct(lv,0.5):>12.2f} {pct(lv,0.75):>12.2f}')

    # === 시간대 분포 ===
    print(f'\n=== Hour distribution ===')
    win_hours = Counter(s['hour'] for s in winners)
    los_hours = Counter(s['hour'] for s in losers)
    for h in range(24):
        if win_hours[h] or los_hours[h]:
            print(f'  {h:02d}시: win={win_hours[h]:>2}, loss={los_hours[h]:>2}')

    # === 가설들 ===
    print(f'\n=== Hypothesis tests ===')

    # H1: cum_30 (이미 펌프 진행 중)
    for thr in [5, 10, 15, 20, 30]:
        wp = sum(1 for s in winners if s['cum_30'] < thr) / len(winners) if winners else 0
        lp = sum(1 for s in losers if s['cum_30'] < thr) / len(losers) if losers else 0
        print(f'  cum_30 < {thr}%: winners {wp*100:.0f}%, losers {lp*100:.0f}%')

    # H2: bar_gain (신호 봉이 양봉이지만 너무 큰 양봉이면 끝물?)
    for thr in [3, 5, 7, 10]:
        wp = sum(1 for s in winners if s['bar_gain'] < thr) / len(winners) if winners else 0
        lp = sum(1 for s in losers if s['bar_gain'] < thr) / len(losers) if losers else 0
        print(f'  bar_gain < {thr}%: winners {wp*100:.0f}%, losers {lp*100:.0f}%')

    # H3: triggered_lb (5분 vs 30분)
    print(f'\n  Triggered lookback distribution:')
    win_lb = Counter(s['triggered_lb'] for s in winners)
    los_lb = Counter(s['triggered_lb'] for s in losers)
    for lb in [5, 10, 15, 30]:
        print(f'    {lb}min: win={win_lb[lb]}, loss={los_lb[lb]}')

    # H4: vol_ratio
    for thr in [10, 20, 30, 50, 100]:
        wp = sum(1 for s in winners if s['vol_ratio_5'] >= thr)
        lp = sum(1 for s in losers if s['vol_ratio_5'] >= thr)
        print(f'  vol_ratio_5 >= {thr}: winners {wp}/{len(winners)}, losers {lp}/{len(losers)}')

    # H5: 시간 (밤 22-02 vs 그 외)
    night_w = sum(1 for s in winners if s['hour'] in [22, 23, 0, 1, 2])
    night_l = sum(1 for s in losers if s['hour'] in [22, 23, 0, 1, 2])
    print(f'\n  Night (22-02시): winners {night_w}/{len(winners)} ({night_w/len(winners)*100:.0f}%), losers {night_l}/{len(losers)} ({night_l/len(losers)*100:.0f}%)')

    # H6: upper wick (신호 봉의 윗꼬리 — 위로 갔다 내려옴 = 매도 압력)
    for thr in [0.5, 1, 2, 5]:
        wp = sum(1 for s in winners if s['upper_wick'] <= thr)
        lp = sum(1 for s in losers if s['upper_wick'] <= thr)
        print(f'  upper_wick <= {thr}%: winners {wp}/{len(winners)}, losers {lp}/{len(losers)}')

    # === 전체 list 비교 ===
    print(f'\n=== Detailed signal list ===')
    print(f'  {"type":<8} {"coin":>10} {"date_time":<17} {"tv_5":>6} {"vr5":>6} {"lb":>4} {"gain":>6} {"cv30":>6} {"cum30":>7} {"bar":>6} {"wick":>6}')
    for s in sorted(winners, key=lambda x: -x['result']):
        print(f'  WIN     {s["coin"]:>10} {s["dt"]:%m-%d %H:%M}     {s["tv_5"]/1e6:>5.0f}M {s["vol_ratio_5"]:>5.1f}x {s["triggered_lb"]:>3}m {s["triggered_gain"]:>+5.1f}% {s["cv_30"]:>6.3f} {s["cum_30"]:>+6.1f}% {s["bar_gain"]:>+5.1f}% {s["upper_wick"]:>+5.1f}%')
    for s in sorted(losers, key=lambda x: x['result']):
        print(f'  LOSS    {s["coin"]:>10} {s["dt"]:%m-%d %H:%M}     {s["tv_5"]/1e6:>5.0f}M {s["vol_ratio_5"]:>5.1f}x {s["triggered_lb"]:>3}m {s["triggered_gain"]:>+5.1f}% {s["cv_30"]:>6.3f} {s["cum_30"]:>+6.1f}% {s["bar_gain"]:>+5.1f}% {s["upper_wick"]:>+5.1f}%')


if __name__ == '__main__':
    main()
