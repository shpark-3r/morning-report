"""
사용자가 본 (A) 타입 점진 상승 펌프 분석.

타겟 코인: JOE, XION, ENJ, XYO, D, COS, TRAC
- 각 코인의 펌프 시점 자동 탐지
- 1분봉 패턴 추출 (펌프 시작~끝)
- 누적 패턴 신호 정의 + 검증
"""
import json
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def load_coin_1m(coin):
    fp = f'data/bithumb_1m/{coin}.json'
    if not os.path.exists(fp):
        return None
    with open(fp) as f:
        raw = json.load(f)
    candles = []
    for row in raw:
        try:
            ts = int(row[0])
            o, c, h, l, v = float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5])
            candles.append((ts, o, c, h, l, v))
        except (ValueError, IndexError):
            continue
    return candles


def find_gradual_pumps(candles, min_total_gain=30, min_duration=15, max_duration=120):
    """점진적 펌프 탐지: N~M분 동안 누적 +X% 이상 상승하는 구간"""
    n = len(candles)
    pumps = []
    i = 0
    while i < n - max_duration:
        start_close = candles[i][2]
        if start_close <= 0:
            i += 1
            continue
        # 미래 max_duration 안에서 max gain 찾기
        best_gain = 0
        best_j = i
        for j in range(i + min_duration, min(i + max_duration + 1, n)):
            high_in_range = max(candles[k][3] for k in range(i, j + 1))
            gain = (high_in_range - start_close) / start_close * 100
            if gain >= min_total_gain and gain > best_gain:
                best_gain = gain
                best_j = j
        if best_gain >= min_total_gain:
            duration = best_j - i
            pumps.append({
                'start_i': i, 'end_i': best_j,
                'duration': duration,
                'gain': best_gain,
                'start_ts': candles[i][0],
                'start_close': start_close,
            })
            i = best_j + 5  # skip past this pump
        else:
            i += 1
    return pumps


def main():
    coins_to_check = ['JOE', 'XION', 'ENJ', 'XYO', 'D', 'COS', 'TRAC', 'XTER']

    all_pumps = []
    for coin in coins_to_check:
        candles = load_coin_1m(coin)
        if not candles:
            print(f'{coin}: no data')
            continue
        pumps = find_gradual_pumps(candles, min_total_gain=30, min_duration=10, max_duration=120)
        print(f'\n{coin}: {len(candles)} candles, {len(pumps)} gradual pumps')
        for p in pumps:
            dt = datetime.fromtimestamp(p['start_ts'] / 1000, KST)
            print(f'  {dt:%m-%d %H:%M} +{p["gain"]:.1f}% over {p["duration"]} min (start price={p["start_close"]:.4f})')
            all_pumps.append({**p, 'coin': coin})

    print(f'\n{"=" * 80}')
    print(f'Total gradual pumps found: {len(all_pumps)}')
    print(f'{"=" * 80}')

    # === 핵심: JOE, XION, ENJ의 사용자가 본 펌프와 매칭 ===
    print(f'\n=== Look at the SPECIFIC pumps user mentioned ===')
    target_pumps = [
        ('ENJ', '2026-04-09', 11, 12),  # 11~12시 KST
        ('JOE', '2026-04-08', 6, 8),
        ('XION', '2026-04-07', 14, 16),
    ]
    for coin, date, hour_start, hour_end in target_pumps:
        candles = load_coin_1m(coin)
        if not candles:
            continue
        # 해당 시간대 캔들 찾기
        relevant = []
        for c in candles:
            dt = datetime.fromtimestamp(c[0] / 1000, KST)
            if dt.strftime('%Y-%m-%d') == date and hour_start <= dt.hour <= hour_end:
                relevant.append((dt, *c))
        if not relevant:
            print(f'\n{coin} {date} {hour_start}-{hour_end}시: NO DATA in window')
            continue
        # 시작/최고가 표시
        relevant.sort()
        first = relevant[0]
        max_h = max(r[4] for r in relevant)  # high index 4
        first_close = first[3]
        gain = (max_h - first_close) / first_close * 100 if first_close > 0 else 0
        print(f'\n{coin} {date} {hour_start}-{hour_end}시:')
        print(f'  Window: {first[0]:%H:%M} ~ {relevant[-1][0]:%H:%M} ({len(relevant)} 1m candles)')
        print(f'  Start close: {first_close:.4f}')
        print(f'  Max high: {max_h:.4f}')
        print(f'  Total gain (close to high): +{gain:.1f}%')

        # 미니 candlestick: 매 5분마다 OHLCV 표시
        print(f'  Sample (every 5 min):')
        for k in range(0, len(relevant), 5):
            r = relevant[k]
            dt, ts, o, c, h, l, v = r
            change = (c - o) / o * 100 if o > 0 else 0
            tv = c * v
            print(f'    {dt:%H:%M}  O={o:>8.4f} C={c:>8.4f} H={h:>8.4f} L={l:>8.4f} ({change:>+5.1f}%) tv={tv/1e6:.0f}M v={v:.0f}')

        # 우리 기존 신호 (vol_mult 50x + 양봉 + gain 5%) 가 이 구간에서 트리거됐는지
        print(f'  Old signal triggers (vol_mult>=50, gain>=5%, tv>=10M):')
        old_trigs = 0
        for k in range(30, len(relevant)):
            ts, o, c, h, l, v = relevant[k][1], relevant[k][2], relevant[k][3], relevant[k][4], relevant[k][5], relevant[k][6]
            if c <= o or v <= 0:
                continue
            gain_bar = (c - o) / o * 100
            if gain_bar < 5:
                continue
            tv = c * v
            if tv < 10e6:
                continue
            base_vol = sum(relevant[m][6] for m in range(max(0, k - 30), k)) / min(30, k)
            if base_vol <= 0:
                continue
            vr = v / base_vol
            if vr >= 50:
                dt = relevant[k][0]
                print(f'    {dt:%H:%M}  vr={vr:.0f}x gain={gain_bar:.1f}% (TRIGGERED)')
                old_trigs += 1
        if old_trigs == 0:
            print(f'    NONE - old signal missed this entire pump.')

        # 누적 신호: 직전 5/10/15분 누적 vol과 가격 상승
        print(f'  CUMULATIVE signal check (lookback 10 min):')
        cum_trigs = 0
        for k in range(30, len(relevant)):
            past_5_vol = sum(relevant[m][6] for m in range(max(0, k - 5), k))
            base_vol_30 = sum(relevant[m][6] for m in range(max(0, k - 35), max(0, k - 5))) / 30
            if base_vol_30 <= 0:
                continue
            vol_ratio_5 = past_5_vol / (base_vol_30 * 5)
            # 직전 5분 누적 가격 변화
            if k >= 5:
                price_5 = (relevant[k - 1][3] - relevant[k - 5][2]) / relevant[k - 5][2] * 100 if relevant[k - 5][2] > 0 else 0
            else:
                price_5 = 0
            # 양봉 비율
            up_count = sum(1 for m in range(max(0, k - 5), k) if relevant[m][3] > relevant[m][2])
            if vol_ratio_5 >= 5 and price_5 >= 5 and up_count >= 3:
                dt = relevant[k][0]
                cum_trigs += 1
                if cum_trigs <= 5:
                    print(f'    {dt:%H:%M}  vol_ratio_5min={vol_ratio_5:.1f}x price_5min={price_5:+.1f}% up_count={up_count}/5 (TRIGGERED)')
        print(f'    Total cumulative triggers: {cum_trigs}')


if __name__ == '__main__':
    main()
