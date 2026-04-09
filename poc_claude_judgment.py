"""
Claude judgment PoC.

각 strict signal에 대해:
1. 신호 시점 직전 60분 1분봉 차트 데이터를 텍스트로 출력
2. (이상적으로는 Claude API 호출, 여기선 사람/Claude가 직접 보고 판단)
3. 신호 시점 이후 60분 데이터로 outcome 측정

목표: 사람/Claude가 차트 보고 판단했다면 EV 어떻게 됐을지 시뮬

여기선 텍스트 출력만. 진짜 실시간은 Anthropic API + tool use로 다음 단계.
"""
import json
import os
from datetime import datetime, timezone, timedelta
from analyze_realistic_simulation import load_candles_1m, find_adaptive_signals, apply_costs
from analyze_adaptive_trailing import simulate_adaptive_trailing

KST = timezone(timedelta(hours=9))


def render_chart_text(candles, center_i, before=60, after=60):
    """텍스트로 차트 표현. 1분봉 OHLCV + 가격 변화 + vol burst 마커"""
    start = max(0, center_i - before)
    end = min(len(candles), center_i + after + 1)

    lines = []
    lines.append(f'{"idx":>4} {"time":<10} {"O":>8} {"H":>8} {"L":>8} {"C":>8} {"V":>10} {"tv(M)":>7} {"chg%":>6} {"marker":<10}')

    base_close = candles[center_i][2]
    base_vol = sum(candles[j][5] for j in range(max(0, center_i - 30), center_i)) / 30 if center_i >= 30 else 1

    for j in range(start, end):
        ts, o, c, h, l, v = candles[j]
        dt = datetime.fromtimestamp(ts / 1000, KST)
        chg = (c - o) / o * 100 if o > 0 else 0
        tv = c * v / 1e6
        rel = (c - base_close) / base_close * 100 if base_close > 0 else 0
        vol_x = v / base_vol if base_vol > 0 else 0
        marker = ''
        if j == center_i:
            marker = '<-- SIGNAL'
        elif j == center_i + 1:
            marker = '<-- ENTRY'
        elif vol_x >= 5:
            marker = f'vol{vol_x:.0f}x'
        bar = '+' if c > o else '-' if c < o else '='
        lines.append(f'{j:>4} {dt:%m-%d %H:%M} {o:>8.4f} {h:>8.4f} {l:>8.4f} {c:>8.4f} {v:>10.0f} {tv:>6.0f}M {chg:>+5.1f}% {marker} [{bar}] rel={rel:+.1f}%')

    return '\n'.join(lines)


def main():
    coins = load_candles_1m()
    sigs = find_adaptive_signals(coins)
    print(f'Loaded {len(coins)} coins, {len(sigs)} signals')

    # Strict + FP filter
    enriched = []
    for s in sigs:
        candles = coins[s['coin']]
        i = s['i']
        if i < 60:
            continue
        tv_5 = sum(candles[j][2] * candles[j][5] for j in range(i - 5, i))
        past_5 = sum(candles[j][5] for j in range(i - 5, i))
        base_30 = sum(candles[j][5] for j in range(i - 35, i - 5)) / 30
        vr = (past_5 / 5) / base_30 if base_30 > 0 else 0
        o, c = candles[i][1], candles[i][2]
        bar_gain = (c - o) / o * 100 if o > 0 else 0
        triggered_gain = 0
        for lb_min, min_g in [(5, 5), (10, 7), (15, 10), (30, 15)]:
            if i >= lb_min:
                sc = candles[i - lb_min][2]
                if sc > 0:
                    cg = (c - sc) / sc * 100
                    if cg >= min_g:
                        triggered_gain = cg
                        break
        dt = datetime.fromtimestamp(candles[i][0] / 1000, KST)
        if tv_5 >= 200e6 and vr >= 10:
            enriched.append({**s, 'tv_5': tv_5, 'vr5': vr, 'bar_gain': bar_gain, 'triggered_gain': triggered_gain, 'dt': dt})

    print(f'Strict signals: {len(enriched)}')

    # 사용자가 본 케이스 + 다른 winner/loser 섞어서
    sample_targets = ['ENJ', 'JOE', 'XION', 'XYO', 'COMP', 'JTO', 'OPEN', 'PYR', 'PEAQ']

    for target in sample_targets:
        matches = [s for s in enriched if s['coin'] == target]
        if not matches:
            print(f'\n=== {target}: NO STRICT SIGNAL ===')
            # Try in non-strict
            non_strict = []
            for s in sigs:
                if s['coin'] == target:
                    candles = coins[s['coin']]
                    i = s['i']
                    if i >= 60:
                        non_strict.append((s, datetime.fromtimestamp(s['ts']/1000, KST)))
            if non_strict:
                # Take first one
                s, dt = non_strict[0]
                print(f'  Showing first non-strict signal: {dt:%m-%d %H:%M}')
                print(render_chart_text(coins[s['coin']], s['i'], before=30, after=60))
            continue

        for s in matches[:1]:  # 첫 1건만
            candles = coins[s['coin']]
            print(f'\n{"="*100}')
            print(f'{target} {s["dt"]:%m-%d %H:%M} | tv5={s["tv_5"]/1e6:.0f}M vr5={s["vr5"]:.1f}x triggered_gain={s["triggered_gain"]:+.1f}% bar={s["bar_gain"]:+.1f}%')
            print('='*100)
            print(render_chart_text(candles, s['i'], before=30, after=30))

            # D 시뮬 결과
            stages_D = [(5, 4, 2), (10, 3, 6), (20, 2, 15), (35, 1.5, 28)]
            r = simulate_adaptive_trailing(candles, s['i'] + 1, stages_D, 5, 60)
            print(f'\n  D adaptive trailing simulated outcome: {r:+.2f}%')


if __name__ == '__main__':
    main()
