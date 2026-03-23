"""아침 투자 리포트 생성기

매일 아침 실행하면 다음을 종합한 리포트를 출력합니다:
  1. 주요 시장 지수 현황 (KOSPI, KOSDAQ, 미국지수, 환율, 원자재)
  2. KOSPI 분석 및 시장 심리
  3. 한국경제 / 매일경제 주요 경제 뉴스
  4. 관련 YouTube 영상

사용법:
  python report.py
"""

import asyncio
import sys
import io
import os
from datetime import datetime

# Windows UTF-8 출력 강제
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

from market_data import fetch_market_data, get_kospi_analysis
from news_fetcher import fetch_all_news, filter_market_news
from youtube_search import fetch_youtube_videos, get_youtube_search_urls


console = Console(force_terminal=True)


def render_header():
    """리포트 헤더"""
    now = datetime.now()
    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    weekday = weekdays[now.weekday()]
    date_str = now.strftime(f"%Y년 %m월 %d일 ({weekday}) %H:%M")

    console.print()
    console.print(
        Panel(
            f"[bold white]  아침 투자 리포트  [/]\n[dim]{date_str}[/]",
            style="bold blue",
            box=box.DOUBLE,
            expand=False,
            padding=(1, 4),
        )
    )
    console.print()


def render_market_table(market_data: dict):
    """시장 지수 테이블"""
    table = Table(
        title="[주요 시장 지표]",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("지표", style="bold", width=14)
    table.add_column("현재가", justify="right", width=14)
    table.add_column("등락", justify="right", width=12)
    table.add_column("등락률", justify="right", width=10)
    table.add_column("5일 고가", justify="right", width=14)
    table.add_column("5일 저가", justify="right", width=14)

    for name, info in market_data.items():
        if "error" in info:
            table.add_row(name, f"[dim]{info['error']}[/]", "-", "-", "-", "-")
            continue

        price = f"{info['price']:,.2f}"
        change = info["change"]
        change_pct = info["change_pct"]

        if change > 0:
            color = "red"
            arrow = "+"
        elif change < 0:
            color = "blue"
            arrow = "-"
        else:
            color = "white"
            arrow = " "

        change_str = f"[{color}]{arrow}{abs(change):,.2f}[/]"
        pct_str = f"[{color}]{change_pct:+.2f}%[/]"
        high_str = f"{info['high_5d']:,.2f}"
        low_str = f"{info['low_5d']:,.2f}"

        table.add_row(name, price, change_str, pct_str, high_str, low_str)

    console.print(table)
    console.print()


def render_analysis(analysis: dict):
    """KOSPI 분석 결과"""
    sentiment = analysis.get("sentiment", "")
    description = analysis.get("description", "")
    factors = analysis.get("factors", [])

    lines = [f"[bold]{sentiment}[/]  {description}"]
    if factors:
        lines.append("")
        lines.append("[bold]주요 요인:[/]")
        for f in factors:
            lines.append(f"  * {f}")

    console.print(Panel(
        "\n".join(lines),
        title="[KOSPI 시장 분석]",
        box=box.ROUNDED,
        style="yellow",
    ))
    console.print()


def render_news(all_news: dict):
    """뉴스 섹션"""
    for source, articles in all_news.items():
        if not articles:
            console.print(f"[dim]  {source}: 뉴스를 가져올 수 없습니다.[/]")
            continue

        console.print(f"[bold cyan][{source}][/] ({len(articles)}건)")
        console.print()
        for i, article in enumerate(articles, 1):
            time_str = f"[dim]{article['published']}[/]" if article["published"] else ""
            console.print(f"  {i}. [bold]{article['title']}[/]  {time_str}")
            if article["summary"]:
                console.print(f"     [dim]{article['summary'][:120]}...[/]")
            console.print(f"     {article['link']}")
            console.print()

    # 시장 관련 핵심 뉴스
    market_news = filter_market_news(all_news)
    if market_news:
        console.print(f"[bold yellow][시장 핵심 뉴스 - 키워드 필터][/]")
        console.print()
        for i, article in enumerate(market_news[:5], 1):
            console.print(f"  {i}. [{article['source']}] [bold]{article['title']}[/]")
            console.print(f"     {article['link']}")
        console.print()


def render_youtube(videos: list[dict]):
    """YouTube 영상 섹션"""
    console.print("[bold cyan][관련 YouTube 영상][/]")
    console.print()

    if videos:
        for i, v in enumerate(videos, 1):
            channel = f" - {v['channel']}" if v.get("channel") else ""
            published = f" ({v['published']})" if v.get("published") else ""
            console.print(f"  {i}. [bold]{v['title']}[/]{channel}{published}")
            console.print(f"     {v['url']}")
        console.print()
    else:
        console.print("  [dim]영상을 직접 검색할 수 없어 검색 링크를 제공합니다:[/]")
        console.print()
        for link in get_youtube_search_urls():
            console.print(f"  {link['title']}")
            console.print(f"     {link['url']}")
        console.print()


def render_footer():
    """리포트 푸터"""
    console.print(
        Panel(
            "[dim]본 리포트는 자동 수집된 데이터 기반이며 투자 조언이 아닙니다.\n"
            "투자 판단은 본인의 책임하에 이루어져야 합니다.[/]",
            style="dim",
            box=box.SIMPLE,
        )
    )


async def generate_report():
    """전체 리포트 생성"""
    render_header()

    # 1. 시장 데이터 (동기)
    console.print("[dim]시장 데이터 수집 중...[/]")
    market_data = fetch_market_data()
    render_market_table(market_data)

    # 2. KOSPI 분석
    analysis = get_kospi_analysis(market_data)
    render_analysis(analysis)

    # 3. 뉴스 + YouTube 병렬 수집
    console.print("[dim]뉴스 및 YouTube 데이터 수집 중...[/]")
    news_task = fetch_all_news()
    yt_task = fetch_youtube_videos()
    all_news, videos = await asyncio.gather(news_task, yt_task)

    # 4. 뉴스 출력
    render_news(all_news)

    # 5. YouTube 출력
    render_youtube(videos)

    # 6. 푸터
    render_footer()


def main():
    asyncio.run(generate_report())


if __name__ == "__main__":
    main()
