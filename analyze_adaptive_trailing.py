"""
Adaptive trailing stop 시뮬:
사용자 반박 반영:
1. 진입 직후 grace period (5~10분): SL only, trailing 비활성
2. Profit-scaled trailing: 수익 누적될수록 trail % 좁아짐
3. Profit lock: +X% 도달 후엔 entry 위에서만 trail (절대 손실 X)

스테이지:
  Stage 0 (entry ~ +5%): SL -7~10% only, no trailing
  Stage 1 (+5% ~ +15%): trail 5%, profit lock at +1% (최소 +1% 보장)
  Stage 2 (+15% ~ +30%): trail 3%, profit lock at +10%
  Stage 3 (+30% ~ +50%): trail 2%, profit lock at +20%
  Stage 4 (+50%+): trail 1.5%, profit lock at +35%

비교:
- 기존 trail3/SL7/60m
- adaptive_v1 (위 stage 정의)
- adaptive_v2 (조금 다른 stage)
- adaptive 어그레시브
"""
import json
import os
from datetime import datetime, timezone, timedelta
from analyze_realistic_simulation import load_candles_1m, find_adaptive_signals, apply_costs

KST = timezone(timedelta(hours=9))


def simulate_adaptive_trailing(candles, entry_i, stages, init_sl, max_hold):
    """
    stages: list of (profit_threshold_pct, trail_pct, profit_lock_pct)
      예: [(5, 5, 1), (15, 3, 10), (30, 2, 20), (50, 1.5, 35)]

    Logic:
      진입 후 max_high 추적.
      현재 max_gain = (max_high - entry) / entry * 100
      stage 결정: max_gain >= stage[i][0] 이면 stage i+1 적용
      현재 stage의 trail_pct로 trail_p 계산.
      profit_lock 적용: trail_p < entry * (1 + lock/100) 이면 entry * (1 + lock/100)
      Stage 0이면 trailing 비활성, init_sl만 적용.
      lower(low) <= trail_p 또는 sl_p 이면 청산.
    """
    if entry_i >= len(candles):
        return None
    entry = candles[entry_i][1]
    if entry <= 0:
        return None
    sl_p = entry * (1 - init_sl / 100)
    max_high = entry

    end = min(entry_i + max_hold, len(candles))
    for j in range(entry_i, end):
        ts, o, c, h, l, v = candles[j]

        # max_high 업데이트
        if h > max_high:
            max_high = h

        # current max gain
        max_gain = (max_high - entry) / entry * 100

        # stage 결정
        current_stage_idx = 0
        for idx, (thr, _, _) in enumerate(stages):
            if max_gain >= thr:
                current_stage_idx = idx + 1

        # SL 체크 (Stage 0이면 init_sl)
        if current_stage_idx == 0:
            # Stage 0: SL only
            if l <= sl_p:
                return -init_sl
        else:
            # Stage 1+
            stage = stages[current_stage_idx - 1]
            _, trail_pct, lock_pct = stage
            trail_p = max_high * (1 - trail_pct / 100)
            lock_p = entry * (1 + lock_pct / 100)
            if trail_p < lock_p:
                trail_p = lock_p
            if l <= trail_p and j > entry_i:
                return (trail_p - entry) / entry * 100

    # 시간 만료
    return (candles[end - 1][2] - entry) / entry * 100


