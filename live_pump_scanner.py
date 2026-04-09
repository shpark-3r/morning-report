"""
라이브 펌프 신호 스캐너 (forward 검증용).

사용법:
  python live_pump_scanner.py                    # base 신호
  python live_pump_scanner.py --strict           # strict 신호
  python live_pump_scanner.py --strict --filter  # strict + FP 필터 (best EV)
  python live_pump_scanner.py --watch            # 1분마다 반복

신호 정의 (4/9 분석에서 검증):

[Base] Multi-lookback adaptive
  - cumulative gain: 5분+5% OR 10분+7% OR 15분+10% OR 30분+15%
  - 양봉 비율 ≥ 60% (직전 5분 중 3봉)
  - 5분 누적 tv ≥ 30M KRW
  - dedupe: 같은 코인 10분 내 1건만
  - 검증: precision 10.3% (future +20%)

[Strict] (--strict)
  - + tv_5min ≥ 200M
  - + vol_ratio_5 (vs 직전 30분 baseline) ≥ 10x
  - 검증: precision 19.4%, EV @0.3% +1.33% (D adaptive trailing)

[Strict + FP filter] (--strict --filter)
  - + 22-02시 제외 (밤 작전 dump 회피)
  - + triggered_gain ≥ 10%
  - + bar_gain < 7% (신호 봉이 끝물 아님)
  - 검증: 90% win rate, EV @0.3% +6.10% (n=10, ⚠️ cherry pick 위험)

검증된 사용자 사례 (D adaptive trailing):
  ENJ 4/9 11:39 → exit +6.70% (net)
  JOE 4/8 06:38 → exit +1.32% (보수적, A 전략으로는 더 잘 잡음)
  XION 4/7 14:35 → exit +14.58%
  XYO 3/31 18:02 → exit +21.51%

⚠️ 표본 10~31건 작음. 라이브는 paper trading부터.
⚠️ 라이브 슬리피지가 결정자. slip 1% 시 EV -0.07% (break-even).
"""
import urllib.request
import json
import time
import sys
import os
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


def parse_candles(raw):
    candles = []
    for row in raw:
        try:
            ts = int(row[0])
            o, c, h, l, v = float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
            candles.append((ts, o, c, h, l, v))
        except (ValueError, IndexError):
            continue
    return candles


def check_signal(candles, strict=False, fp_filter=False):
    """
    가장 최신 봉 직전까지의 데이터로 신호 검사.
    fp_filter: False positive 추가 필터 (밤 시간대 제외 + tg≥10 + bar<7)
    Returns: dict | None
    """
    if len(candles) < 36:
        return None
    i = len(candles) - 1  # 가장 최신 봉
    ts, o, c, h, l, v = candles[i]
    if c <= 0:
        return None

    # 5분 누적 trade value
    tv_5 = sum(candles[j][2] * candles[j][5] for j in range(i - 5, i))
    min_tv = 200e6 if strict else 30e6
    if tv_5 < min_tv:
        return None

    # 양봉 비율
    up_count = sum(1 for j in range(i - 5, i) if candles[j][2] > candles[j][1])
    if up_count < 3:
        return None

    # multi-lookback gain check
    triggered_lb = None
    triggered_gain = None
    for lb_min, min_gain in [(5, 5), (10, 7), (15, 10), (30, 15)]:
        if i < lb_min + 1:
            continue
        start_close = candles[i - lb_min][2]
        if start_close <= 0:
            continue
        cum_gain = (c - start_close) / start_close * 100
        if cum_gain >= min_gain:
            triggered_lb = lb_min
            triggered_gain = cum_gain
            break
    if triggered_lb is None:
        return None

    # vol_ratio (5분 평균 vs 직전 30분 평균)
    past_5_vol = sum(candles[j][5] for j in range(i - 5, i))
    base_vol_30 = sum(candles[j][5] for j in range(i - 35, i - 5)) / 30
    vol_ratio_5 = (past_5_vol / 5) / base_vol_30 if base_vol_30 > 0 else 0

    if strict and vol_ratio_5 < 10:
        return None

    # 신호 봉 자체 메타
    bar_gain = (c - o) / o * 100 if o > 0 else 0
    upper_wick = (h - c) / c * 100 if c > 0 else 0

    # FP 필터 (best EV +6.10%)
    if fp_filter:
        from datetime import datetime as _dt
        dt_kst = _dt.fromtimestamp(ts / 1000, KST)
        # 1. 22-02시 제외
        if dt_kst.hour in [22, 23, 0, 1]:
            return None
        # 2. triggered_gain >= 10%
        if triggered_gain < 10:
            return None
        # 3. bar_gain < 7% (신호 봉이 끝물 아님)
        if bar_gain >= 7:
            return None

    return {
        'ts': ts,
        'price': c,
        'tv_5min': tv_5,
        'up_count': up_count,
        'triggered_lb_min': triggered_lb,
        'triggered_gain': triggered_gain,
        'vol_ratio_5': vol_ratio_5,
        'bar_gain': bar_gain,
        'upper_wick': upper_wick,
        'very_strict': tv_5 >= 500e6 and vol_ratio_5 >= 10,
    }


