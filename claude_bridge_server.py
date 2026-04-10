"""
Claude Bridge — TCP 소켓 서버 (워커 PC에서 실행)
연구원 클로드와 직통 통신. git 대신 실시간 JSON 메시지.

사용법 (워커 PC):
  python claude_bridge_server.py

포트: 9999 (방화벽 허용 필요)
"""
import socket
import json
import sys
import threading
import time
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

KST = timezone(timedelta(hours=9))
PORT = 9999
clients = []
message_log = []


def handle_client(conn, addr):
    print(f'[{datetime.now(KST):%H:%M:%S}] Connected: {addr}')
    clients.append(conn)
    try:
        while True:
            data = conn.recv(65536)
            if not data:
                break
            msg = json.loads(data.decode('utf-8'))
            msg['_from'] = str(addr)
            msg['_ts'] = datetime.now(KST).isoformat()
            message_log.append(msg)
            print(f'[{datetime.now(KST):%H:%M:%S}] FROM {addr}: {msg.get("type","?")} — {msg.get("summary","")[:80]}')

            # 다른 클라이언트에 브로드캐스트
            for c in clients:
                if c != conn:
                    try:
                        c.sendall(json.dumps(msg).encode('utf-8') + b'\n')
                    except Exception:
                        pass

            # 자동 ACK
            ack = json.dumps({'type': 'ack', 'received': msg.get('type'), 'ts': datetime.now(KST).isoformat()})
            conn.sendall(ack.encode('utf-8') + b'\n')
    except Exception as e:
        print(f'[{datetime.now(KST):%H:%M:%S}] Disconnected {addr}: {e}')
    finally:
        clients.remove(conn)
        conn.close()


def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', PORT))
    server.listen(5)
    print(f'[{datetime.now(KST):%H:%M:%S}] Claude Bridge Server listening on port {PORT}')
    print(f'  연구원 PC에서: python claude_bridge_client.py <이 PC IP>')

    while True:
        conn, addr = server.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()


if __name__ == '__main__':
    start_server()
