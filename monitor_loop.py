"""
1분 루프 모니터링 — 매집 감지 + 차트 렌더링.
Claude가 output 파일을 읽고 차트를 직접 분석.

출력: monitor_output.txt (상태), scan_charts/ (차트 이미지)
"""
import time
import json
import os
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
OUTPUT_FILE = 'monitor_output.txt'
ALERT_FILE = 'monitor_alerts.jsonl'


def run_once():
    from visual_scanner import load_coins, quick_filter, render_scan_chart

    now = datetime.now(KST)
    coins = load_coins()
    candidates = quick_filter(coins)

    accum = [c for c in candidates if c.get('accumulation')]
    movers = [c for c in candidates if not c.get('accumulation')]

    lines = []
    lines.append(f'[{now:%H:%M:%S}] scan={len(coins)} candidates={len(candidates)} accum={len(accum)}')

    # 매집 신호 — 최우선
    if accum:
        lines.append(f'*** ACCUMULATION ({len(accum)}) ***')
        for c in accum:
            lines.append(f'  >>> {c["coin"]:>10} @{c["price"]:>12,.0f}  '
                         f'vol={c["vol_ratio"]:.0f}x  tv10={c["tv_10m"]/1e6:.0f}M  '
                         f'chg10={c["chg_10m"]:+.1f}%  chg60={c["chg_60m"]:+.1f}%')
            # 매집 신호는 즉시 차트 렌더
            chart = render_scan_chart(c['coin'], 120)
            if chart:
                lines.append(f'       CHART: {chart}')

            # alert 기록
            with open(ALERT_FILE, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    'ts': now.isoformat(), 'type': 'ACCUM',
                    'coin': c['coin'], 'price': c['price'],
                    'vol_ratio': c['vol_ratio'], 'tv_10m': c['tv_10m'],
                }, ensure_ascii=False) + '\n')

    # 상위 무버 (가격 변동 있는 것) — 상위 5개
    top_movers = sorted(movers, key=lambda x: -x['vol_ratio'])[:5]
    if top_movers:
        lines.append(f'Top movers ({len(movers)} total):')
        for c in top_movers:
            tag = ''
            # 새로 등장한 코인이면 차트도 렌더
            if c['vol_ratio'] >= 7 or abs(c['chg_10m']) >= 3:
                chart = render_scan_chart(c['coin'], 120)
                if chart:
                    tag = f' CHART:{chart}'
            lines.append(f'  {c["coin"]:>10} @{c["price"]:>12,.0f}  '
                         f'{c["reason"]:<30}  tv10={c["tv_10m"]/1e6:.0f}M  '
                         f'fH={c["from_high"]:+.1f}%{tag}')

    if not accum and not movers:
        lines.append('  (quiet)')

    result = '\n'.join(lines)
    print(result)

    # output 파일에 append (Claude가 읽을 수 있도록)
    with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
        f.write(result + '\n\n')

    return len(accum), len(movers)


def main():
    print(f'Monitor loop started at {datetime.now(KST):%H:%M:%S}')
    print(f'Output: {OUTPUT_FILE}')
    print(f'Charts: scan_charts/')
    print('---')

    # 기존 output 초기화
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(f'=== Monitor started {datetime.now(KST):%Y-%m-%d %H:%M:%S} ===\n\n')

    while True:
        try:
            a, m = run_once()
        except Exception as e:
            now = datetime.now(KST)
            msg = f'[{now:%H:%M:%S}] ERROR: {e}'
            print(msg)
            with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
                f.write(msg + '\n\n')

        time.sleep(60)


if __name__ == '__main__':
    main()
