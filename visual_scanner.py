"""
Visual Scanner — 1단계 거름망 + 2단계 차트 렌더링.

1단계: 451코인 빠른 스캔 (거래량/가격 변동 기준)
2단계: 후보 코인만 차트 렌더링 → Claude가 직접 이미지 분석

사용법:
  python visual_scanner.py              # 거름망 + 차트 렌더
  python visual_scanner.py --filter     # 거름망만 (차트 없이)
  python visual_scanner.py --coin ILV   # 특정 코인만 차트
"""
import urllib.request
import json
import time
import os
import sys
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
UA = {'User-Agent': 'Mozilla/5.0'}
CHART_DIR = 'scan_charts'


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


def quick_filter(coins):
    """1단계: 빠른 거름망 — 움직이는 코인만 추출.

    조건 (하나라도 충족):
    - 최근 10분 가격 변동 >=2%
    - 최근 10분 거래량이 이전 50분 평균 대비 5x 이상
    - 최근 60분 가격 변동 >=10%
    """
    candidates = []
    for coin in coins:
        raw = fetch_candles(coin, '1m')
        if not raw:
            continue
        candles = parse(raw)
        if len(candles) < 65:
            continue

        i = len(candles) - 1
        price_now = candles[i][2]
        if price_now <= 0:
            continue

        # 10분 가격 변동
        price_10ago = candles[i - 10][2]
        chg_10m = abs(price_now - price_10ago) / price_10ago * 100 if price_10ago > 0 else 0

        # 60분 가격 변동
        price_60ago = candles[i - 60][2] if i >= 60 else candles[0][2]
        chg_60m = (price_now - price_60ago) / price_60ago * 100 if price_60ago > 0 else 0

        # 거래량 비교: 최근 10분 vs 이전 50분 평균
        vol_recent = sum(candles[j][5] for j in range(i - 9, i + 1))
        vol_prev = sum(candles[j][5] for j in range(i - 59, i - 9))
        avg_prev = vol_prev / 50 if vol_prev > 0 else 0.001
        avg_recent = vol_recent / 10
        vol_ratio = avg_recent / avg_prev if avg_prev > 0 else 0

        # 거래대금 (10분)
        tv_10m = sum(candles[j][2] * candles[j][5] for j in range(i - 9, i + 1))

        # 거래대금 최소 필터 (너무 소량 제외)
        if tv_10m < 3_000_000:
            continue

        # 고점 대비 현재 위치 (60분 내)
        high_60 = max(candles[j][3] for j in range(max(0, i - 59), i + 1))
        from_high = (price_now - high_60) / high_60 * 100 if high_60 > 0 else 0

        # 매집 감지: 가격 정체 + 거래량 폭증 (가장 선행하는 신호)
        # tv_10m >= 30M 필터로 잡코인 제외
        is_accumulation = (chg_10m < 1.5 and vol_ratio >= 8 and tv_10m >= 30_000_000)

        hit = False
        reason = []
        priority = 0  # 낮을수록 우선

        if is_accumulation:
            hit = True
            reason.append(f'ACCUM vol {vol_ratio:.0f}x price flat')
            priority = 0  # 최우선 — 아직 안 올랐으니 진입 가능
        if chg_10m >= 2:
            hit = True
            reason.append(f'10m {chg_10m:+.1f}%')
            priority = max(priority, 1)
        if vol_ratio >= 5 and not is_accumulation:
            hit = True
            reason.append(f'vol {vol_ratio:.0f}x')
            priority = max(priority, 1)
        if chg_60m >= 10:
            hit = True
            reason.append(f'60m {chg_60m:+.1f}%')
            priority = max(priority, 2)  # 이미 많이 오른 것

        if hit:
            candidates.append({
                'coin': coin,
                'price': price_now,
                'chg_10m': round(chg_10m, 2),
                'chg_60m': round(chg_60m, 2),
                'vol_ratio': round(vol_ratio, 1),
                'tv_10m': tv_10m,
                'from_high': round(from_high, 1),
                'reason': ', '.join(reason),
                'priority': priority,
                'accumulation': is_accumulation,
            })

        time.sleep(0.05)

    # 우선순위: 매집(0) > 초기 상승(1) > 이미 오른 것(2), 같은 우선순위 내 거래량 순
    candidates.sort(key=lambda x: (x['priority'], -x['vol_ratio']))
    return candidates


