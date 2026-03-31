"""KOSPI/KOSDAQ 및 주요 지수 데이터 수집 모듈

국내 지수: 네이버 금융 API (실시간)
환율/원자재: 네이버 시장지표 스크래핑
해외 지수/비트코인: yfinance (fallback)
"""

import requests
import yfinance as yf
from datetime import datetime
from bs4 import BeautifulSoup
from config import TICKERS

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _parse_number(s: str) -> float:
    """콤마/공백 제거 후 float 변환"""
    if not s:
        return 0.0
    return float(s.replace(",", "").replace(" ", "").strip())


def _fetch_naver_domestic(code: str) -> dict | None:
    """네이버 금융 API로 국내 지수(KOSPI/KOSDAQ) 실시간 조회"""
    try:
        url = f"https://m.stock.naver.com/api/index/{code}/basic"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        d = r.json()

        price = _parse_number(d.get("closePrice", ""))
        change = _parse_number(d.get("compareToPreviousClosePrice", ""))
        change_pct = float(d.get("fluctuationsRatio", 0))
        prev_close = price - change

        return {
            "price": price,
            "prev_close": prev_close,
            "change": change,
            "change_pct": change_pct,
            "high_5d": 0,
            "low_5d": 0,
            "volume": 0,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "source": "네이버(실시간)",
            "market_status": d.get("marketStatus", ""),
        }
    except Exception:
        return None


def _fetch_naver_marketindex() -> dict:
    """네이버 시장지표 페이지에서 환율/원자재 스크래핑"""
    result = {}
    try:
        url = "https://finance.naver.com/marketindex/"
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.encoding = "euc-kr"
        soup = BeautifulSoup(r.text, "html.parser")

        # 환율 (USD/KRW)
        for li in soup.select("#exchangeList li"):
            name_el = li.select_one("h3 .blind")
            val_el = li.select_one(".value")
            chg_el = li.select_one(".change")
            if not name_el or not val_el:
                continue
            name_text = name_el.text.strip()
            if "USD" in name_text:
                price = _parse_number(val_el.text)
                change = _parse_number(chg_el.text) if chg_el else 0
                # 방향 판단: up/down class
                is_down = bool(li.select_one(".ico.down, .head_info.minus"))
                if is_down:
                    change = -abs(change)
                prev = price - change
                change_pct = (change / prev * 100) if prev else 0
                result["USD/KRW"] = {
                    "price": price,
                    "prev_close": prev,
                    "change": change,
                    "change_pct": change_pct,
                    "high_5d": 0,
                    "low_5d": 0,
                    "volume": 0,
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "source": "네이버(실시간)",
                }

        # 원자재 (WTI, 금)
        for li in soup.select("#oilGoldList li"):
            name_el = li.select_one("h3 .blind")
            val_el = li.select_one(".value")
            chg_el = li.select_one(".change")
            if not name_el or not val_el:
                continue
            name_text = name_el.text.strip()
            price = _parse_number(val_el.text)
            change = _parse_number(chg_el.text) if chg_el else 0

            is_down = bool(li.select_one(".ico.down, .head_info.minus"))
            if is_down:
                change = -abs(change)
            prev = price - change
            change_pct = (change / prev * 100) if prev else 0

            entry = {
                "price": price,
                "prev_close": prev,
                "change": change,
                "change_pct": change_pct,
                "high_5d": 0,
                "low_5d": 0,
                "volume": 0,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "source": "네이버(실시간)",
            }

            if "WTI" in name_text:
                result["WTI 원유"] = entry
            elif "금" in name_text and "국제" in name_text:
                result["금"] = entry

    except Exception:
        pass
    return result


def _fetch_yfinance(name: str, ticker_symbol: str) -> dict | None:
    """yfinance fallback으로 데이터 조회"""
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info

        current_price = info.get("regularMarketPrice")
        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")

        if current_price and prev_close:
            change = current_price - prev_close
            change_pct = (change / prev_close) * 100
        elif info.get("regularMarketChange") is not None:
            change = info["regularMarketChange"]
            change_pct = info.get("regularMarketChangePercent", 0)
            current_price = current_price or (prev_close + change if prev_close else 0)
        else:
            return None

        # 5일 고/저
        hist = ticker.history(period="1mo")
        if not hist.empty:
            recent = hist.tail(5)
            high_5d = recent["High"].max()
            low_5d = recent["Low"].min()
        else:
            high_5d = current_price
            low_5d = current_price

        return {
            "price": current_price,
            "prev_close": prev_close,
            "change": change,
            "change_pct": change_pct,
            "high_5d": high_5d,
            "low_5d": low_5d,
            "volume": info.get("regularMarketVolume", 0),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "source": "Yahoo(15분 지연)",
        }
    except Exception as e:
        return None


