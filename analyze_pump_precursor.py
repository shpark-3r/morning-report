"""
Phase 2: 펌프 사전 신호 식별.

펌프 정의: 시점 i에서 i+1~i+W 봉 사이에 high가 (1+THR/100)*close[i] 도달
  - W = 10분, 30분, 60분
  - THR = +50%, +80%

사전 신호 후보 (시점 i 직전 K봉 [i-K, i-1] 으로만 측정 — 미래 leak 없음):
  - vol_ratio_K = sum(vol[i-K..i-1]) / mean(vol[i-K-BASE..i-K-1])  (K=5, BASE=30)
  - trade_value_K = sum(close*vol)[i-K..i-1] (KRW)
  - momentum_K = (close[i-1] - close[i-K]) / close[i-K] * 100
  - consec_up_K = 직전 K봉 중 양봉 비율

베이스라인: 같은 코인의 과거 30봉 평균 거래량
같은 코인 안에서 모든 캔들에 대해 위 지표 계산 → 펌프 캔들과 비펌프 캔들 분포 비교.

목표: precision >= 30% 달성하는 신호 조합 찾기.
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import statistics

KST = timezone(timedelta(hours=9))


def load_candles(out_dir: str):
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
                o = float(row[1])
                c = float(row[2])
                h = float(row[3])
                l = float(row[4])
                v = float(row[5])
                candles.append((ts, o, c, h, l, v))
            except (ValueError, IndexError):
                continue
        if len(candles) >= 100:  # 최소 100봉
            coins[coin] = candles
    return coins


def analyze_coin(candles, pump_window, pump_threshold, lookback=5, baseline=30):
    """
    한 코인에 대해 모든 (검사 가능한) 시점에서:
      - is_pump: i+1~i+pump_window 안에 high가 +pump_threshold% 도달 여부
      - 사전 신호 4개 측정
    Returns: list of dicts
    """
    results = []
    n = len(candles)
    min_i = baseline + lookback  # 베이스라인 + 룩백 가능한 최소 인덱스
    max_i = n - pump_window  # 미래 윈도우 가능한 최대 인덱스
    if max_i <= min_i:
        return results

    for i in range(min_i, max_i):
        ts, o, c, h, l, v = candles[i]
        # 미래: i+1 ~ i+pump_window 봉의 max high
        future_max = max(candles[j][3] for j in range(i + 1, i + 1 + pump_window))
        is_pump = (future_max - c) / c * 100 >= pump_threshold if c > 0 else False

        # 과거 lookback K봉 [i-K, i-1] 의 sum vol, sum trade_value
        past_vol_sum = sum(candles[j][5] for j in range(i - lookback, i))
        past_tv_sum = sum(candles[j][2] * candles[j][5] for j in range(i - lookback, i))
        # 베이스라인: [i-K-BASE, i-K-1] 의 mean vol
        base_vol_mean = sum(candles[j][5] for j in range(i - lookback - baseline, i - lookback)) / baseline
        if base_vol_mean <= 0:
            continue
        vol_ratio = past_vol_sum / (base_vol_mean * lookback)  # K봉 평균 vs 베이스라인 평균
        # momentum
        start_close = candles[i - lookback][2]
        if start_close <= 0:
            continue
        momentum = (candles[i - 1][2] - start_close) / start_close * 100
        # consecutive up bars in lookback
        consec_up = sum(1 for j in range(i - lookback, i) if candles[j][2] > candles[j][1]) / lookback

        results.append({
            'i': i,
            'ts': ts,
            'is_pump': is_pump,
            'vol_ratio': vol_ratio,
            'trade_value': past_tv_sum,
            'momentum': momentum,
            'consec_up': consec_up,
            'future_gain_pct': (future_max - c) / c * 100,
        })
    return results


def evaluate_filter(samples, condition_fn, label):
    """주어진 condition으로 신호 친 것의 precision/recall 계산"""
    n_total = len(samples)
    n_pump = sum(1 for s in samples if s['is_pump'])
    n_signal = sum(1 for s in samples if condition_fn(s))
    n_tp = sum(1 for s in samples if condition_fn(s) and s['is_pump'])
    precision = n_tp / n_signal if n_signal > 0 else 0
    recall = n_tp / n_pump if n_pump > 0 else 0
    return {
        'label': label,
        'n_signal': n_signal,
        'n_tp': n_tp,
        'n_pump': n_pump,
        'n_total': n_total,
        'precision': precision,
        'recall': recall,
        'signal_rate': n_signal / n_total if n_total else 0,
    }


def grid_search(samples):
    """vol_ratio × trade_value × momentum 그리드"""
    vol_grid = [3, 5, 10, 20, 30, 50, 100]
    tv_grid = [0, 1e6, 5e6, 10e6, 50e6]  # KRW
    mom_grid = [-100, 0, 5, 10, 20]  # 음수 = 제약 없음

    rows = []
    for vr in vol_grid:
        for tv in tv_grid:
            for mom in mom_grid:
                cond = lambda s, vr=vr, tv=tv, mom=mom: (
                    s['vol_ratio'] >= vr and s['trade_value'] >= tv and s['momentum'] >= mom
                )
                r = evaluate_filter(samples, cond, f'vol≥{vr}x, tv≥{tv/1e6:.0f}M, mom≥{mom}%')
                rows.append(r)
    return rows


def main():
    out_dir = 'data/bithumb_1m'
    pump_window = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    pump_threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 50

    print(f'Loading 1m candles from {out_dir}/...')
    coins = load_candles(out_dir)
    print(f'Loaded {len(coins)} coins')
    print(f'Pump definition: high reaches +{pump_threshold}% within {pump_window} minutes')

    # 모든 코인에서 샘플 수집
    all_samples = []
    for coin, candles in coins.items():
        samples = analyze_coin(candles, pump_window, pump_threshold)
        for s in samples:
            s['coin'] = coin
        all_samples.extend(samples)

    n = len(all_samples)
    n_pump = sum(1 for s in all_samples if s['is_pump'])
    print(f'\nTotal samples: {n:,}')
    print(f'Pump samples: {n_pump:,} ({n_pump/n*100:.3f}%)')
    print(f'Base rate (random precision): {n_pump/n*100:.3f}%')

    # 펌프 캔들의 사전 신호 분포
    pump_samples = [s for s in all_samples if s['is_pump']]
    if pump_samples:
        print(f'\nPump precursor stats (n={len(pump_samples)}):')
        for key in ['vol_ratio', 'trade_value', 'momentum', 'consec_up']:
            vals = sorted(s[key] for s in pump_samples)
            p25 = vals[len(vals) // 4]
            p50 = vals[len(vals) // 2]
            p75 = vals[len(vals) * 3 // 4]
            p90 = vals[len(vals) * 9 // 10]
            unit = 'KRW' if key == 'trade_value' else ''
            print(f'  {key:>12}: p25={p25:>10.2f} p50={p50:>10.2f} p75={p75:>10.2f} p90={p90:>10.2f} {unit}')

    # 비펌프 캔들 분포 (비교용)
    nonpump_samples = [s for s in all_samples if not s['is_pump']]
    if nonpump_samples:
        print(f'\nNon-pump precursor stats (n={len(nonpump_samples)}):')
        for key in ['vol_ratio', 'trade_value', 'momentum', 'consec_up']:
            vals = sorted(s[key] for s in nonpump_samples)
            p25 = vals[len(vals) // 4]
            p50 = vals[len(vals) // 2]
            p75 = vals[len(vals) * 3 // 4]
            p90 = vals[len(vals) * 9 // 10]
            unit = 'KRW' if key == 'trade_value' else ''
            print(f'  {key:>12}: p25={p25:>10.2f} p50={p50:>10.2f} p75={p75:>10.2f} p90={p90:>10.2f} {unit}')

    # Grid search
    print(f'\n{"="*100}')
    print(f'Grid search (precision sorted, top 30, n_signal >= 5)')
    print(f'{"="*100}')
    print(f'{"filter":<48} {"n_sig":>8} {"n_tp":>6} {"prec":>8} {"recall":>8} {"sig_rate":>10}')
    print('-' * 100)

    rows = grid_search(all_samples)
    rows = [r for r in rows if r['n_signal'] >= 5]
    rows.sort(key=lambda r: -r['precision'])
    for r in rows[:30]:
        print(f'{r["label"]:<48} {r["n_signal"]:>8} {r["n_tp"]:>6} {r["precision"]*100:>7.2f}% {r["recall"]*100:>7.2f}% {r["signal_rate"]*100:>9.4f}%')

    # Top precision 신호의 실제 적중 케이스
    top = rows[0] if rows else None
    if top and top['precision'] > 0:
        vr_str = top['label']
        # 가장 좋은 필터 재현
        # parse: 'vol≥30x, tv≥10M, mom≥0%'
        import re
        m = re.match(r'vol≥(\d+)x, tv≥(\d+)M, mom≥(-?\d+)%', vr_str)
        if m:
            vr = int(m.group(1))
            tv = int(m.group(2)) * 1e6
            mom = int(m.group(3))
            cond = lambda s: s['vol_ratio'] >= vr and s['trade_value'] >= tv and s['momentum'] >= mom
            print(f'\nTop filter hits ({vr_str}):')
            hits = [s for s in all_samples if cond(s)]
            hits.sort(key=lambda s: -s['vol_ratio'])
            for s in hits[:20]:
                ts = datetime.fromtimestamp(s['ts'] / 1000, KST)
                marker = '★ PUMP' if s['is_pump'] else ' miss '
                print(f'  {marker} {s["coin"]:>10} {ts:%m-%d %H:%M} vr={s["vol_ratio"]:>7.1f} tv={s["trade_value"]/1e6:>6.1f}M mom={s["momentum"]:>+5.1f}% future={s["future_gain_pct"]:>+5.1f}%')

    # 저장
    summary = {
        'pump_window': pump_window,
        'pump_threshold': pump_threshold,
        'n_total': n,
        'n_pump': n_pump,
        'base_rate': n_pump / n if n else 0,
        'top_filters': rows[:30],
    }
    with open(f'pump_precursor_w{pump_window}_t{int(pump_threshold)}.json', 'w') as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f'\nSaved pump_precursor_w{pump_window}_t{int(pump_threshold)}.json')


if __name__ == '__main__':
    main()
