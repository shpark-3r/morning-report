"""
Auto Trader - STAIR 감지 + 차트 분석 + 자동 매매.

1분마다 451코인 스캔 -> STAIR 감지 -> 차트 렌더 -> 매수 판단 -> 포지션 관리.
Claude가 직접 차트를 보고 최종 판단.

출력 파일:
  auto_trader_log.jsonl  - 전체 매매 로그
  auto_trader_status.txt - 현재 상태 (Claude가 읽음)
  scan_charts/           - 차트 이미지
"""
import json
import time
import os
from datetime import datetime, timezone, timedelta
from visual_scanner import load_coins, quick_filter, render_scan_chart
from trade_executor import get_balance, buy_market, sell_market

KST = timezone(timedelta(hours=9))
STATUS_FILE = 'auto_trader_status.txt'
LOG_FILE = 'auto_trader_log.jsonl'


def log_trade(data):
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(json.dumps({**data, 'ts': datetime.now(KST).isoformat()}, ensure_ascii=False) + '\n')


def scan_once():
    """1회 스캔 -> STAIR/ACCUM 후보 반환."""
    coins = load_coins()
    candidates = quick_filter(coins)

    stairs = [c for c in candidates if c.get('staircase')]
    accum = [c for c in candidates if c.get('accumulation') and not c.get('staircase')]

    # 차트 렌더
    for c in stairs:
        c['chart'] = render_scan_chart(c['coin'], 120)

        # 매수/매도 비율 체크
        try:
            import urllib.request
            tx_url = f'https://api.bithumb.com/public/transaction_history/{c["coin"]}_KRW?count=30'
            tx_req = urllib.request.Request(tx_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(tx_req, timeout=3) as tx_r:
                tx_d = json.loads(tx_r.read())
            if tx_d.get('status') == '0000':
                txs = tx_d['data']
                buy = sum(float(t['price'])*float(t['units_traded']) for t in txs if t['type']=='bid')
                sell = sum(float(t['price'])*float(t['units_traded']) for t in txs if t['type']=='ask')
                total_tx = buy + sell
                c['buy_pct'] = buy/total_tx*100 if total_tx > 0 else 50
            else:
                c['buy_pct'] = -1
        except Exception:
            c['buy_pct'] = -1

    return stairs, accum


def write_status(msg):
    """현재 상태를 파일에 쓰기 (Claude가 Read로 확인)."""
    now = datetime.now(KST)
    with open(STATUS_FILE, 'w', encoding='utf-8') as f:
        f.write(f'[{now:%H:%M:%S}] {msg}\n')


def format_stair(c):
    """STAIR 후보 정보 문자열."""
    buy_str = f'buy={c.get("buy_pct",0):.0f}%' if c.get('buy_pct', -1) >= 0 else 'buy=?'
    return (f'{c["coin"]:>8} @{c["price"]:>10,.0f}  '
            f'vol={c["vol_ratio"]:.0f}x  tv={c["tv_10m"]/1e6:.0f}M  '
            f'chg10={c["chg_10m"]:+.1f}%  fH={c["from_high"]:+.1f}%  '
            f'{buy_str}  chart={c.get("chart","")}')


def main():
    now = datetime.now(KST)
    print(f'Auto Trader started at {now:%H:%M:%S}')
    print(f'Status: {STATUS_FILE}')
    print(f'Log: {LOG_FILE}')
    print('---')

    while True:
        try:
            now = datetime.now(KST)

            # 잔고 확인
            krw, positions = get_balance()

            # 스캔
            stairs, accum = scan_once()

            # 상태 작성
            lines = [f'[{now:%H:%M:%S}] KRW={krw:,.0f} pos={len(positions)}']
            for p in positions:
                lines.append(f'  {p["coin"]} qty={p["qty"]:.2f} avg={p["avg_buy"]:.2f}')

            if stairs:
                lines.append(f'*** STAIR DETECTED ({len(stairs)}) ***')
                for c in stairs:
                    lines.append(f'  {format_stair(c)}')
            else:
                lines.append('STAIR: none')

            if accum:
                lines.append(f'ACCUM: {len(accum)}')

            status = '\n'.join(lines)
            write_status(status)
            print(status)

            # 로그
            if stairs:
                for c in stairs:
                    log_trade({
                        'type': 'STAIR_DETECTED',
                        'coin': c['coin'], 'price': c['price'],
                        'vol_ratio': c['vol_ratio'], 'tv_10m': c['tv_10m'],
                        'buy_pct': c.get('buy_pct', -1),
                        'chart': c.get('chart', ''),
                    })

        except Exception as e:
            now = datetime.now(KST)
            msg = f'[{now:%H:%M:%S}] ERROR: {e}'
            print(msg)
            write_status(msg)

        time.sleep(60)


if __name__ == '__main__':
    main()