def _fill_5d_range(results: dict):
    """네이버 데이터에 5일 고/저가 보충 (yfinance history 활용)"""
    naver_codes = {"KOSPI": "^KS11", "KOSDAQ": "^KQ11"}
    for name, yf_sym in naver_codes.items():
        if name in results and results[name].get("high_5d", 0) == 0:
            try:
                hist = yf.Ticker(yf_sym).history(period="1mo")
                if not hist.empty:
                    recent = hist.tail(5)
                    results[name]["high_5d"] = recent["High"].max()
                    results[name]["low_5d"] = recent["Low"].min()
            except Exception:
                pass


def fetch_market_data() -> dict[str, dict]:
    """주요 시장 지수 데이터 수집 (하이브리드)"""
    results = {}

    # 1. 국내 지수 - 네이버 실시간
    for name, naver_code in [("KOSPI", "KOSPI"), ("KOSDAQ", "KOSDAQ")]:
        data = _fetch_naver_domestic(naver_code)
        if data:
            results[name] = data
        else:
            # fallback to yfinance
            yf_data = _fetch_yfinance(name, TICKERS[name])
            results[name] = yf_data if yf_data else {"error": "데이터 없음"}

    # 2. 환율/원자재 - 네이버 시장지표
    naver_market = _fetch_naver_marketindex()
    for name in ["USD/KRW", "WTI 원유", "금"]:
        if name in naver_market:
            results[name] = naver_market[name]
        else:
            yf_data = _fetch_yfinance(name, TICKERS[name])
            results[name] = yf_data if yf_data else {"error": "데이터 없음"}

    # 3. 해외 지수 / 비트코인 - yfinance
    for name in ["S&P 500", "NASDAQ", "비트코인"]:
        yf_data = _fetch_yfinance(name, TICKERS[name])
        results[name] = yf_data if yf_data else {"error": "데이터 없음"}

    # 4. 국내 지수 5일 고/저 보충
    _fill_5d_range(results)

    return results


def get_kospi_analysis(market_data: dict) -> dict:
    """KOSPI 지수 간단 분석"""
    kospi = market_data.get("KOSPI", {})
    if "error" in kospi:
        return {"summary": "KOSPI 데이터를 가져올 수 없습니다."}

    change_pct = kospi["change_pct"]

    if change_pct >= 2:
        sentiment = "[강한 상승]"
        description = "시장이 강한 상승세를 보이고 있습니다."
    elif change_pct >= 0.5:
        sentiment = "[상승]"
        description = "시장이 소폭 상승했습니다."
    elif change_pct >= -0.5:
        sentiment = "[보합]"
        description = "시장이 보합세를 유지하고 있습니다."
    elif change_pct >= -2:
        sentiment = "[하락]"
        description = "시장이 하락세를 보이고 있습니다."
    else:
        sentiment = "[급락]"
        description = "시장이 급락했습니다. 주의가 필요합니다."

    # 미국 시장과의 상관관계 체크
    sp500 = market_data.get("S&P 500", {})
    nasdaq = market_data.get("NASDAQ", {})
    usd_krw = market_data.get("USD/KRW", {})

    factors = []
    if not sp500.get("error"):
        sp_chg = sp500.get("change_pct", 0)
        if abs(sp_chg) >= 1:
            direction = "상승" if sp_chg > 0 else "하락"
            factors.append(f"미국 S&P 500 {sp_chg:+.2f}% {direction}")

    if not nasdaq.get("error"):
        nq_chg = nasdaq.get("change_pct", 0)
        if abs(nq_chg) >= 1:
            direction = "상승" if nq_chg > 0 else "하락"
            factors.append(f"나스닥 {nq_chg:+.2f}% {direction}")

    if not usd_krw.get("error"):
        fx_chg = usd_krw.get("change_pct", 0)
        if abs(fx_chg) >= 0.5:
            direction = "원화 약세(달러 강세)" if fx_chg > 0 else "원화 강세(달러 약세)"
            factors.append(f"환율 {fx_chg:+.2f}% → {direction}")

    return {
        "sentiment": sentiment,
        "description": description,
        "change_pct": change_pct,
        "factors": factors,
    }


if __name__ == "__main__":
    data = fetch_market_data()
    for name, info in data.items():
        if "error" in info:
            print(f"{name}: {info['error']}")
        else:
            src = info.get("source", "")
            print(f"{name}: {info['price']:,.2f} ({info['change_pct']:+.2f}%) [{src}]")
