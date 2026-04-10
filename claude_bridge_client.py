"""
Claude Bridge — TCP 소켓 클라이언트 (연구원 PC에서 실행)
워커 클로드와 직통 통신.

사용법 (연구원 PC):
  python claude_bridge_client.py <워커PC IP>
  예: python claude_bridge_client.py 172.17.0.50

메시지 형식:
  send({'type': 'signal', 'coin': 'CFG', 'action': 'BUY', 'price': 380, ...})
  send({'type': 'analysis', 'coin': 'PCI', 'summary': '30m +22%', ...})
  send({'type': 'sl_update', 'coin': 'CFG', 'sl': 365, ...})
  send({'type': 'question', 'text': 'CFG BE 룰 제거했나?', ...})
"""
import socket
import json
import sys
import threading
import time
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
PORT = 9999

conn = None
received_messages = []


def connect(host):
    global conn
    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    conn.connect((host, PORT))
    print(f'[{datetime.now(KST):%H:%M:%S}] Connected to {host}:{PORT}')

    # 수신 스레드
    def receiver():
        buffer = b''
        while True:
            try:
                data = conn.recv(65536)
                if not data:
                    break
                buffer += data
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    msg = json.loads(line.decode('utf-8'))
                    received_messages.append(msg)
                    if msg.get('type') != 'ack':
                        print(f'[{datetime.now(KST):%H:%M:%S}] FROM WORKER: {msg.get("type","?")} — {json.dumps(msg, ensure_ascii=False)[:120]}')
            except Exception as e:
                print(f'Disconnected: {e}')
                break

    t = threading.Thread(target=receiver, daemon=True)
    t.start()
    return conn


def send(msg_dict):
    """메시지 전송"""
    if conn is None:
        print('Not connected!')
        return
    msg_dict['_ts'] = datetime.now(KST).isoformat()
    msg_dict['_from'] = 'researcher'
    data = json.dumps(msg_dict, ensure_ascii=False).encode('utf-8')
    conn.sendall(data)
    print(f'[{datetime.now(KST):%H:%M:%S}] SENT: {msg_dict.get("type","?")} — {msg_dict.get("summary","")[:80]}')


def send_signal(coin, action, price=None, summary=''):
    send({'type': 'signal', 'coin': coin, 'action': action, 'price': price, 'summary': summary})


def send_analysis(coin, summary, data=None):
    send({'type': 'analysis', 'coin': coin, 'summary': summary, 'data': data or {}})


def send_sl_update(coin, sl, tp=None):
    send({'type': 'sl_update', 'coin': coin, 'sl': sl, 'tp': tp})


def send_question(text):
    send({'type': 'question', 'text': text})


def send_alert(text):
    send({'type': 'alert', 'text': text})


def get_messages(last_n=10):
    return received_messages[-last_n:]


# CLI 모드
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Usage: python claude_bridge_client.py <worker_ip>')
        print('  예: python claude_bridge_client.py 172.17.0.50')
        sys.exit(1)

    host = sys.argv[1]
    connect(host)

    print('\nCommands:')
    print('  signal <coin> <BUY/SELL> [price] [summary]')
    print('  analysis <coin> <summary>')
    print('  sl <coin> <sl_price> [tp_price]')
    print('  q <question text>')
    print('  alert <text>')
    print('  msgs  — show recent messages')
    print('  quit')

    while True:
        try:
            line = input('> ').strip()
            if not line:
                continue
            parts = line.split(None, 3)
            cmd = parts[0].lower()

            if cmd == 'quit':
                break
            elif cmd == 'signal' and len(parts) >= 3:
                send_signal(parts[1], parts[2], float(parts[3]) if len(parts) > 3 else None)
            elif cmd == 'analysis' and len(parts) >= 3:
                send_analysis(parts[1], ' '.join(parts[2:]))
            elif cmd == 'sl' and len(parts) >= 3:
                send_sl_update(parts[1], float(parts[2]), float(parts[3]) if len(parts) > 3 else None)
            elif cmd == 'q':
                send_question(' '.join(parts[1:]))
            elif cmd == 'alert':
                send_alert(' '.join(parts[1:]))
            elif cmd == 'msgs':
                for m in get_messages():
                    print(f'  {m}')
            else:
                print(f'Unknown: {line}')
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f'Error: {e}')

    conn.close()
