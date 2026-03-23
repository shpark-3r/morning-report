"""KOSPI/KOSDAQ 및 주요 지수 데이터 수집 모듈"""

import yfinance as yf
from datetime import datetime, timedelta
from config import TICKERS


def fetch_market_data() -> dict[str, dict]:
    """주요 시장 지수 데이터 수집"""
    results = {}

    for name, ticker_symbol in TICKERS.items():
        try:
            ticker = yf.Ticker(ticker_symbol)
            # 최근 5일 데이터
            hist = ticker.history(period="5d")

            if hist.empty or len(hist) < 1:
                results[name] = {"error": "데이터 없음"}
                continue

            latest = hist.iloc[-1]
            current_price = latest["Close"]

            # 전일 대비 변동
            if len(hist) >= 2:
                prev_price = hist.iloc[-2]["Close"]
                change = current_price - prev_price
                change_pct = (change / prev_price) * 100
            else:
                change = 0
                change_pct = 0

            # 5일 고/저
            high_5d = hist["High"].max()
            low_5d = hist["Low"].min()

            results[name] = {
                "price": current_price,
                "change": change,
                "change_pct": change_pct,
                "high_5d": high_5d,
                "low_5d": low_5d,
                "volume": latest.get("Volume", 0),
                "date": hist.index[-1].strftime("%Y-%m-%d"),
            }
        except Exception as e:
            results[name] = {"error": str(e)}

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
            print(f"{name}: {info['price']:,.2f} ({info['change_pct']:+.2f}%)")
