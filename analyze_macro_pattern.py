"""
Phase B: 30분봉 매크로 패턴 분석.

작전주 패턴 가설:
  N일간 박스권 → 거래량 점진 누적 → 폭발

지표 (펌프 시작 직전 7일/14일):
  1. 가격 변동성: std(close[-N*48:]) / mean(close[-N*48:])  ← 박스권일수록 작음
  2. 가격 트렌드: (close[-1] - close[-N*48]) / close[-N*48]
  3. 거래량 트렌드: (mean(vol[-N*48:-N*24]) → mean(vol[-N*24:])) ratio
  4. 거래량 절대 누적: log(sum(close*vol)[-N*48:])  ← 작은 코인 vs 큰 코인 구분
  5. 거래일수: 7일 중 거래량 0 아닌 일수 (작은 코인 필터)
  6. 최대 단일 캔들 변동: max((high-low)/open) over lookback (이미 한 번 펌프했는지)

방법:
  1. 펌프 시작점 109개 (1h +50%, dedupe 4h)
  2. 각 시작점 -lookback ~ -1봉 패턴 측정
  3. 비교군: 같은 코인 비펌프 시점 100개 무작위
  4. 분포 비교 + classifier
"""
import json
import os
import sys
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
random.seed(42)


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
        if len(candles) >= 500:
            coins[coin] = candles
    return coins


def find_pump_starts(candles, window=2, threshold=50, dedupe=8):
    """30분봉 펌프 시작점. window=2 → 1시간."""
    pumps = []
    last_i = -1000
    n = len(candles)
    for i in range(n - window):
        c = candles[i][2]
        if c <= 0:
            continue
        future_max = max(candles[j][3] for j in range(i + 1, i + 1 + window))
        gain = (future_max - c) / c * 100
        if gain >= threshold and i - last_i >= dedupe:
            pumps.append((i, gain))
            last_i = i
    return pumps


def compute_macro_features(candles, i, lookback_bars):
    """시점 i 직전 lookback_bars개 봉의 매크로 패턴."""
    if i < lookback_bars + 10:
        return None
    window = candles[i - lookback_bars:i]
    closes = [x[2] for x in window]
    vols = [x[5] for x in window]
    tvs = [x[2] * x[5] for x in window]
    highs = [x[3] for x in window]
    lows = [x[4] for x in window]

    if not closes or all(c == 0 for c in closes):
        return None

    mean_close = sum(closes) / len(closes)
    if mean_close <= 0:
        return None
    std_close = statistics.pstdev(closes)
    cv = std_close / mean_close  # coefficient of variation

    # trend
    if closes[0] > 0:
        price_trend = (closes[-1] - closes[0]) / closes[0]
    else:
        return None

    # vol trend: 후반 절반 / 전반 절반
    half = lookback_bars // 2
    vol_first = sum(vols[:half]) / half if half else 0
    vol_second = sum(vols[half:]) / (lookback_bars - half) if half else 0
    vol_trend = vol_second / vol_first if vol_first > 0 else 0

    # 누적 거래액
    sum_tv = sum(tvs)
    log_tv = 0
    if sum_tv > 0:
        import math
        log_tv = math.log10(sum_tv)

    # 최대 단일 봉 변동
    max_bar_range = 0
    for x in window:
        o = x[1]
        if o > 0:
            r = (x[3] - x[4]) / o
            if r > max_bar_range:
                max_bar_range = r

    # 거래량이 0인 봉 비율
    zero_vol = sum(1 for v in vols if v == 0) / len(vols)

    return {
        'cv': cv,                      # 박스권: 작을수록 저변동
        'price_trend': price_trend,    # 누적 가격 변동
        'vol_trend': vol_trend,        # 후반/전반 거래량 비
        'log_tv': log_tv,              # 코인 크기 대용
        'max_bar_range': max_bar_range,  # 직전 큰 봉
        'zero_vol_ratio': zero_vol,
    }


def analyze(coins, lookback_bars=336, sample_per_coin=50):
    """
    lookback_bars=336 → 30분 × 336 = 168시간 = 7일
    """
    pump_features = []  # 펌프 직전 패턴
    nonpump_features = []  # 비펌프 무작위 시점 패턴

    for coin, candles in coins.items():
        n = len(candles)
        pumps = find_pump_starts(candles)
        pump_indices = set(i for i, _ in pumps)

        # 펌프 시작점 패턴
        for i, gain in pumps:
            f = compute_macro_features(candles, i, lookback_bars)
            if f is None:
                continue
            f['coin'] = coin
            f['i'] = i
            f['ts'] = candles[i][0]
            f['gain'] = gain
            f['is_pump'] = True
            pump_features.append(f)

        # 비펌프 무작위 시점
        valid_range = list(range(lookback_bars + 10, n - 5))
        valid_range = [i for i in valid_range if i not in pump_indices]
        if len(valid_range) > sample_per_coin:
            sampled = random.sample(valid_range, sample_per_coin)
        else:
            sampled = valid_range
        for i in sampled:
            f = compute_macro_features(candles, i, lookback_bars)
            if f is None:
                continue
            f['coin'] = coin
            f['i'] = i
            f['ts'] = candles[i][0]
            f['is_pump'] = False
            nonpump_features.append(f)

    return pump_features, nonpump_features


