"""
Phase A: Binance lead-lag 검증.

가설: Binance가 빗썸보다 N초~분 먼저 움직인다.
방법:
  1. 21개 매칭 코인의 1분봉 시간 정렬
  2. lag별(0, 1, 2, 5, 10분) Binance Δprice와 빗썸 Δprice 상관관계
  3. 큰 movement (Binance |Δ|>=2%, >=5%) 케이스에서 빗썸 후속 움직임 EV
  4. 빗썸 펌프(+50% in 30min)가 발생하기 전 Binance에서 같은 코인 움직임 측정
"""
import os
import json
import pickle
import statistics
from collections import defaultdict
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
UTC = timezone.utc

BINANCE_DIR = 'C:/Users/Park/Documents/ClaudeCode/bithumb-discord-bot/binance_data/klines_cache/'
BITHUMB_DIR = 'data/bithumb_1m/'


def load_binance_1m(coin):
    """Binance pkl 파일을 dict[ts_ms_kst] = (o, c, h, l, v) 로 로드"""
    fp = os.path.join(BINANCE_DIR, f'{coin}USDT_1m.pkl')
    if not os.path.exists(fp):
        fp = os.path.join(BINANCE_DIR, f'1000{coin}USDT_1m.pkl')
        if not os.path.exists(fp):
            return None
    with open(fp, 'rb') as f:
        df = pickle.load(f)
    if df is None or len(df) == 0:
        return None
    out = {}
    for _, row in df.iterrows():
        # open_time is tz-aware UTC pandas timestamp
        ts = row['open_time']
        if hasattr(ts, 'value'):
            ts_ms = ts.value // 1_000_000  # ns → ms
        else:
            continue
        out[ts_ms] = (
            float(row['open']),
            float(row['close']),
            float(row['high']),
            float(row['low']),
            float(row['volume']),
        )
    return out


def load_bithumb_1m(coin):
    fp = os.path.join(BITHUMB_DIR, f'{coin}.json')
    if not os.path.exists(fp):
        return None
    with open(fp) as f:
        raw = json.load(f)
    out = {}
    for row in raw:
        try:
            ts_ms = int(row[0])
            o, c, h, l, v = float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
            out[ts_ms] = (o, c, h, l, v)
        except (ValueError, IndexError):
            continue
    return out


def get_aligned(binance, bithumb):
    """공통 timestamp만 추출 (정렬된 list)"""
    common = sorted(set(binance.keys()) & set(bithumb.keys()))
    return common


def pearson(xs, ys):
    if len(xs) < 5:
        return 0
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    num = sum(a * b for a, b in zip(dx, dy))
    sx = sum(a * a for a in dx) ** 0.5
    sy = sum(a * a for a in dy) ** 0.5
    if sx == 0 or sy == 0:
        return 0
    return num / (sx * sy)


def compute_returns(candles_dict, ts_list, window):
    """ts_list 각 시점에서 window분 후의 close 변화율 (%)"""
    rets = []
    for i, ts in enumerate(ts_list):
        future_ts = ts + window * 60_000
        if future_ts not in candles_dict:
            rets.append(None)
            continue
        c_now = candles_dict[ts][1]
        c_future = candles_dict[future_ts][1]
        if c_now <= 0:
            rets.append(None)
            continue
        rets.append((c_future - c_now) / c_now * 100)
    return rets


