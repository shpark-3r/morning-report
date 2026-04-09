"""
Phase 2 v2: 펌프 dedupe + 다양한 lookback + "진짜 사전 신호" 강제

핵심 변경:
1. 펌프 dedupe: 같은 코인의 한 펌프 클러스터를 1건으로 (연속 펌프 캔들 → 첫 시작점만)
2. 사전 신호 lookback 확장: 5/15/30/60분
3. **진짜 사전 강제**: 진입 시점 직전 5분의 momentum < 5% (즉 아직 가격 안 움직임) 필터 추가
4. 펌프 시작 추정: future_max를 만든 봉 시점 - lookback 안에서 가격이 안 움직였어야 진짜 사전
"""
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta

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
        if len(candles) >= 200:
            coins[coin] = candles
    return coins


def find_pump_starts(candles, pump_window, pump_threshold, dedupe_minutes=60):
    """
    펌프 클러스터의 '시작점'만 찾기.
    pump_start: 정의된 윈도우 내 +threshold% 도달했고, 직전 dedupe_minutes 안에 다른 펌프 시작이 없는 캔들.

    추가 조건 (진짜 사전):
      - 시작점 직전 5분 모멘텀이 작았어야 함 (< 10%)
      - 즉, 펌프 진행 중인 캔들은 시작점에서 제외
    """
    n = len(candles)
    pump_starts = []  # list of (i, gain)
    last_pump_i = -1000

    for i in range(5, n - pump_window):
        c_now = candles[i][2]
        if c_now <= 0:
            continue
        # 직전 5분 모멘텀
        c_prev5 = candles[i - 5][2]
        if c_prev5 <= 0:
            continue
        mom_prev5 = (c_now - c_prev5) / c_prev5 * 100
        if mom_prev5 >= 10:  # 이미 움직이고 있음 → 사전이 아님
            continue

        # 미래 윈도우
        future_max = max(candles[j][3] for j in range(i + 1, i + 1 + pump_window))
        gain = (future_max - c_now) / c_now * 100
        if gain >= pump_threshold:
            # dedupe: 직전 펌프 시작에서 일정 분 이상 떨어져야
            if i - last_pump_i >= dedupe_minutes:
                pump_starts.append((i, gain))
                last_pump_i = i

    return pump_starts


def compute_signals(candles, i, lookback_minutes):
    """시점 i에서 직전 lookback_minutes 동안의 사전 신호."""
    K = lookback_minutes
    BASE = 60  # 기준선: 그 이전 60봉
    if i < K + BASE:
        return None
    # vol_ratio: K봉 평균 vs BASE봉 평균
    vol_K = sum(candles[j][5] for j in range(i - K, i)) / K
    vol_base = sum(candles[j][5] for j in range(i - K - BASE, i - K)) / BASE
    if vol_base <= 0:
        return None
    vol_ratio = vol_K / vol_base

    # trade value
    tv_K = sum(candles[j][2] * candles[j][5] for j in range(i - K, i))

    # 모멘텀
    c_start = candles[i - K][2]
    c_end = candles[i - 1][2]
    if c_start <= 0:
        return None
    momentum = (c_end - c_start) / c_start * 100

    # 연속 양봉 비율
    consec_up = sum(1 for j in range(i - K, i) if candles[j][2] > candles[j][1]) / K

    return {
        'vol_ratio': vol_ratio,
        'trade_value': tv_K,
        'momentum': momentum,
        'consec_up': consec_up,
    }


def analyze(coins, pump_window, pump_threshold, lookback):
    """모든 코인에서 (모든 검사 가능한 캔들 × 펌프 시작점) 수집"""
    all_samples = []  # 모든 검사 가능 캔들
    pump_start_set = set()  # (coin, i)

    for coin, candles in coins.items():
        # 펌프 시작점
        pumps = find_pump_starts(candles, pump_window, pump_threshold)
        for i, gain in pumps:
            pump_start_set.add((coin, i))

        # 모든 검사 가능 캔들에 대해 사전 신호 측정
        n = len(candles)
        for i in range(lookback + 60, n - pump_window):
            # 진짜 사전 강제: 직전 5분 momentum < 10%
            c_now = candles[i][2]
            c_prev5 = candles[i - 5][2]
            if c_prev5 <= 0 or c_now <= 0:
                continue
            mom5 = (c_now - c_prev5) / c_prev5 * 100
            if mom5 >= 10:
                continue

            sig = compute_signals(candles, i, lookback)
            if sig is None:
                continue
            sig['coin'] = coin
            sig['i'] = i
            sig['ts'] = candles[i][0]
            sig['is_pump_start'] = (coin, i) in pump_start_set
            # future
            future_max = max(candles[j][3] for j in range(i + 1, i + 1 + pump_window))
            sig['future_gain_pct'] = (future_max - c_now) / c_now * 100
            all_samples.append(sig)

    return all_samples, pump_start_set


