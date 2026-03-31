"""아침 투자 리포트 - Flask 웹 애플리케이션"""

import asyncio
from datetime import datetime
from flask import Flask, render_template, jsonify

from market_data import fetch_market_data, get_kospi_analysis
from news_fetcher import fetch_all_news, filter_market_news
from youtube_search import fetch_youtube_videos, get_youtube_search_urls
from config import TRADINGVIEW_SYMBOLS

app = Flask(__name__)


def collect_all_data() -> dict:
    """모든 데이터를 수집하여 딕셔너리로 반환"""
    # 시장 데이터
    market_data = fetch_market_data()
    analysis = get_kospi_analysis(market_data)

    # 뉴스 + YouTube (비동기)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        all_news, videos = loop.run_until_complete(
            asyncio.gather(fetch_all_news(), fetch_youtube_videos())
        )
    finally:
        loop.close()

    market_news = filter_market_news(all_news)
    youtube_fallback = get_youtube_search_urls() if not videos else []

    # 날짜 정보
    now = datetime.now()
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]

    return {
        "date_str": now.strftime(f"%Y년 %m월 %d일 ({weekdays[now.weekday()]}) %H:%M"),
        "market_data": market_data,
        "analysis": analysis,
        "all_news": all_news,
        "market_news": market_news[:5],
        "videos": videos,
        "youtube_fallback": youtube_fallback,
        "tv_symbols": TRADINGVIEW_SYMBOLS,
    }


@app.route("/")
def index():
    data = collect_all_data()
    return render_template("index.html", **data)


@app.route("/api/report")
def api_report():
    """JSON API 엔드포인트 (나중에 다른 앱에서 활용 가능)"""
    data = collect_all_data()
    return jsonify(data)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
