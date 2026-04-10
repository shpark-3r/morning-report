"""
차트 렌더링 — 빗썸 1분봉 데이터로 캔들차트 + MA + 거래량 생성.
Claude가 Read tool로 이미지 분석 가능.

사용법:
  python chart_render.py CFG          # CFG 최근 60분 차트
  python chart_render.py CFG 120      # CFG 최근 120분
  python chart_render.py CFG 60 save  # 파일 저장 (CFG_chart.png)
"""
import urllib.request
import json
import sys
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def fetch_candles(coin, interval='1m'):
    url = f'https://api.bithumb.com/public/candlestick/{coin}_KRW/{interval}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    return d.get('data', [])


def render_chart(coin, minutes=60, save=True):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    raw = fetch_candles(coin)
    if not raw:
        print(f'{coin}: no data')
        return None

    data = []
    for row in raw[-minutes:]:
        ts = int(row[0]) / 1000
        dt = datetime.fromtimestamp(ts, KST)
        o, c, h, l, v = float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
        data.append((dt, o, h, l, c, v))

    if not data:
        return None

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
    ma60 = ma(closes, min(60, len(closes)))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), gridspec_kw={'height_ratios': [3, 1]}, sharex=True)
    fig.suptitle(f'{coin}/KRW  1min  (last {minutes}min)  {times[-1]:%Y-%m-%d %H:%M}', fontsize=14)

    # 캔들스틱
    for i, (t, o, h, l, c, v) in enumerate(data):
        color = '#e74c3c' if c >= o else '#3498db'
        ax1.plot([t, t], [l, h], color=color, linewidth=0.8)
        ax1.plot([t, t], [o, c], color=color, linewidth=3)

    # MA 라인
    valid_times_5 = [t for t, v in zip(times, ma5) if v is not None]
    valid_ma5 = [v for v in ma5 if v is not None]
    valid_times_15 = [t for t, v in zip(times, ma15) if v is not None]
    valid_ma15 = [v for v in ma15 if v is not None]

    if valid_ma5:
        ax1.plot(valid_times_5, valid_ma5, color='orange', linewidth=1, label='MA5', alpha=0.8)
    if valid_ma15:
        ax1.plot(valid_times_15, valid_ma15, color='blue', linewidth=1, label='MA15', alpha=0.8)

    ax1.legend(loc='upper left', fontsize=9)
    ax1.set_ylabel('Price')
    ax1.grid(True, alpha=0.3)

    # 현재가 + 변동률
    first_close = closes[0]
    last_close = closes[-1]
    chg = (last_close - first_close) / first_close * 100
    ax1.annotate(f'{last_close:,.2f} ({chg:+.1f}%)',
                 xy=(times[-1], last_close), fontsize=11, fontweight='bold',
                 color='#e74c3c' if chg >= 0 else '#3498db')

    # 거래량
    for i, (t, o, h, l, c, v) in enumerate(data):
        color = '#e74c3c' if c >= o else '#3498db'
        ax2.bar(t, v, width=0.0005, color=color, alpha=0.7)
    ax2.set_ylabel('Volume')
    ax2.grid(True, alpha=0.3)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    plt.xticks(rotation=45)
    plt.tight_layout()

    filename = f'{coin}_chart.png'
    if save:
        plt.savefig(filename, dpi=100, bbox_inches='tight')
        plt.close()
        print(f'Saved: {filename}')
        return filename
    else:
        plt.close()
        return None


def scan_and_render(coins=None, minutes=60):
    """여러 코인 차트 한 번에 렌더링"""
    if coins is None:
        coins = ['CFG', 'MERL', 'GRND', 'PCI']
    files = []
    for coin in coins:
        f = render_chart(coin, minutes)
        if f:
            files.append(f)
    return files


if __name__ == '__main__':
    coin = sys.argv[1] if len(sys.argv) > 1 else 'CFG'
    minutes = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    render_chart(coin, minutes)
