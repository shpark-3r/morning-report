"""
Dual scanner v2 — burst + gradual + medium 동시 스캔.

Type A: Immediate burst (vol_x 10x + gain 3% + tv 30M) ← 완화 (Q-30)
Type B: Gradual buildup (30분 +10% + 양봉 60% + tv30m ≥ 300M) ← last5_min 수정
Type C: Medium speed acceleration (10분 +7% + vol 3x + 양봉 70% + tv10m ≥ 100M) ← 신규

PCI 12:41 미탐지 원인 해결:
- Type A gain 5%→3%: PCI 단봉 max +4.6% (이전 미탐지) → 3% 통과
- Type B last5_min: -4.3% 음봉 후 회복 시 허용
- Type C: PCI 12:48 시점 10분 +10.9% 탐지 가능
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
    """Type A: vol burst (완화: gain 3%, vol_x 10x, tv 30M)"""
    if len(candles) < 35:
        return None
    i = len(candles) - 1
    ts, o, c, h, l, v = candles[i]
    if c <= o or v <= 0 or o <= 0:
        return None
    gain = (c - o) / o * 100
    if gain < 3:
        return None
    tv = c * v
    if tv < 30e6:
        return None
    base_vol = sum(candles[j][5] for j in range(i - 30, i)) / 30
    if base_vol <= 0:
        return None
    vol_x = v / base_vol
    if vol_x < 10:
        return None
    strength = 'STRONG' if (vol_x >= 30 and gain >= 5 and tv >= 100e6) else 'NORMAL'
    return {'type': f'BURST_{strength}', 'ts': ts, 'price': c, 'vol_x': vol_x, 'gain': gain, 'tv': tv}


def check_gradual(candles):
    """Type B: 30분 점진 (last5_min 수정: 회복 시 허용)"""
    if len(candles) < 35:
        return None
    i = len(candles) - 1
    ts, o, c, h, l, v = candles[i]

    start_idx = i - 30
    if start_idx < 0:
        return None
    start_close = candles[start_idx][2]
    if start_close <= 0:
        return None
    cum_gain = (c - start_close) / start_close * 100
    if cum_gain < 10:
        return None

    up = sum(1 for j in range(start_idx, i + 1) if candles[j][2] > candles[j][1])
    up_ratio = up / 31
    if up_ratio < 0.55:
        return None

    tv_30 = sum(candles[j][2] * candles[j][5] for j in range(start_idx, i + 1))
    if tv_30 < 300e6:
        return None

    # 수정: last5_min 조건 완화
    # 이전: -3% 음봉 있으면 무조건 차단
    # 신규: -3% 음봉 있어도, 현재 봉이 양봉이고 직전 low보다 높으면 허용 (회복 확인)
    last_5_gains = []
    last_5_lows = []
    for j in range(i - 4, i + 1):
        bo, bc = candles[j][1], candles[j][2]
        if bo > 0:
            last_5_gains.append((bc - bo) / bo * 100)
        last_5_lows.append(candles[j][4])
    last5_min = min(last_5_gains) if last_5_gains else 0

    if last5_min < -3:
        # 회복 확인: 현재 close가 5분 low 최저점보다 +2% 이상 위?
        min_low = min(last_5_lows) if last_5_lows else c
        recovery = (c - min_low) / min_low * 100 if min_low > 0 else 0
        if recovery < 2:
            return None  # 회복 안 됨 = 진짜 끝물

    return {
        'type': 'GRADUAL',
        'ts': ts,
        'price': c,
        'cum_gain_30m': cum_gain,
        'up_ratio': up_ratio,
        'tv_30m': tv_30,
        'last5_min_bar': last5_min,
    }


def check_medium(candles):
    """Type C: Medium speed (10분 +7% + vol 3x + 양봉 70% + tv10m >= 100M)
    PCI 12:48 패턴 탐지용.
    """
    if len(candles) < 15:
        return None
    i = len(candles) - 1
    ts, o, c, h, l, v = candles[i]

    # 10분 전 close
    if i < 10:
        return None
    start_close = candles[i - 10][2]
    if start_close <= 0:
        return None
    cum_gain_10 = (c - start_close) / start_close * 100
    if cum_gain_10 < 7:
        return None

    # 10봉 양봉 비율
    up = sum(1 for j in range(i - 9, i + 1) if candles[j][2] > candles[j][1])
    up_ratio = up / 10
    if up_ratio < 0.6:
        return None

    # vol 가속 (10분 평균 vs 직전 30분 평균)
    vol_10 = sum(candles[j][5] for j in range(i - 9, i + 1)) / 10
    vol_30_base = sum(candles[j][5] for j in range(max(0, i - 39), i - 9)) / 30 if i >= 39 else 0
    vol_accel = vol_10 / vol_30_base if vol_30_base > 0 else 0
    if vol_accel < 3:
        return None

    # tv 10분 누적
    tv_10 = sum(candles[j][2] * candles[j][5] for j in range(i - 9, i + 1))
    if tv_10 < 100e6:
        return None

    # 5분 단위로도 체크 (더 빠른 탐지)
    if i >= 5:
        start_5 = candles[i - 5][2]
        cum_gain_5 = (c - start_5) / start_5 * 100 if start_5 > 0 else 0
    else:
        cum_gain_5 = 0

    return {
        'type': 'MEDIUM',
        'ts': ts,
        'price': c,
        'cum_gain_10m': cum_gain_10,
        'cum_gain_5m': cum_gain_5,
        'up_ratio': up_ratio,
        'vol_accel': vol_accel,
        'tv_10m': tv_10,
    }


def check_quiet_gradual(candles):
    """Type D: Quiet Gradual — 조용한 계단식 우상향 (CFG/MERL/MON 패턴)
    MA 정배열 + R^2 선형 추세 + vol steady + 30분 gain 3~15%
    """
    if len(candles) < 65:
        return None
    i = len(candles) - 1

    # close 배열
    closes_60 = [candles[j][2] for j in range(i - 59, i + 1)]
    closes_30 = closes_60[30:]
    closes_15 = closes_60[45:]
    closes_5 = closes_60[55:]

    # 1. MA 정배열 (MA5 > MA15 > MA60)
    ma5 = sum(closes_5) / 5
    ma15 = sum(closes_15) / 15
    ma60 = sum(closes_60) / 60
    if not (ma5 > ma15 > ma60):
        return None
    # MA 기울기 양수 확인 (ma5 > 5분전 ma5)
    closes_5_prev = closes_60[50:55]
    ma5_prev = sum(closes_5_prev) / 5
    if ma5 <= ma5_prev:
        return None

    # 2. R^2 (30분 close의 선형 회귀 적합도)
    n = len(closes_30)
    x_mean = (n - 1) / 2
    y_mean = sum(closes_30) / n
    ss_xy = sum((j - x_mean) * (closes_30[j] - y_mean) for j in range(n))
    ss_xx = sum((j - x_mean) ** 2 for j in range(n))
    ss_yy = sum((closes_30[j] - y_mean) ** 2 for j in range(n))
    if ss_xx == 0 or ss_yy == 0:
        return None
    r2 = (ss_xy ** 2) / (ss_xx * ss_yy)
    if r2 < 0.65:
        return None

    # 3. 30분 gain 3~20%
    gain_30 = (closes_30[-1] - closes_30[0]) / closes_30[0] * 100 if closes_30[0] > 0 else 0
    if gain_30 < 3 or gain_30 > 20:
        return None

    # 4. vol steady (1.5~10x, burst 아닌 꾸준한 증가)
    vol_recent = sum(candles[j][5] for j in range(i - 9, i + 1)) / 10
    vol_base = sum(candles[j][5] for j in range(i - 59, i - 9)) / 50 if i >= 59 else 0
    vol_ratio = vol_recent / vol_base if vol_base > 0 else 0
    if vol_ratio < 1.2 or vol_ratio > 15:
        return None

    # 5. tv 30분 누적 >= 50M (최소 거래)
    tv_30 = sum(candles[j][2] * candles[j][5] for j in range(i - 29, i + 1))
    if tv_30 < 50e6:
        return None

    return {
        'type': 'QUIET_GRADUAL',
        'ts': candles[i][0],
        'price': candles[i][2],
        'r2': r2,
        'gain_30m': gain_30,
        'ma_alignment': f'{ma5:.2f}>{ma15:.2f}>{ma60:.2f}',
        'vol_ratio': vol_ratio,
        'tv_30m': tv_30,
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
    now = datetime.now(KST)
    print(f'[{now:%H:%M:%S}] Dual scan v2: {len(coins)} coins')
    print(f'  Type A (burst):   vol>=10x + gain>=3% + tv>=30M')
    print(f'  Type B (gradual): 30m +10% + up>=55% + tv30m>=300M (dip recovery OK)')
    print(f'  Type C (medium):  10m +7% + up>=60% + vol_accel>=3x + tv10m>=100M')

    bursts = []
    graduals = []
    mediums = []
    quiets = []

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
        m = check_medium(candles)
        if m:
            mediums.append({**m, 'coin': coin})
        q = check_quiet_gradual(candles)
        if q:
            quiets.append({**q, 'coin': coin})
        time.sleep(0.08)

    print(f'\n=== TYPE A (BURST): {len(bursts)} signals ===')
    if bursts:
        bursts.sort(key=lambda s: -s['vol_x'])
        for s in bursts:
            dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
            url = f'https://www.bithumb.com/react/trade/order/{s["coin"]}_KRW'
            print(f'  [{dt:%H:%M}] {s["coin"]:>10} vol_x={s["vol_x"]:>6.0f}x gain={s["gain"]:>+5.1f}% tv={s["tv"]/1e6:>5.0f}M @{s["price"]} ({s["type"]})')
            print(f'             -> {url}')
    else:
        print('  None')

    print(f'\n=== TYPE B (GRADUAL): {len(graduals)} signals ===')
    if graduals:
        graduals.sort(key=lambda s: -s['cum_gain_30m'])
        for s in graduals:
            dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
            print(f'  [{dt:%H:%M}] {s["coin"]:>10} 30m={s["cum_gain_30m"]:>+5.1f}% up={s["up_ratio"]:.0%} tv30={s["tv_30m"]/1e6:>4.0f}M last5={s["last5_min_bar"]:+.1f}% @{s["price"]}')
    else:
        print('  None')

    print(f'\n=== TYPE C (MEDIUM): {len(mediums)} signals ===')
    if mediums:
        mediums.sort(key=lambda s: -s['cum_gain_10m'])
        for s in mediums:
            dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
            url = f'https://www.bithumb.com/react/trade/order/{s["coin"]}_KRW'
            print(f'  [{dt:%H:%M}] {s["coin"]:>10} 10m={s["cum_gain_10m"]:>+5.1f}% 5m={s["cum_gain_5m"]:>+5.1f}% up={s["up_ratio"]:.0%} vol_acc={s["vol_accel"]:.0f}x tv10={s["tv_10m"]/1e6:>4.0f}M @{s["price"]}')
            print(f'             -> {url}')
    else:
        print('  None')

    print(f'\n=== TYPE D (QUIET GRADUAL): {len(quiets)} signals ===')
    if quiets:
        quiets.sort(key=lambda s: -s['r2'])
        for s in quiets:
            dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
            url = f'https://www.bithumb.com/react/trade/order/{s["coin"]}_KRW'
            print(f'  [{dt:%H:%M}] {s["coin"]:>10} R2={s["r2"]:.2f} 30m={s["gain_30m"]:>+5.1f}% vol={s["vol_ratio"]:.1f}x tv30={s["tv_30m"]/1e6:>4.0f}M @{s["price"]}')
            print(f'             MA: {s["ma_alignment"]}')
            print(f'             -> {url}')
    else:
        print('  None')

    # 로그 저장
    log_file = f'dual_scan_{now:%Y-%m-%d}.jsonl'
    with open(log_file, 'a') as f:
        ts_str = now.isoformat()
        for s in bursts + graduals + mediums + quiets:
            f.write(json.dumps({**s, 'scan_time': ts_str}) + '\n')
    if bursts or graduals or mediums or quiets:
        print(f'\n  -> Logged to {log_file}')


if __name__ == '__main__':
    main()