def main():
    with open('bithumb_coins.json') as f:
        bithumb_coins = set(json.load(f))

    binance_files = [f for f in os.listdir(BINANCE_DIR) if f.endswith('_1m.pkl')]
    binance_coins_raw = [f.replace('_1m.pkl', '') for f in binance_files]

    matches = []
    for raw in binance_coins_raw:
        # 1000PEPE → PEPE 같은 prefix 제거
        coin = raw.replace('USDT', '').replace('1000', '')
        if coin in bithumb_coins:
            matches.append(coin)

    print(f'Matching coins: {len(matches)}')
    print(f'  {matches}')

    # 코인 데이터 로드
    coin_data = {}  # coin → (binance_dict, bithumb_dict, common_ts_list)
    for coin in matches:
        bn = load_binance_1m(coin)
        bt = load_bithumb_1m(coin)
        if bn is None or bt is None:
            print(f'  {coin}: load failed')
            continue
        common = get_aligned(bn, bt)
        if len(common) < 100:
            print(f'  {coin}: only {len(common)} common candles')
            continue
        coin_data[coin] = (bn, bt, common)
        print(f'  {coin}: {len(common)} common 1m candles')

    print(f'\nUsable coins: {len(coin_data)}')
    if not coin_data:
        return

    # === Lag별 상관관계 ===
    print(f'\n=== Lag-correlation: Binance Δ(t-N, t) vs Bithumb Δ(t, t+N) ===')
    print('  (positive = binance leads bithumb)')

    lags = [1, 2, 3, 5, 10]
    print(f'\n{"coin":<8} {"n":>6}', *[f'{f"lag{l}m":>10}' for l in lags])

    aggregate_corrs = {l: [] for l in lags}
    for coin, (bn, bt, common) in coin_data.items():
        row = f'{coin:<8} {len(common):>6}'
        for lag in lags:
            xs = []
            ys = []
            for ts in common:
                # Binance 과거 lag분 변화
                ts_past = ts - lag * 60_000
                if ts_past not in bn:
                    continue
                bn_past = bn[ts_past][1]
                bn_now = bn[ts][1]
                if bn_past <= 0:
                    continue
                bn_ret = (bn_now - bn_past) / bn_past * 100

                # 빗썸 미래 lag분 변화
                ts_future = ts + lag * 60_000
                if ts_future not in bt:
                    continue
                bt_now = bt[ts][1]
                bt_future = bt[ts_future][1]
                if bt_now <= 0:
                    continue
                bt_ret = (bt_future - bt_now) / bt_now * 100

                xs.append(bn_ret)
                ys.append(bt_ret)

            if len(xs) >= 50:
                corr = pearson(xs, ys)
                aggregate_corrs[lag].append((coin, len(xs), corr))
                row += f' {corr:>+9.3f}'
            else:
                row += f' {"--":>10}'
        print(row)

    print(f'\n=== Average correlation across coins ===')
    for lag in lags:
        if aggregate_corrs[lag]:
            avg_corr = sum(c for _, _, c in aggregate_corrs[lag]) / len(aggregate_corrs[lag])
            n_coins = len(aggregate_corrs[lag])
            print(f'  lag {lag}m: avg corr = {avg_corr:+.4f} (across {n_coins} coins)')

    # === Big move 분석 ===
    print(f'\n=== Big move analysis: Binance |Δ| in lookback window → Bithumb forward ===')
    print('  Question: When Binance moves +X%, what does Bithumb do in next N min?')

    for binance_threshold in [1, 2, 5, 10]:
        for binance_window in [1, 5]:
            for bithumb_window in [1, 5, 10]:
                events = []  # (binance_move, bithumb_followup)
                for coin, (bn, bt, common) in coin_data.items():
                    for ts in common:
                        ts_past = ts - binance_window * 60_000
                        if ts_past not in bn:
                            continue
                        bn_past = bn[ts_past][1]
                        bn_now = bn[ts][1]
                        if bn_past <= 0:
                            continue
                        bn_move = (bn_now - bn_past) / bn_past * 100
                        if abs(bn_move) < binance_threshold:
                            continue

                        ts_future = ts + bithumb_window * 60_000
                        if ts_future not in bt:
                            continue
                        bt_now = bt[ts][1]
                        bt_future = bt[ts_future][1]
                        if bt_now <= 0:
                            continue
                        bt_move = (bt_future - bt_now) / bt_now * 100
                        events.append((coin, bn_move, bt_move))

                if len(events) < 5:
                    continue
                bt_moves = [e[2] for e in events]
                bn_moves = [e[1] for e in events]
                avg_bt = sum(bt_moves) / len(bt_moves)
                # Binance up일 때 bt 움직임
                up_events = [e for e in events if e[1] > 0]
                down_events = [e for e in events if e[1] < 0]
                up_avg = sum(e[2] for e in up_events) / len(up_events) if up_events else 0
                down_avg = sum(e[2] for e in down_events) / len(down_events) if down_events else 0

                # signed agreement (binance up → bithumb up)
                agree = sum(1 for e in events if (e[1] > 0) == (e[2] > 0))
                agree_pct = agree / len(events) * 100

                print(f'  bn|Δ|>={binance_threshold}% in {binance_window}m → bt {bithumb_window}m: '
                      f'n={len(events):>5} avg={avg_bt:>+5.2f}% '
                      f'(up→{up_avg:>+5.2f}%, dn→{down_avg:>+5.2f}%) agree={agree_pct:.1f}%')

    # === 큰 빗썸 펌프 직전 Binance 거동 ===
    print(f'\n=== Pre-pump Binance behavior (Bithumb pump = +20% in 10min) ===')
    pump_events = []
    for coin, (bn, bt, common) in coin_data.items():
        for ts in common:
            # Bithumb 향후 10분 max
            future_max_pct = 0
            for j in range(1, 11):
                ts_f = ts + j * 60_000
                if ts_f not in bt:
                    continue
                bt_now = bt[ts][1]
                bt_h = bt[ts_f][2]  # close
                if bt_now > 0:
                    pct = (bt_h - bt_now) / bt_now * 100
                    if pct > future_max_pct:
                        future_max_pct = pct
            if future_max_pct < 20:
                continue
            # 같은 코인의 직전 5분 binance 움직임
            ts_past = ts - 5 * 60_000
            if ts_past not in bn:
                continue
            bn_past = bn[ts_past][1]
            bn_now = bn[ts][1]
            if bn_past <= 0:
                continue
            bn_pre = (bn_now - bn_past) / bn_past * 100
            pump_events.append((coin, ts, future_max_pct, bn_pre))

    if pump_events:
        print(f'  Found {len(pump_events)} bithumb pumps with binance data')
        for coin, ts, bt_pump, bn_pre in pump_events[:30]:
            dt = datetime.fromtimestamp(ts / 1000, KST)
            print(f'    {coin:>8} {dt:%m-%d %H:%M} bt+10min={bt_pump:>+6.1f}% bn-5min={bn_pre:>+6.1f}%')
        # 통계
        bn_pres = [e[3] for e in pump_events]
        print(f'\n  Binance pre-move stats (n={len(bn_pres)}):')
        print(f'    avg={sum(bn_pres)/len(bn_pres):+.2f}%')
        print(f'    median={sorted(bn_pres)[len(bn_pres)//2]:+.2f}%')
        print(f'    p90={sorted(bn_pres)[len(bn_pres)*9//10]:+.2f}%')
        print(f'    >0%: {sum(1 for x in bn_pres if x > 0)}/{len(bn_pres)} ({sum(1 for x in bn_pres if x > 0)/len(bn_pres)*100:.1f}%)')
    else:
        print('  No matching pumps')


if __name__ == '__main__':
    main()
