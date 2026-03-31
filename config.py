"""아침 투자 리포트 설정"""

# 경제 신문 RSS 피드
NEWS_FEEDS = {
    "한국경제": {
        "name": "한국경제",
        "rss_url": "https://www.hankyung.com/feed/economy",
        "web_url": "https://www.hankyung.com/economy",
    },
    "매일경제": {
        "name": "매일경제",
        "rss_url": "https://www.mk.co.kr/rss/30100041/",
        "web_url": "https://www.mk.co.kr/economy/",
    },
}

# 수집할 뉴스 개수 (신문당)
NEWS_COUNT = 5

# KOSPI 관련 티커 (yfinance / TradingView 심볼)
TICKERS = {
    "KOSPI": "^KS11",
    "KOSDAQ": "^KQ11",
    "USD/KRW": "KRW=X",
    "S&P 500": "^GSPC",
    "NASDAQ": "^IXIC",
    "WTI 원유": "CL=F",
    "금": "GC=F",
    "비트코인": "BTC-KRW",
}

# TradingView 차트 심볼 매핑
TRADINGVIEW_SYMBOLS = {
    "KOSPI": "KRX:KOSPI",
    "KOSDAQ": "KRX:KOSDAQ",
    "USD/KRW": "FX_IDC:USDKRW",
    "S&P 500": "SP:SPX",
    "NASDAQ": "NASDAQ:NDX",
    "WTI 원유": "NYMEX:CL1!",
    "금": "COMEX:GC1!",
    "비트코인": "BITHUMB:BTCKRW",
}

# YouTube 검색 키워드
YOUTUBE_KEYWORDS = [
    "오늘 증시 전망",
    "코스피 분석",
    "주식 시장 브리핑",
]
