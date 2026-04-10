"""
Dual scanner — burst + gradual 동시 스캔.

Type A: Immediate burst (vol_x 20x + gain 5% + tv 50M)
Type B: Gradual buildup (직전 30분 누적 +10% + 양봉 60% + tv 누적 ≥ 300M)

각 타입 신호 발생 코인 모두 출력.
"""
import urllib.request
import json
import time
import sys
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
UA = {'User-Agent': 'Mozilla/5.0'}


def fetch_candles(coin, interval='1m'):
    url = f'https://api.bithumb.com/public/candlestick/{coin}_KRW/{interval}'
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        if d.get('status') != '0000':
            return None
        return d.get('data', [])
    except Exception:
        return None


def parse(raw):
    candles = []
    for row in raw:
        try:
            ts = int(row[0])
            o, c, h, l, v = float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
            candles.append((ts, o, c, h, l, v))
        except (ValueError, IndexError):
            continue
    return candles


def check_burst(candles):
    """Type A: 마지막 1분봉이 즉시 vol burst"""
    if len(candles) < 35:
        return None
    i = len(candles) - 1
    ts, o, c, h, l, v = candles[i]
    if c <= o or v <= 0 or o <= 0:
        return None
    gain = (c - o) / o * 100
    if gain < 5:
        return None
    tv = c * v
    if tv < 50e6:
        return None
    base_vol = sum(candles[j][5] for j in range(i - 30, i)) / 30
    if base_vol <= 0:
        return None
    vol_x = v / base_vol
    if vol_x < 20:
        return None
    return {'type': 'BURST', 'ts': ts, 'price': c, 'vol_x': vol_x, 'gain': gain, 'tv': tv}


def check_gradual(candles):
    """Type B: 직전 30분 누적 +10% + 양봉 60% + tv 누적 ≥ 300M"""
    if len(candles) < 35:
        return None
    i = len(candles) - 1
    ts, o, c, h, l, v = candles[i]

    # 30분 전 close
    start_idx = i - 30
    if start_idx < 0:
        return None
    start_close = candles[start_idx][2]
    if start_close <= 0:
        return None
    cum_gain = (c - start_close) / start_close * 100
    if cum_gain < 10:
        return None

    # 30봉 양봉 비율
    up = sum(1 for j in range(start_idx, i + 1) if candles[j][2] > candles[j][1])
    up_ratio = up / 31
    if up_ratio < 0.6:
        return None

    # 30분 누적 tv
    tv_30 = sum(candles[j][2] * candles[j][5] for j in range(start_idx, i + 1))
    if tv_30 < 300e6:
        return None

    # 직전 5분 음봉 최대 (-2% 이하 dump 없으면)
    last_5_gains = []
    for j in range(i - 4, i + 1):
        bo, bc = candles[j][1], candles[j][2]
        if bo > 0:
            last_5_gains.append((bc - bo) / bo * 100)
    last5_min = min(last_5_gains) if last_5_gains else 0
    if last5_min < -3:
        return None  # 직전 5분에 큰 음봉 있으면 끝물

    return {
        'type': 'GRADUAL',
        'ts': ts,
        'price': c,
        'cum_gain_30m': cum_gain,
        'up_ratio': up_ratio,
        'tv_30m': tv_30,
        'last5_min_bar': last5_min,
    }


def load_coins():
    fp = 'bithumb_coins.json'
    try:
        with open(fp) as f:
            return json.load(f)
    except FileNotFoundError:
        url = 'https://api.bithumb.com/public/ticker/ALL_KRW'
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read())
        coins = [k for k in d.get('data', {}).keys() if k != 'date']
        with open(fp, 'w') as f:
            json.dump(coins, f)
        return coins


def main():
    coins = load_coins()
    print(f'[{datetime.now(KST):%H:%M:%S}] Dual scan: {len(coins)} coins')
    print(f'  Type A (burst): vol≥20x + gain≥5% + tv≥50M')
    print(f'  Type B (gradual): 30m +10% + 양봉≥60% + tv30m≥300M + 직전5분 음봉<-3% 없음')

    bursts = []
    graduals = []

    for i, coin in enumerate(coins, 1):
        raw = fetch_candles(coin, '1m')
        if raw is None:
            continue
        candles = parse(raw)
        if not candles:
            continue
        b = check_burst(candles)
        if b:
            bursts.append({**b, 'coin': coin})
        g = check_gradual(candles)
        if g:
            graduals.append({**g, 'coin': coin})
        time.sleep(0.08)

    print(f'\n=== TYPE A (BURST): {len(bursts)} signals ===')
    if bursts:
        bursts.sort(key=lambda s: -s['vol_x'])
        for s in bursts:
            dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
            print(f'  [{dt:%H:%M}] {s["coin"]:>10} vol_x={s["vol_x"]:>6.0f}x gain={s["gain"]:>+5.1f}% tv={s["tv"]/1e6:>5.0f}M @{s["price"]}')
    else:
        print('  None')

    print(f'\n=== TYPE B (GRADUAL): {len(graduals)} signals ===')
    if graduals:
        graduals.sort(key=lambda s: -s['cum_gain_30m'])
        for s in graduals:
            dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
            print(f'  [{dt:%H:%M}] {s["coin"]:>10} 30m_gain={s["cum_gain_30m"]:>+5.1f}% up_ratio={s["up_ratio"]:.0%} tv30={s["tv_30m"]/1e6:>4.0f}M last5_min={s["last5_min_bar"]:+.1f}% @{s["price"]}')
    else:
        print('  None')

    # 로그 저장
    log_file = f'dual_scan_{datetime.now(KST):%Y-%m-%d}.jsonl'
    with open(log_file, 'a') as f:
        ts = datetime.now(KST).isoformat()
        for s in bursts + graduals:
            f.write(json.dumps({**s, 'scan_time': ts}) + '\n')
    if bursts or graduals:
        print(f'\n  → Logged to {log_file}')


if __name__ == '__main__':
    main()
