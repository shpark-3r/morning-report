"""
빗썸 1분봉/30분봉 전 종목 다운로드.
- 1분봉: ~3000개 = ~50시간 (~2일치)
- 30분봉: ~3000개 = ~62일치 (~2개월)
저장: data/bithumb_1m/{COIN}.json, data/bithumb_30m/{COIN}.json
"""
import urllib.request
import urllib.error
import json
import time
import os
import sys
from datetime import datetime

UA = {'User-Agent': 'Mozilla/5.0'}
RATE_DELAY = 0.15  # 빗썸 public API: ~150 req/s 한도, 여유롭게


def fetch_candles(coin: str, interval: str, retries: int = 3):
    url = f'https://api.bithumb.com/public/candlestick/{coin}_KRW/{interval}'
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read())
            if d.get('status') != '0000':
                return None, f"status={d.get('status')}"
            return d.get('data', []), None
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            if attempt < retries - 1:
                time.sleep(0.5 * (attempt + 1))
                continue
            return None, str(e)
        except Exception as e:
            return None, str(e)
    return None, "max retries"


def save_candles(coin: str, interval: str, data: list, out_dir: str):
    fp = os.path.join(out_dir, f'{coin}.json')
    with open(fp, 'w') as f:
        json.dump(data, f)
    return fp


def main():
    interval = sys.argv[1] if len(sys.argv) > 1 else '1m'
    assert interval in ('1m', '30m'), "interval must be 1m or 30m"
    out_dir = f'data/bithumb_{interval}'
    os.makedirs(out_dir, exist_ok=True)

    with open('bithumb_coins.json') as f:
        coins = json.load(f)

    print(f'[{datetime.now():%H:%M:%S}] Downloading {interval} candles for {len(coins)} coins...')
    print(f'  Output: {out_dir}/')

    success = 0
    fail = 0
    failures = []
    t0 = time.time()

    for i, coin in enumerate(coins, 1):
        data, err = fetch_candles(coin, interval)
        if data is None:
            fail += 1
            failures.append((coin, err))
            print(f'  [{i}/{len(coins)}] {coin} FAIL: {err}')
        else:
            save_candles(coin, interval, data, out_dir)
            success += 1
            if i % 50 == 0:
                elapsed = time.time() - t0
                rate = i / elapsed
                eta = (len(coins) - i) / rate
                print(f'  [{i}/{len(coins)}] {coin} ok ({len(data)} candles) | {rate:.1f}/s, eta {eta:.0f}s')
        time.sleep(RATE_DELAY)

    elapsed = time.time() - t0
    print(f'\n[{datetime.now():%H:%M:%S}] DONE in {elapsed:.0f}s')
    print(f'  Success: {success}/{len(coins)}')
    print(f'  Fail:    {fail}')
    if failures:
        print('  Failures:')
        for c, e in failures[:20]:
            print(f'    {c}: {e}')

    # 메타: 시간 범위
    if success > 0:
        sample_coin = next((c for c in coins if os.path.exists(os.path.join(out_dir, f'{c}.json'))), None)
        if sample_coin:
            with open(os.path.join(out_dir, f'{sample_coin}.json')) as f:
                sample = json.load(f)
            if sample:
                first_ts = sample[0][0] / 1000
                last_ts = sample[-1][0] / 1000
                print(f'\n  Time range ({sample_coin}): {datetime.fromtimestamp(first_ts)} → {datetime.fromtimestamp(last_ts)}')
                print(f'  Span: {(last_ts - first_ts) / 3600:.1f} hours / {len(sample)} candles')


if __name__ == '__main__':
    main()