def load_coin_list():
    fp = 'bithumb_coins.json'
    if os.path.exists(fp):
        with open(fp) as f:
            return json.load(f)
    # API에서 받기
    url = 'https://api.bithumb.com/public/ticker/ALL_KRW'
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    coins = [k for k in d.get('data', {}).keys() if k != 'date']
    with open(fp, 'w') as f:
        json.dump(coins, f)
    return coins


def scan(strict=False, fp_filter=False):
    coins = load_coin_list()
    print(f'[{datetime.now(KST):%H:%M:%S}] Scanning {len(coins)} coins (strict={strict}, fp_filter={fp_filter})...')

    signals = []
    for i, coin in enumerate(coins, 1):
        raw = fetch_candles(coin, '1m')
        if raw is None:
            continue
        candles = parse_candles(raw)
        if not candles:
            continue
        sig = check_signal(candles, strict=strict, fp_filter=fp_filter)
        if sig:
            signals.append({**sig, 'coin': coin})
        time.sleep(0.1)  # rate limit

    print(f'\n=== Signals found: {len(signals)} ===')
    if signals:
        # very_strict 우선
        signals.sort(key=lambda s: (-s['very_strict'], -s['tv_5min']))
        for s in signals:
            dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
            marker = '*** VERY STRICT ***' if s['very_strict'] else ''
            print(f'  [{dt:%H:%M}] {s["coin"]:>10} '
                  f'lb={s["triggered_lb_min"]:>2}min gain={s["triggered_gain"]:>+5.1f}% '
                  f'tv5={s["tv_5min"]/1e6:>5.0f}M vr5={s["vol_ratio_5"]:>5.1f}x '
                  f'price={s["price"]} {marker}')

        # 로그 저장
        log_file = f'live_signals_{datetime.now(KST):%Y-%m-%d}.jsonl'
        with open(log_file, 'a') as f:
            for s in signals:
                f.write(json.dumps({**s, 'scan_time': datetime.now(KST).isoformat()}) + '\n')
        print(f'  → Logged to {log_file}')
    else:
        print('  No signals.')

    return signals


def main():
    strict = '--strict' in sys.argv
    fp_filter = '--filter' in sys.argv
    watch = '--watch' in sys.argv

    if watch:
        print('Watch mode: scanning every 60 seconds')
        while True:
            try:
                scan(strict=strict, fp_filter=fp_filter)
            except KeyboardInterrupt:
                print('\nStopped.')
                break
            except Exception as e:
                print(f'Error: {e}')
            time.sleep(60)
    else:
        scan(strict=strict, fp_filter=fp_filter)


if __name__ == '__main__':
    main()