def main():
    coins = load_candles_1m()
    print(f'Loaded {len(coins)} coins')

    # Adaptive 신호 (전체)
    sigs = find_adaptive_signals(coins)
    print(f'All adaptive signals: {len(sigs)}')

    # Strict 필터
    strict = []
    for s in sigs:
        candles = coins[s['coin']]
        i = s['i']
        tv_5 = sum(candles[j][2] * candles[j][5] for j in range(max(0, i - 5), i))
        past_5 = sum(candles[j][5] for j in range(max(0, i - 5), i))
        base_30 = sum(candles[j][5] for j in range(max(0, i - 35), max(0, i - 5))) / 30 if i >= 35 else 0
        vr = (past_5 / 5) / base_30 if base_30 > 0 else 0
        if tv_5 >= 200e6 and vr >= 10:
            strict.append({**s, 'tv_5': tv_5, 'vr': vr})
    print(f'Strict signals: {len(strict)}')

    # Stages 후보
    stages_candidates = [
        ('A: gentle', [(5, 5, 1), (15, 3, 10), (30, 2, 20), (50, 1.5, 35)]),
        ('B: aggressive lock', [(3, 5, 0), (10, 3, 5), (20, 2, 12), (35, 1.5, 25)]),
        ('C: wide initial', [(7, 7, 2), (15, 5, 8), (25, 3, 18), (40, 2, 30)]),
        ('D: tight lock', [(5, 4, 2), (10, 3, 6), (20, 2, 15), (35, 1.5, 28)]),
        ('E: very wide', [(10, 7, 3), (20, 5, 12), (35, 3, 25), (60, 2, 45)]),
    ]
    init_sls = [5, 7, 10]
    max_holds = [60, 120, 180]

    print(f'\n=== Adaptive trailing on STRICT signals (n={len(strict)}) ===')
    print(f'  {"strategy":<35} {"init_sl":<8} {"hold":<6} {"win%":>7} {"gross":>10} {"@0.3%":>10} {"@1%":>10}')
    print('  ' + '-' * 100)

    best_label = None
    best_ev = -999
    for label, stages in stages_candidates:
        for init_sl in init_sls:
            for hold in max_holds:
                gross = []
                for s in strict:
                    r = simulate_adaptive_trailing(coins[s['coin']], s['i'] + 1, stages, init_sl, hold)
                    if r is not None:
                        gross.append(r)
                if not gross:
                    continue
                n = len(gross)
                wins = sum(1 for x in gross if x > 0)
                avg_g = sum(gross) / n
                avg03 = sum(apply_costs(x, 0.003) for x in gross) / n
                avg10 = sum(apply_costs(x, 0.010) for x in gross) / n
                marker = ''
                if avg03 > 0:
                    marker = ' *'
                if avg03 > best_ev:
                    best_ev = avg03
                    best_label = f'{label} sl={init_sl} hold={hold}'
                print(f'  {label:<35} {init_sl:<8} {hold:<6} {wins/n*100:>6.1f}% {avg_g:>+9.2f}% {avg03:>+9.2f}% {avg10:>+9.2f}%{marker}')

    print(f'\n  Best: {best_label} → EV @0.3% = {best_ev:+.2f}%')

    # Best 전략으로 사용자 사례 검증
    print('\n=== User cases - best adaptive strategy ===')
    target_pumps = [
        ('ENJ', '2026-04-09', 11),
        ('JOE', '2026-04-08', 6),
        ('XION', '2026-04-07', 14),
        ('XYO', '2026-03-31', 18),
    ]
    # parse best label
    if best_label:
        parts = best_label.split()
        label = parts[0] + ' ' + parts[1]  # e.g. "C: wide initial"
        sl_val = int(parts[2].split('=')[1])
        hold_val = int(parts[3].split('=')[1])
        # find stages
        for lab, stgs in stages_candidates:
            if lab == label:
                best_stages = stgs
                break
        else:
            best_stages = stages_candidates[0][1]

        for coin, date, hour in target_pumps:
            for s in strict:
                if s['coin'] != coin:
                    continue
                dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
                if dt.strftime('%Y-%m-%d') == date and dt.hour == hour:
                    candles = coins[s['coin']]
                    r = simulate_adaptive_trailing(candles, s['i'] + 1, best_stages, sl_val, hold_val)
                    if r is not None:
                        net = apply_costs(r, 0.003)
                        print(f'  {coin} {date} {hour}시 신호 → exit {r:+.2f}% (net @0.3% slip: {net:+.2f}%)')
                    break

    # 모든 strict 신호의 outcome 분포
    if best_label:
        gross = []
        for s in strict:
            r = simulate_adaptive_trailing(coins[s['coin']], s['i'] + 1, best_stages, sl_val, hold_val)
            if r is not None:
                gross.append((s, r))
        gross.sort(key=lambda x: -x[1])
        print(f'\n=== All 31 strict signals - best adaptive outcome ===')
        for s, r in gross:
            dt = datetime.fromtimestamp(s['ts'] / 1000, KST)
            net = apply_costs(r, 0.003)
            marker = '+++' if r >= 10 else ('++' if r >= 5 else ('+' if r > 0 else ('-' if r > -3 else '---')))
            print(f'  {marker} {s["coin"]:>10} {dt:%m-%d %H:%M} tv5={s["tv_5"]/1e6:>4.0f}M  result={r:+.2f}% (net {net:+.2f}%)')


if __name__ == '__main__':
    main()
