"""YouTube 관련 영상 검색 모듈"""

import aiohttp
import asyncio
from urllib.parse import quote_plus, urlencode
from bs4 import BeautifulSoup
from datetime import datetime
import json
import re
from config import YOUTUBE_KEYWORDS


async def search_youtube(session: aiohttp.ClientSession, query: str, max_results: int = 3) -> list[dict]:
    """YouTube에서 관련 영상 검색 (웹 스크래핑 방식)"""
    videos = []
    search_query = f"{query} {datetime.now().strftime('%Y년 %m월')}"
    url = f"https://www.youtube.com/results?search_query={quote_plus(search_query)}"

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return videos
            html = await resp.text()

        # ytInitialData JSON에서 영상 정보 추출
        match = re.search(r"var ytInitialData = ({.*?});</script>", html)
        if not match:
            return videos

        data = json.loads(match.group(1))

        # 검색 결과에서 영상 추출
        contents = (
            data.get("contents", {})
            .get("twoColumnSearchResultsRenderer", {})
            .get("primaryContents", {})
            .get("sectionListRenderer", {})
            .get("contents", [])
        )

        for section in contents:
            items = section.get("itemSectionRenderer", {}).get("contents", [])
            for item in items:
                video = item.get("videoRenderer")
                if not video:
                    continue

                video_id = video.get("videoId", "")
                title = ""
                title_runs = video.get("title", {}).get("runs", [])
                if title_runs:
                    title = title_runs[0].get("text", "")

                channel = ""
                channel_runs = video.get("ownerText", {}).get("runs", [])
                if channel_runs:
                    channel = channel_runs[0].get("text", "")

                published = ""
                published_text = video.get("publishedTimeText", {})
                if published_text:
                    published = published_text.get("simpleText", "")

                view_count = ""
                view_text = video.get("viewCountText", {})
                if view_text:
                    view_count = view_text.get("simpleText", "")

                if video_id and title:
                    videos.append({
                        "title": title,
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "channel": channel,
                        "published": published,
                        "views": view_count,
                    })

                if len(videos) >= max_results:
                    break
            if len(videos) >= max_results:
                break

    except Exception as e:
        print(f"  ⚠ YouTube 검색 실패 ({query}): {e}")

    return videos


async def fetch_youtube_videos() -> list[dict]:
    """모든 키워드로 YouTube 영상 검색"""
    all_videos = []
    seen_urls = set()

    async with aiohttp.ClientSession(
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
        }
    ) as session:
        for keyword in YOUTUBE_KEYWORDS:
            videos = await search_youtube(session, keyword)
            for v in videos:
                if v["url"] not in seen_urls:
                    seen_urls.add(v["url"])
                    all_videos.append(v)

    return all_videos[:8]  # 최대 8개


def get_youtube_search_urls() -> list[dict]:
    """YouTube 검색 링크 직접 제공 (스크래핑 실패 시 대안)"""
    today = datetime.now().strftime("%Y년 %m월 %d일")
    search_queries = [
        f"오늘 증시 전망 {today}",
        f"코스피 분석 {today}",
        f"주식시장 브리핑 {today}",
    ]
    return [
        {
            "title": f"🔍 '{q}' 검색",
            "url": f"https://www.youtube.com/results?search_query={quote_plus(q)}",
        }
        for q in search_queries
    ]


if __name__ == "__main__":
    videos = asyncio.run(fetch_youtube_videos())
    if videos:
        for v in videos:
            print(f"  🎬 {v['title']} - {v['channel']}")
            print(f"     {v['url']}")
    else:
        print("스크래핑 실패, 검색 링크 제공:")
        for link in get_youtube_search_urls():
            print(f"  {link['title']}: {link['url']}")
