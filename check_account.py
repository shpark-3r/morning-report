"""빗썸 계좌 조회 (연구원 PC용, Q-27)

self-contained. 의존성: pyjwt만.

사용:
  1. 빗썸 API key 발급 (read-only 권한 충분)
  2. .bithumb_keys.json 생성 (template 참조)
  3. python check_account.py

출력:
  KRW 잔고 + 보유 코인 + 현재가 + pnl
"""
import hashlib
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlencode, unquote

try:
    import jwt
except ImportError:
    print("ERROR: 'pyjwt' required. Run: pip install pyjwt")
    sys.exit(1)

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE_URL = "https://api.bithumb.com/v1"
KEY_FILE = Path(__file__).parent / ".bithumb_keys.json"


def load_keys():
    if not KEY_FILE.exists():
        print(f"ERROR: {KEY_FILE} missing. Copy .bithumb_keys.json.template and fill in your keys.")
        sys.exit(1)
    with open(KEY_FILE, 'r') as f:
        d = json.load(f)
    if not d.get('access_key') or d['access_key'] == 'YOUR_ACCESS_KEY_HERE':
        print("ERROR: .bithumb_keys.json has placeholder values. Fill in your real keys.")
        sys.exit(1)
    return d['access_key'], d['secret_key']


def auth_header(access_key: str, secret_key: str, query: dict | None = None) -> dict:
    payload = {
        'access_key': access_key,
        'nonce': str(uuid.uuid4()),
        'timestamp': round(time.time() * 1000),
    }
    if query:
        query_string = unquote(urlencode(query, doseq=True))
        payload['query_hash'] = hashlib.sha512(query_string.encode()).hexdigest()
        payload['query_hash_alg'] = 'SHA512'
    token = jwt.encode(payload, secret_key, algorithm='HS256')
    return {'Authorization': f'Bearer {token}'}


def fetch(url: str, headers: dict | None = None) -> dict | list:
    req = urllib.request.Request(url, headers=headers or {'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def get_accounts(access_key: str, secret_key: str) -> list[dict]:
    """보유 계좌 전체. private endpoint — JWT 필요."""
    return fetch(f'{BASE_URL}/accounts', auth_header(access_key, secret_key))


def get_tickers(markets: list[str]) -> dict[str, float]:
    """공개 시세. key로 market code (KRW-BTC 형식), value로 현재가."""
    if not markets:
        return {}
    params = ','.join(markets)
    data = fetch(f'{BASE_URL}/ticker?markets={params}')
    return {row['market']: float(row['trade_price']) for row in data}


def get_krw_balance() -> float:
    """KRW 가용 잔고 return."""
    access_key, secret_key = load_keys()
    accts = get_accounts(access_key, secret_key)
    for a in accts:
        if a.get('currency') == 'KRW':
            return float(a.get('balance', 0) or 0)
    return 0.0


def get_positions() -> list[dict]:
    """보유 코인 list. 각 항목: coin, qty, avg_buy, current, pnl_pct, krw_value."""
    access_key, secret_key = load_keys()
    accts = get_accounts(access_key, secret_key)
    raw = []
    for a in accts:
        cur = a.get('currency')
        if cur in ('KRW', 'P'):
            continue
        bal = float(a.get('balance', 0) or 0)
        avg = float(a.get('avg_buy_price', 0) or 0)
        if bal > 0 and avg > 0 and bal * avg >= 100:
            raw.append({'coin': cur, 'qty': bal, 'avg_buy': avg})
    if not raw:
        return []
    price_map = get_tickers([f'KRW-{p["coin"]}' for p in raw])
    out = []
    for p in raw:
        current = price_map.get(f'KRW-{p["coin"]}', p['avg_buy'])
        pnl_pct = (current - p['avg_buy']) / p['avg_buy'] * 100 if p['avg_buy'] else 0
        out.append({
            **p,
            'current': current,
            'pnl_pct': pnl_pct,
            'krw_value': p['qty'] * current,
        })
    return out


def get_trade_history_placeholder():
    """
    최근 매매 이력은 빗썸 private endpoint /orders 필요.
    TODO: 필요 시 구현. 워커가 daily_results/*.json 쓰고 있으니 그걸 읽는 게 더 쉬울 수 있음.
    """
    raise NotImplementedError("Use worker's daily_results/*.json for trade history.")


def main():
    krw = get_krw_balance()
    positions = get_positions()
    print(f'KRW: {krw:,.0f}')
    total = krw
    if positions:
        print(f'Positions ({len(positions)}):')
        for p in positions:
            total += p['krw_value']
            print(f'  {p["coin"]:>6} {p["qty"]:>12.4f} qty @ {p["avg_buy"]:.4f} → '
                  f'{p["current"]:.4f} ({p["pnl_pct"]:+.2f}%, {p["krw_value"]:,.0f} KRW)')
    else:
        print('Positions: (none)')
    print(f'Total: {total:,.0f} KRW')


if __name__ == '__main__':
    main()