def percentiles(values, ps=(0.1, 0.25, 0.5, 0.75, 0.9)):
    if not values:
        return [0] * len(ps)
    s = sorted(values)
    return [s[min(int(p * len(s)), len(s) - 1)] for p in ps]


def main():
    lookback_bars = int(sys.argv[1]) if len(sys.argv) > 1 else 336  # 7일
    print(f'Macro pattern analysis: lookback={lookback_bars} bars = {lookback_bars * 30 / 60 / 24:.1f} days')

    coins = load_candles('data/bithumb_30m')
    print(f'Loaded {len(coins)} coins')

    pumps, nonpumps = analyze(coins, lookback_bars=lookback_bars)
    print(f'Pump features: {len(pumps)}')
    print(f'Non-pump features: {len(nonpumps)}')

    if not pumps or not nonpumps:
        print('Not enough data')
        return

    # 분포 비교
    keys = ['cv', 'price_trend', 'vol_trend', 'log_tv', 'max_bar_range', 'zero_vol_ratio']
    print(f'\n{"feature":>16} {"pump_p25":>10} {"pump_p50":>10} {"pump_p75":>10} | {"nonpump_p25":>13} {"nonpump_p50":>13} {"nonpump_p75":>13}')
    print('-' * 110)
    for k in keys:
        p_vals = [x[k] for x in pumps]
        np_vals = [x[k] for x in nonpumps]
        pp = percentiles(p_vals)
        npp = percentiles(np_vals)
        print(f'{k:>16} {pp[1]:>10.4f} {pp[2]:>10.4f} {pp[3]:>10.4f} | {npp[1]:>13.4f} {npp[2]:>13.4f} {npp[3]:>13.4f}')

    # Grid search: 작전주 가설 (저변동 + 큰 거래량 + 거래량 증가)
    print(f'\n{"=" * 110}')
    print(f'Grid search (lookback={lookback_bars} bars / {lookback_bars * 30 / 60 / 24:.1f} days)')
    print(f'{"=" * 110}')
    print(f'{"filter":<70} {"n_sig":>8} {"n_tp":>6} {"prec":>8} {"recall":>8} {"lift":>6}')
    print('-' * 110)

    cv_grid = [0.05, 0.10, 0.20, 1.0]  # 1.0 = 제약 없음
    log_tv_grid = [0, 8, 9, 10]  # 10^8 = 1억 KRW 누적
    vol_trend_grid = [0, 1.0, 2.0, 5.0]
    bar_range_grid = [0, 0.5, 1.0]  # 직전 큰 봉 없음

    base_pump_rate = len(pumps) / (len(pumps) + len(nonpumps))

    rows = []
    all_samples = pumps + nonpumps
    for cv_max in cv_grid:
        for log_tv_min in log_tv_grid:
            for vt_min in vol_trend_grid:
                for br_max in bar_range_grid:
                    cond = lambda s, cv_max=cv_max, log_tv_min=log_tv_min, vt_min=vt_min, br_max=br_max: (
                        s['cv'] <= cv_max and s['log_tv'] >= log_tv_min
                        and s['vol_trend'] >= vt_min
                        and s['max_bar_range'] <= br_max if br_max < 1.0 else
                        (s['cv'] <= cv_max and s['log_tv'] >= log_tv_min and s['vol_trend'] >= vt_min)
                    )
                    n_sig = sum(1 for s in all_samples if cond(s))
                    n_tp = sum(1 for s in all_samples if cond(s) and s['is_pump'])
                    if n_sig < 5:
                        continue
                    prec = n_tp / n_sig
                    recall = n_tp / len(pumps)
                    lift = prec / base_pump_rate if base_pump_rate else 0
                    rows.append({
                        'label': f'cv<={cv_max}, log_tv>={log_tv_min}, vol_trend>={vt_min}, bar<={br_max if br_max < 1.0 else "any"}',
                        'n_sig': n_sig, 'n_tp': n_tp, 'prec': prec, 'recall': recall, 'lift': lift,
                    })

    rows.sort(key=lambda r: -r['lift'])
    for r in rows[:25]:
        print(f'{r["label"]:<70} {r["n_sig"]:>8} {r["n_tp"]:>6} {r["prec"]*100:>7.2f}% {r["recall"]*100:>7.2f}% {r["lift"]:>5.2f}x')

    print(f'\n[Base pump rate]: {base_pump_rate*100:.2f}% (in this sampled comparison set)')
    print(f'Note: lift = precision / base_rate. lift > 1 = signal에 알파 있음')

    out = {
        'lookback_bars': lookback_bars,
        'lookback_days': lookback_bars * 30 / 60 / 24,
        'n_pumps': len(pumps),
        'n_nonpumps': len(nonpumps),
        'top_filters': rows[:30],
    }
    with open(f'macro_pattern_lb{lookback_bars}.json', 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print(f'\nSaved macro_pattern_lb{lookback_bars}.json')


if __name__ == '__main__':
    main()
