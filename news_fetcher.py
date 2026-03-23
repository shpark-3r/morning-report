"""경제 신문 뉴스 수집 모듈 (한국경제, 매일경제)"""

import feedparser
import aiohttp
import asyncio
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from config import NEWS_FEEDS, NEWS_COUNT


async def fetch_rss(session: aiohttp.ClientSession, feed_name: str, feed_info: dict) -> list[dict]:
    """RSS 피드에서 뉴스 수집"""
    articles = []
    try:
        async with session.get(feed_info["rss_url"], timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                print(f"  ⚠ {feed_name} RSS 응답 오류: {resp.status}")
                return articles
            text = await resp.text()

        feed = feedparser.parse(text)
        for entry in feed.entries[:NEWS_COUNT]:
            published = ""
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6]).strftime("%Y-%m-%d %H:%M")
            elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                published = datetime(*entry.updated_parsed[:6]).strftime("%Y-%m-%d %H:%M")

            # 요약 텍스트 정리
            summary = ""
            if hasattr(entry, "summary"):
                soup = BeautifulSoup(entry.summary, "html.parser")
                summary = soup.get_text(strip=True)[:200]

            articles.append({
                "source": feed_name,
                "title": entry.title.strip(),
                "link": entry.link,
                "published": published,
                "summary": summary,
            })
    except Exception as e:
        print(f"  ⚠ {feed_name} 뉴스 수집 실패: {e}")

    return articles


async def fetch_all_news() -> dict[str, list[dict]]:
    """모든 신문사에서 뉴스 수집"""
    result = {}
    async with aiohttp.ClientSession(
        headers={"User-Agent": "MorningReport/1.0"}
    ) as session:
        tasks = {
            name: fetch_rss(session, name, info)
            for name, info in NEWS_FEEDS.items()
        }
        for name, task in tasks.items():
            result[name] = await task

    return result


def filter_market_news(all_news: dict[str, list[dict]]) -> list[dict]:
    """시장 관련 뉴스만 필터링 (키워드 기반)"""
    keywords = [
        "코스피", "코스닥", "증시", "주가", "주식", "환율", "금리",
        "미국", "나스닥", "S&P", "다우", "연준", "Fed", "GDP",
        "물가", "인플레", "금", "원유", "유가", "반도체", "AI",
        "삼성전자", "SK하이닉스", "투자", "외국인", "기관",
        "경기", "수출", "무역", "관세", "트럼프",
    ]
    filtered = []
    for source_articles in all_news.values():
        for article in source_articles:
            text = f"{article['title']} {article['summary']}".lower()
            if any(kw.lower() in text for kw in keywords):
                filtered.append(article)
    return filtered


if __name__ == "__main__":
    news = asyncio.run(fetch_all_news())
    for source, articles in news.items():
        print(f"\n📰 {source} ({len(articles)}건)")
        for a in articles:
            print(f"  - [{a['published']}] {a['title']}")