def grid_search(samples):
    vol_grid = [2, 3, 5, 10, 20, 50, 100]
    tv_grid = [0, 5e6, 20e6, 100e6]
    mom_grid = [-100, 0, 3]  # 너무 큰 mom는 진짜 사전 강제와 충돌

    rows = []
    for vr in vol_grid:
        for tv in tv_grid:
            for mom in mom_grid:
                cond = lambda s, vr=vr, tv=tv, mom=mom: (
                    s['vol_ratio'] >= vr and s['trade_value'] >= tv and s['momentum'] >= mom
                )
                n_total = len(samples)
                n_signal = 0
                n_tp = 0
                n_pump = 0
                for s in samples:
                    if s['is_pump_start']:
                        n_pump += 1
                    if cond(s):
                        n_signal += 1
                        if s['is_pump_start']:
                            n_tp += 1
                rows.append({
                    'label': f'vol>={vr}x, tv>={tv/1e6:.0f}M, mom>={mom}%',
                    'n_signal': n_signal,
                    'n_tp': n_tp,
                    'n_pump': n_pump,
                    'precision': n_tp / n_signal if n_signal else 0,
                    'recall': n_tp / n_pump if n_pump else 0,
                    'vr': vr, 'tv': tv, 'mom': mom,
                })
    return rows


def main():
    pump_window = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    pump_threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 50
    lookback = int(sys.argv[3]) if len(sys.argv) > 3 else 30  # 직전 N분

    print(f'Loading 1m candles...')
    coins = load_candles('data/bithumb_1m')
    print(f'Loaded {len(coins)} coins')
    print(f'Pump: +{pump_threshold}% within {pump_window}min, lookback={lookback}min')
    print(f'Constraint: pre-entry 5min momentum < 10% (real precursor)')

    samples, pump_starts = analyze(coins, pump_window, pump_threshold, lookback)
    n_total = len(samples)
    n_pump = sum(1 for s in samples if s['is_pump_start'])
    print(f'\nSamples (after pre-momentum filter): {n_total:,}')
    print(f'Pump starts (deduped): {n_pump}')
    if n_total:
        print(f'Base rate: {n_pump/n_total*100:.4f}%')

    # 펌프 시작점의 사전 신호 분포
    pumps = [s for s in samples if s['is_pump_start']]
    nonpumps = [s for s in samples if not s['is_pump_start']]

    if pumps:
        print(f'\nPump-start precursor stats (n={len(pumps)}):')
        for key in ['vol_ratio', 'trade_value', 'momentum', 'consec_up']:
            vals = sorted(s[key] for s in pumps)
            p25 = vals[len(vals) // 4]
            p50 = vals[len(vals) // 2]
            p75 = vals[len(vals) * 3 // 4]
            p90 = vals[len(vals) * 9 // 10]
            print(f'  {key:>12}: p25={p25:>10.2f} p50={p50:>10.2f} p75={p75:>10.2f} p90={p90:>10.2f}')
    if nonpumps:
        print(f'\nNon-pump precursor stats (n={len(nonpumps):,}):')
        for key in ['vol_ratio', 'trade_value', 'momentum', 'consec_up']:
            vals = sorted(s[key] for s in nonpumps)
            p50 = vals[len(vals) // 2]
            p90 = vals[len(vals) * 9 // 10]
            print(f'  {key:>12}: p50={p50:>10.2f} p90={p90:>10.2f}')

    # Grid search
    print(f'\n{"="*100}')
    print(f'Grid search (precision sorted, top 25, n_signal >= 3)')
    print(f'{"="*100}')
    print(f'{"filter":<48} {"n_sig":>8} {"n_tp":>6} {"prec":>8} {"recall":>8}')
    print('-' * 100)

    rows = grid_search(samples)
    rows = [r for r in rows if r['n_signal'] >= 3]
    rows.sort(key=lambda r: -r['precision'])
    for r in rows[:25]:
        print(f'{r["label"]:<48} {r["n_signal"]:>8} {r["n_tp"]:>6} {r["precision"]*100:>7.2f}% {r["recall"]*100:>7.2f}%')

    # Top filter의 실제 적중 케이스
    if rows:
        top = rows[0]
        cond = lambda s, vr=top['vr'], tv=top['tv'], mom=top['mom']: (
            s['vol_ratio'] >= vr and s['trade_value'] >= tv and s['momentum'] >= mom
        )
        hits = [s for s in samples if cond(s)]
        hits.sort(key=lambda s: -s['vol_ratio'])
        print(f'\nTop filter: {top["label"]}')
        print(f'  n_signal={top["n_signal"]}, precision={top["precision"]*100:.2f}%')
        print(f'  Sample hits:')
        for s in hits[:20]:
            ts = datetime.fromtimestamp(s['ts'] / 1000, KST)
            marker = '** PUMP**' if s['is_pump_start'] else '   miss  '
            print(f'  {marker} {s["coin"]:>10} {ts:%m-%d %H:%M} vr={s["vol_ratio"]:>6.1f} tv={s["trade_value"]/1e6:>6.1f}M mom={s["momentum"]:>+5.1f}% future={s["future_gain_pct"]:>+5.1f}%')

    out = f'pump_precursor_v2_w{pump_window}_t{int(pump_threshold)}_lb{lookback}.json'
    with open(out, 'w') as f:
        json.dump({
            'pump_window': pump_window,
            'pump_threshold': pump_threshold,
            'lookback': lookback,
            'n_total': n_total,
            'n_pump_starts': n_pump,
            'top_filters': rows[:30],
        }, f, indent=2, ensure_ascii=False)
    print(f'\nSaved {out}')


if __name__ == '__main__':
    main()
