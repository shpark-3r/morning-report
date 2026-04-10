"""
라이브 펌프 신호 스캐너 (forward 검증용).

사용법 (4/10 ⭐ 새 default):
  python live_pump_scanner.py --burst              # NEW default: immediate burst
  python live_pump_scanner.py --burst --strong     # 더 strict (vol≥30x)
  python live_pump_scanner.py --burst --watch      # 1분마다 반복

기존 (deprecated, backward-looking):
  python live_pump_scanner.py                      # base (multi-lookback adaptive)
  python live_pump_scanner.py --strict             # strict
  python live_pump_scanner.py --strict --filter    # strict + FP filter

신호 정의 (4/9 분석 + 4/10 immediate burst 추가):

[⭐ Immediate Burst] (--burst, 권장)
  - 가장 최근 1분봉이 양봉 + vol ≥ baseline_30 × 20x + gain ≥ 5% + tv ≥ 50M
  - dedupe: 같은 코인 10분 내 1건
  - 검증 (n=77, 20/29 day cover):
    - win rate 49%, EV @0.3% +1.49% (D adaptive trailing)
    - sig/day 평균 2.6건
  - ⭐ ENJ 4/9 00:15 (사용자 본 펌프) 잡음, exit +33.27%
  - 핵심: backward-looking 5분 누적이 아니라 봉 자체의 즉시 burst

[⭐⭐ Immediate Burst Strong] (--burst --strong)
  - vol ≥ 30x, gain ≥ 5%, tv ≥ 50M
  - 검증 (n=66): EV @0.3% +1.60%, win 47%, sig/day 2.2
  - 더 strict하지만 표본 약간 적음

[Base] (multi-lookback, deprecated)
  - 5분+5% OR 10분+7% OR 15분+10% OR 30분+15% (backward-looking)
  - 단점: ENJ 00:15 같은 가속 시작점을 못 잡음 (직전 5분이 박스권)

검증된 사용자 사례 (Immediate burst + D adaptive trailing):
  ENJ 4/9 00:15 (vol 118x, +5.1%) → exit +33.27% ⭐⭐⭐
  XION 4/7 14:38 (vol 18x) → exit +2.00%
  XYO 3/31 18:01 (vol 62x) → exit +12.31%

⚠️ 표본 77건 (immediate burst 20x). 라이브는 paper trading부터.
⚠️ 라이브 슬리피지가 결정자. 호가창 측정 필수.
⚠️ 매일 작전 day 가설은 데이터로 입증됨 (20/29 days +30% pump 발생).
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


def check_burst_signal(candles, strong=False):
    """
    ⭐ Immediate burst signal (4/10 default).
    가장 최근 봉이 vol burst + 양봉.

    조건:
      - candle[i] vol >= baseline_30 * vol_x (default 20x, strong 30x)
      - candle[i] is up bar (close > open)
      - gain >= 5%
      - tv >= 50M
    """
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

    min_vol_x = 30 if strong else 20
    if vol_x < min_vol_x:
        return None

    return {
        'ts': ts,
        'price': c,
        'vol_x': vol_x,
        'gain': gain,
        'tv': tv,
        'mode': 'burst_strong' if strong else 'burst',
    }


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


def write_heartbeat(stage='scan'):
    """Q-17: heartbeat for watchdog. Stale > 3min → restart."""
    try:
        with open('live_scanner_heartbeat.txt', 'w') as f:
            f.write(f'{int(time.time())}|{datetime.now(KST).isoformat()}|{stage}')
    except Exception:
        pass


def scan(strict=False, fp_filter=False, burst=False, strong=False):
    write_heartbeat('scan_start')
    coins = load_coin_list()
    mode = 'burst_strong' if (burst and strong) else 'burst' if burst else f'strict={strict},fp={fp_filter}'
    print(f'[{datetime.now(KST):%H:%M:%S}] Scanning {len(coins)} coins (mode={mode})...')

    signals = []
    for i, coin in enumerate(coins, 1):
        raw = fetch_candles(coin, '1m')
        if raw is None:
            continue
        candles = parse_candles(raw)
        if not candles:
            continue
        if burst:
            sig = check_burst_signal(candles, strong=strong)
        else:
            sig = check_signal(candles, strict=strict, fp_filter=fp_filter)
        if sig:
            signals.append({**sig, 'coin': coin})
        time.sleep(0.1)  # rate limit

    print(f'\n=== Signals found: {len(signals)} ===')
    if signals:
        # burst 우선
        if burst:
            signals.sort(key=lambda s: -s.get('vol_x', 0))
            for s in signals:
                dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
                marker = '*** STRONG ***' if s.get('mode') == 'burst_strong' else ''
                chart_url = f'https://www.bithumb.com/react/trade/order/{s["coin"]}_KRW'
                print(f'  [{dt:%H:%M}] {s["coin"]:>10} '
                      f'vol_x={s["vol_x"]:>6.0f}x gain={s["gain"]:>+5.1f}% '
                      f'tv={s["tv"]/1e6:>4.0f}M price={s["price"]} {marker}')
                print(f'             → {chart_url}')
        else:
            signals.sort(key=lambda s: (-s.get('very_strict', 0), -s.get('tv_5min', 0)))
            for s in signals:
                dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
                marker = '*** VERY STRICT ***' if s.get('very_strict') else ''
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
    burst = '--burst' in sys.argv
    strong = '--strong' in sys.argv
    watch = '--watch' in sys.argv

    if watch:
        print('Watch mode: scanning every 60 seconds')
        while True:
            try:
                scan(strict=strict, fp_filter=fp_filter, burst=burst, strong=strong)
                write_heartbeat('scan_done')
            except KeyboardInterrupt:
                print('\nStopped.')
                break
            except Exception as e:
                print(f'Error: {e}')
                write_heartbeat('scan_error')
            time.sleep(60)
    else:
        scan(strict=strict, fp_filter=fp_filter, burst=burst, strong=strong)


if __name__ == '__main__':
    main()
