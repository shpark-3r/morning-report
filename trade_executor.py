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


def buy_limit(coin, price, volume):
    """지정가 매수.

    Args:
        coin: 코인 심볼 (예: 'NOM')
        price: 매수 희망가
        volume: 매수 수량
    Returns: order result dict
    """
    params = {
        'market': f'KRW-{coin}',
        'side': 'bid',
        'ord_type': 'limit',
        'price': str(price),
        'volume': str(volume),
    }
    try:
        result = _post('/orders', params)
        return result
    except Exception as e:
        return {'error': str(e)}


def cancel_order(uuid_str):
    """주문 취소."""
    try:
        access_key, secret_key = _load_keys()
        params = {'uuid': uuid_str}
        headers = _auth_header(access_key, secret_key, params)
        url = f'{BASE_URL}/order?{urlencode(params)}'
        req = urllib.request.Request(url, headers=headers, method='DELETE')
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
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


def smart_buy(coin, krw_amount, timeout_sec=60):
    """지정가 매수 시도 -> 미체결 시 시장가 전환.

    1. 현재가로 지정가 매수
    2. timeout_sec 대기
    3. 미체결이면 취소 후 시장가 매수
    """
    import urllib.request as ur
    # 현재가 조회
    url = f'https://api.bithumb.com/v1/ticker?markets=KRW-{coin}'
    req = ur.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with ur.urlopen(req, timeout=5) as r:
        ticker = json.loads(r.read())
    current_price = ticker[0]['trade_price']

    # 수량 계산
    volume = krw_amount / current_price
    volume_str = f'{volume:.8f}'

    # 지정가 매수
    result = buy_limit(coin, current_price, volume_str)
    if 'error' in result:
        return buy_market(coin, krw_amount)  # 실패 시 시장가

    order_uuid = result.get('uuid')
    if not order_uuid:
        return buy_market(coin, krw_amount)

    # 대기
    waited = 0
    while waited < timeout_sec:
        time.sleep(5)
        waited += 5
        status = get_order_status(order_uuid)
        if status.get('state') == 'done':
            return status  # 체결 완료
        if status.get('state') == 'cancel':
            return buy_market(coin, krw_amount)  # 취소됨

    # 타임아웃 - 미체결분 취소 후 시장가
    status = get_order_status(order_uuid)
    if status.get('state') != 'done':
        cancel_order(order_uuid)
        time.sleep(1)
        remaining = float(status.get('remaining_volume', 0))
        if remaining > 0:
            remaining_krw = remaining * current_price
            if remaining_krw >= 5000:
                return buy_market(coin, int(remaining_krw))
    return status


if __name__ == '__main__':
    krw, pos = get_balance()
    print(f'KRW: {krw:,.0f}')
    for p in pos:
        print(f'  {p["coin"]}: {p["qty"]:.4f} @ {p["avg_buy"]:.4f}')
