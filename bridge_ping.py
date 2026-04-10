"""
Bridge cron — 1분마다 실행.
1. 워커에게 scan 결과 + 포지션 전송
2. 워커 메시지 수신 + 로그
3. 새 신호 발견 시 즉시 전달
"""
import socket
import json
import time
import subprocess
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
WORKER_IP = '100.107.74.38'
PORT = 9999


def scan_quick():
    """빠른 스캔 (Type A/C만, 속도 우선)"""
    from dual_scanner import load_coins, fetch_candles, parse, check_burst, check_medium, check_quiet_gradual
    coins = load_coins()
    sigs = []
    for coin in coins:
        raw = fetch_candles(coin, '1m')
        if not raw:
            continue
        candles = parse(raw)
        if not candles:
            continue
        for ck, t in [(check_burst, 'A'), (check_medium, 'C'), (check_quiet_gradual, 'D')]:
            r = ck(candles)
            if r:
                sigs.append({'type': t, 'coin': coin, 'price': r['price'], 'detail': r})
        time.sleep(0.05)
    return sigs


def get_account():
    try:
        result = subprocess.run(['python', 'check_account.py'], capture_output=True, text=True, timeout=10, encoding='utf-8', errors='replace')
        return result.stdout.strip()
    except Exception:
        return 'account check failed'


def main():
    now = datetime.now(KST)

    # 스캔
    sigs = scan_quick()

    # 포지션
    acct = get_account()

    # Bridge 전송
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((WORKER_IP, PORT))

        msg = {
            'type': 'cron_report',
            'from': 'researcher',
            'ts': now.isoformat(),
            'signals': len(sigs),
            'signal_list': sigs[:5] if sigs else [],
            'account': acct[:200],
        }

        if sigs:
            msg['alert'] = True
            msg['summary'] = f'SIGNAL! {len(sigs)} found: ' + ', '.join(f'{s["type"]}:{s["coin"]}' for s in sigs[:3])
        else:
            msg['summary'] = f'{now:%H:%M} scan 0 signals'

        s.sendall(json.dumps(msg, ensure_ascii=False).encode('utf-8'))

        # 워커 응답 수신 (최대 5초 폴링)
        s.settimeout(1)
        end_time = time.time() + 5
        while time.time() < end_time:
            try:
                data = s.recv(65536)
                if data:
                    replies = data.decode('utf-8').strip().split('\n')
                    for reply in replies:
                        try:
                            r = json.loads(reply)
                            if r.get('type') != 'ack':
                                print(f'[{now:%H:%M:%S}] WORKER: {json.dumps(r, ensure_ascii=False)[:150]}')
                                with open('bridge_inbox.jsonl', 'a', encoding='utf-8') as f:
                                    f.write(json.dumps(r, ensure_ascii=False) + '\n')
                        except json.JSONDecodeError:
                            pass
            except socket.timeout:
                continue
            except Exception:
                break

        s.close()

        if sigs:
            print(f'[{now:%H:%M:%S}] *** {len(sigs)} SIGNALS sent to worker ***')

    except Exception as e:
        print(f'[{now:%H:%M:%S}] Bridge error: {e}')


if __name__ == '__main__':
    main()
