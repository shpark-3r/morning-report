"""
빗썸 매수/매도 실행기.
check_account.py의 인증 로직 재사용.

사용법:
  from trade_executor import buy_market, sell_market, get_balance
"""
import hashlib
import json
import time
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlencode, unquote

try:
    import jwt
except ImportError:
    raise ImportError("pyjwt required: pip install pyjwt")

BASE_URL = "https://api.bithumb.com/v1"
KEY_FILE = Path(__file__).parent / ".bithumb_keys.json"


def _load_keys():
    with open(KEY_FILE, 'r') as f:
        d = json.load(f)
    return d['access_key'], d['secret_key']


def _auth_header(access_key, secret_key, query=None):
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
    return {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}


def _post(endpoint, params):
    access_key, secret_key = _load_keys()
    headers = _auth_header(access_key, secret_key, params)
    url = f'{BASE_URL}{endpoint}'
    data = json.dumps(params).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _get(endpoint, params=None):
    access_key, secret_key = _load_keys()
    headers = _auth_header(access_key, secret_key, params)
    url = f'{BASE_URL}{endpoint}'
    if params:
        url += '?' + urlencode(params, doseq=True)
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def get_balance():
    """KRW 잔고 + 포지션 반환."""
    access_key, secret_key = _load_keys()
    headers = _auth_header(access_key, secret_key)
    req = urllib.request.Request(f'{BASE_URL}/accounts', headers=headers)
    with urllib.request.urlopen(req, timeout=5) as r:
        accts = json.loads(r.read())

    krw = 0
    positions = []
    for a in accts:
        cur = a.get('currency')
        if cur == 'KRW':
            krw = float(a.get('balance', 0) or 0)
        elif cur != 'P':
            bal = float(a.get('balance', 0) or 0)
            avg = float(a.get('avg_buy_price', 0) or 0)
            if bal > 0 and avg > 0 and bal * avg >= 100:
                positions.append({'coin': cur, 'qty': bal, 'avg_buy': avg})
    return krw, positions


def buy_market(coin, krw_amount):
    """시장가 매수. krw_amount 원어치 매수.

    Returns: order result dict or error string
    """
    params = {
        'market': f'KRW-{coin}',
        'side': 'bid',
        'ord_type': 'price',  # 시장가 매수
        'price': str(int(krw_amount)),
    }
    try:
        result = _post('/orders', params)
        return result
    except Exception as e:
        return {'error': str(e)}


def sell_market(coin, qty):
    """시장가 매도. qty만큼 매도.

    Returns: order result dict or error string
    """
    params = {
        'market': f'KRW-{coin}',
        'side': 'ask',
        'ord_type': 'market',  # 시장가 매도
        'volume': str(qty),
    }
    try:
        result = _post('/orders', params)
        return result
    except Exception as e:
        return {'error': str(e)}


def get_order_status(uuid_str):
    """주문 상태 확인."""
    params = {'uuid': uuid_str}
    try:
        return _get('/order', params)
    except Exception as e:
        return {'error': str(e)}


if __name__ == '__main__':
    # 테스트: 잔고 확인만
    krw, pos = get_balance()
    print(f'KRW: {krw:,.0f}')
    for p in pos:
        print(f'  {p["coin"]}: {p["qty"]:.4f} @ {p["avg_buy"]:.4f}')