def render_scan_chart(coin, minutes=60):
    """후보 코인 차트 렌더링 — scan_charts/ 폴더에 저장."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    raw = fetch_candles(coin)
    if not raw:
        return None
    candles = parse(raw)
    if len(candles) < minutes:
        return None

    data = []
    for row in candles[-minutes:]:
        ts = int(row[0]) / 1000
        dt = datetime.fromtimestamp(ts, KST)
        o, c, h, l, v = row[1], row[2], row[3], row[4], row[5]
        data.append((dt, o, h, l, c, v))

    times = [d[0] for d in data]
    opens = [d[1] for d in data]
    highs = [d[2] for d in data]
    lows = [d[3] for d in data]
    closes = [d[4] for d in data]
    vols = [d[5] for d in data]

    # MA
    def ma(values, n):
        result = []
        for i in range(len(values)):
            if i < n - 1:
                result.append(None)
            else:
                result.append(sum(values[i-n+1:i+1]) / n)
        return result

    ma5 = ma(closes, 5)
    ma15 = ma(closes, 15)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8),
                                    gridspec_kw={'height_ratios': [3, 1]}, sharex=True)

    # 제목에 핵심 수치 포함
    first_c = closes[0]
    last_c = closes[-1]
    total_chg = (last_c - first_c) / first_c * 100
    high_p = max(highs)
    from_high = (last_c - high_p) / high_p * 100

    fig.suptitle(
        f'{coin}/KRW 1min ({minutes}min)  {times[-1]:%H:%M}  '
        f'Now={last_c:,.0f}  Chg={total_chg:+.1f}%  FromHigh={from_high:+.1f}%',
        fontsize=13, fontweight='bold'
    )

    # 캔들스틱
    for i, (t, o, h, l, c, v) in enumerate(data):
        color = '#e74c3c' if c >= o else '#3498db'
        ax1.plot([t, t], [l, h], color=color, linewidth=0.8)
        ax1.plot([t, t], [o, c], color=color, linewidth=3)

    # MA
    valid5 = [(t, v) for t, v in zip(times, ma5) if v is not None]
    valid15 = [(t, v) for t, v in zip(times, ma15) if v is not None]
    if valid5:
        ax1.plot([t for t, v in valid5], [v for t, v in valid5],
                 color='orange', linewidth=1, label='MA5', alpha=0.8)
    if valid15:
        ax1.plot([t for t, v in valid15], [v for t, v in valid15],
                 color='blue', linewidth=1, label='MA15', alpha=0.8)

    ax1.legend(loc='upper left', fontsize=9)
    ax1.set_ylabel('Price')
    ax1.grid(True, alpha=0.3)

    # 현재가 표시
    ax1.annotate(f'{last_c:,.0f} ({total_chg:+.1f}%)',
                 xy=(times[-1], last_c), fontsize=11, fontweight='bold',
                 color='#e74c3c' if total_chg >= 0 else '#3498db')

    # 거래량
    for i, (t, o, h, l, c, v) in enumerate(data):
        color = '#e74c3c' if c >= o else '#3498db'
        ax2.bar(t, v, width=0.0005, color=color, alpha=0.7)
    ax2.set_ylabel('Volume')
    ax2.grid(True, alpha=0.3)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.xticks(rotation=45)
    plt.tight_layout()

    os.makedirs(CHART_DIR, exist_ok=True)
    filename = os.path.join(CHART_DIR, f'{coin}.png')
    plt.savefig(filename, dpi=100, bbox_inches='tight')
    plt.close()
    return filename


def scan_and_render(max_charts=20, minutes=60):
    """전체 파이프라인: 거름망 → 차트 렌더링."""
    now = datetime.now(KST)
    print(f'[{now:%H:%M:%S}] Visual Scanner start')

    coins = load_coins()
    print(f'  Scanning {len(coins)} coins...')

    candidates = quick_filter(coins)
    accum = [c for c in candidates if c.get('accumulation')]
    others = [c for c in candidates if not c.get('accumulation')]

    if accum:
        print(f'\n  *** ACCUMULATION DETECTED ({len(accum)}) — price flat + volume surge ***')
        for c in accum:
            print(f'  >>> {c["coin"]:>10}  {c["price"]:>12,.0f}  {c["reason"]:<35}  '
                  f'tv10={c["tv_10m"]/1e6:>5.0f}M  fromHigh={c["from_high"]:+.1f}%')

    print(f'\n  === {len(others)} other candidates ===')
    for c in others:
        print(f'  {c["coin"]:>10}  {c["price"]:>12,.0f}  {c["reason"]:<35}  '
              f'tv10={c["tv_10m"]/1e6:>5.0f}M  fromHigh={c["from_high"]:+.1f}%')

    if not candidates:
        print('  No activity detected.')
        return candidates, []

    # 상위 N개만 차트 렌더링
    to_render = candidates[:max_charts]
    print(f'\n  Rendering {len(to_render)} charts...')
    charts = []
    for c in to_render:
        f = render_scan_chart(c['coin'], minutes)
        if f:
            charts.append((c['coin'], f))
            print(f'    {c["coin"]}: {f}')

    print(f'\n  Done. {len(charts)} charts in {CHART_DIR}/')
    return candidates, charts


if __name__ == '__main__':
    if '--coin' in sys.argv:
        idx = sys.argv.index('--coin')
        coin = sys.argv[idx + 1]
        mins = int(sys.argv[idx + 2]) if len(sys.argv) > idx + 2 else 60
        f = render_scan_chart(coin, mins)
        print(f'Chart: {f}')
    elif '--filter' in sys.argv:
        coins = load_coins()
        candidates = quick_filter(coins)
        for c in candidates:
            print(f'{c["coin"]:>10}  {c["price"]:>12,.0f}  {c["reason"]:<30}  '
                  f'tv10={c["tv_10m"]/1e6:>5.0f}M  fromHigh={c["from_high"]:+.1f}%')
    else:
        scan_and_render()
