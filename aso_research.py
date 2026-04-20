"""
YouTube ASO Research Tool
Bir konu/kelime için YouTube'da rekabet analizi ve aylık izlenme tahmini yapar.

Kullanım:
  python aso_research.py "anahtar kelime"
  python aso_research.py "anahtar kelime" --cookies-from-browser chrome
  python aso_research.py "anahtar kelime" --demo
"""

import sys
import time
import random
from datetime import datetime, timezone, timedelta
import urllib3
import yt_dlp
from pytrends.request import TrendReq

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()


def format_views(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)


YDL_BASE = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "nocheckcertificate": True,
}


def _make_ydl_opts(cookies_browser: str | None = None) -> dict:
    opts = {**YDL_BASE}
    if cookies_browser:
        opts["cookiesfrombrowser"] = (cookies_browser,)
    return opts


def search_youtube(keyword: str, max_results: int = 10, cookies_browser: str | None = None) -> list[dict]:
    """yt-dlp ile YouTube arama yapar, her video için metadata döner."""
    ydl_opts = {
        **_make_ydl_opts(cookies_browser),
        "extract_flat": True,
        "playlistend": max_results,
    }
    url = f"ytsearch{max_results}:{keyword}"
    videos = []
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(url, download=False)
        for entry in result.get("entries", []):
            if entry:
                videos.append(entry)
    return videos


def _demo_videos(keyword: str, count: int = 10) -> tuple[list[dict], dict[str, dict]]:
    """Gerçek ağ erişimi olmayan ortamlar için örnek veri üretir."""
    rng = random.Random(keyword)
    channels = [
        "TechTürk", "CodeAkademi", "PythonTR", "DevHocası",
        "YazılımOkulu", "KodlamaZamanı", "BilgisayarBilimi", "AlgoTürk",
        "ProgramlamaKlubu", "DigitalMentor",
    ]
    raw_videos = []
    details: dict[str, dict] = {}
    base_date = datetime(2023, 1, 1, tzinfo=timezone.utc)

    for i in range(count):
        vid_id = f"demo_{i:03d}"
        days_ago = rng.randint(30, 900)
        upload_dt = (datetime.now(tz=timezone.utc) - timedelta(days=days_ago))
        upload_date = upload_dt.strftime("%Y%m%d")
        view_count = rng.randint(5_000, 2_000_000)
        raw_videos.append({
            "id": vid_id,
            "title": f"{keyword.title()} {'Nasıl Yapılır' if i % 3 == 0 else 'Nedir' if i % 3 == 1 else 'Öğren'} — {i + 1}. Ders",
            "channel": channels[i % len(channels)],
            "uploader": channels[i % len(channels)],
        })
        details[vid_id] = {
            "view_count": view_count,
            "upload_date": upload_date,
            "like_count": int(view_count * rng.uniform(0.02, 0.08)),
            "comment_count": int(view_count * rng.uniform(0.003, 0.01)),
            "duration": rng.randint(300, 3600),
            "channel": channels[i % len(channels)],
            "subscriber_count": rng.randint(1_000, 500_000),
            "tags": [keyword, f"{keyword} dersleri", "programlama", "eğitim", "türkçe"][:rng.randint(2, 5)],
        }
    return raw_videos, details


def get_video_details(video_ids: list[str], cookies_browser: str | None = None) -> dict[str, dict]:
    """yt-dlp ile her video için tam metadata çeker."""
    ydl_opts = _make_ydl_opts(cookies_browser)
    details: dict[str, dict] = {}
    for vid_id in video_ids:
        url = f"https://www.youtube.com/watch?v={vid_id}"
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                details[vid_id] = {
                    "view_count": info.get("view_count") or 0,
                    "upload_date": info.get("upload_date"),
                    "like_count": info.get("like_count") or 0,
                    "comment_count": info.get("comment_count") or 0,
                    "duration": info.get("duration") or 0,
                    "channel": info.get("channel") or "",
                    "subscriber_count": info.get("channel_follower_count") or 0,
                    "tags": info.get("tags") or [],
                }
        except Exception as e:
            console.print(f"  [dim red]Detay alınamadı ({vid_id}): {e}[/dim red]")
            details[vid_id] = {"view_count": 0, "upload_date": None}
        time.sleep(0.5)
    return details


def calculate_monthly_views(view_count: int, upload_date_str: str | None) -> int:
    """Toplam görüntülemeyi geçen aylara bölerek aylık ortalama döner."""
    if not upload_date_str or view_count == 0:
        return 0
    try:
        upload = datetime.strptime(upload_date_str, "%Y%m%d").replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        months = max((now - upload).days / 30, 1)
        return int(view_count / months)
    except Exception:
        return 0


def get_trends_score(keyword: str) -> int | None:
    """Google Trends'den 0-100 arası ilgi skoru döner (TR, son 3 ay)."""
    try:
        pytrends = TrendReq(hl="tr-TR", tz=180, timeout=(10, 25), requests_args={"verify": False})
        pytrends.build_payload([keyword], cat=0, timeframe="today 3-m", geo="TR")
        data = pytrends.interest_over_time()
        if data.empty or keyword not in data.columns:
            return None
        return int(data[keyword].mean())
    except Exception:
        return None


def get_related_queries(keyword: str) -> list[str]:
    """Google Trends ile ilgili sorguları getirir."""
    try:
        pytrends = TrendReq(hl="tr-TR", tz=180, timeout=(10, 25), requests_args={"verify": False})
        pytrends.build_payload([keyword], cat=0, timeframe="today 3-m", geo="TR")
        related = pytrends.related_queries()
        top = related.get(keyword, {}).get("top")
        if top is not None and not top.empty:
            return top["query"].tolist()[:8]
    except Exception:
        pass
    return []


def calc_opportunity(avg_monthly: int, trend_score: int | None) -> int:
    """Basit fırsat skoru (0-100): izlenme + trend ağırlıklı."""
    if avg_monthly >= 100_000:
        view_score = 80
    elif avg_monthly >= 50_000:
        view_score = 65
    elif avg_monthly >= 20_000:
        view_score = 50
    elif avg_monthly >= 5_000:
        view_score = 35
    elif avg_monthly >= 1_000:
        view_score = 20
    else:
        view_score = 10

    t = trend_score if trend_score is not None else 30
    return min(100, int(view_score * 0.65 + t * 0.35))


def analyze_keyword(
    keyword: str,
    max_videos: int = 10,
    cookies_browser: str | None = None,
    demo: bool = False,
) -> None:
    mode_label = "[dim](demo modu)[/dim]" if demo else ""
    console.print(Panel(
        f"[bold cyan]YouTube ASO Analizi[/bold cyan] {mode_label}\nAnahtar kelime: [yellow]{keyword}[/yellow]",
        expand=False,
    ))

    if demo:
        console.print("\n[bold yellow]Demo modu — örnek verilerle çalışıyor.[/bold yellow]")
        raw_videos, details = _demo_videos(keyword, max_videos)
    else:
        # 1. YouTube'da arama
        console.print("\n[bold]YouTube'da arama yapılıyor...[/bold]")
        try:
            raw_videos = search_youtube(keyword, max_videos, cookies_browser)
        except Exception as e:
            console.print(f"[red]YouTube araması başarısız: {e}[/red]")
            console.print(
                "\n[yellow]İpucu:[/yellow] Tarayıcı cookie'si ile deneyin:\n"
                f"  python aso_research.py \"{keyword}\" --cookies-from-browser chrome\n"
                "Ya da demo modunda test edin:\n"
                f"  python aso_research.py \"{keyword}\" --demo"
            )
            return

        if not raw_videos:
            console.print("[red]Sonuç bulunamadı.[/red]")
            return

        video_ids = [v["id"] for v in raw_videos if v.get("id")]
        console.print(f"  [dim]{len(video_ids)} video bulundu.[/dim]")

        # 2. Her video için tam detay
        console.print("[bold]Detaylı metadata çekiliyor...[/bold]")
        details = get_video_details(video_ids, cookies_browser)

    # 3. Veri birleştir + aylık izlenme hesapla
    videos = []
    for raw in raw_videos:
        vid_id = raw.get("id")
        if not vid_id:
            continue
        det = details.get(vid_id, {})
        view_count = det.get("view_count") or raw.get("view_count") or 0
        upload_date = det.get("upload_date") or raw.get("upload_date")
        monthly = calculate_monthly_views(view_count, upload_date)
        videos.append({
            "id": vid_id,
            "title": raw.get("title", ""),
            "channel": det.get("channel") or raw.get("channel") or raw.get("uploader") or "",
            "view_count": view_count,
            "monthly_views": monthly,
            "upload_date": upload_date,
            "duration": det.get("duration", 0),
            "like_count": det.get("like_count", 0),
            "subscriber_count": det.get("subscriber_count", 0),
            "tags": det.get("tags", []),
        })

    # 4. İstatistikler
    top_videos = sorted(videos, key=lambda x: x["view_count"], reverse=True)
    avg_views = sum(v["view_count"] for v in videos) // len(videos)
    avg_monthly = sum(v["monthly_views"] for v in videos) // max(sum(1 for v in videos if v["monthly_views"] > 0), 1)
    top_video = top_videos[0] if top_videos else None

    # 5. Google Trends
    console.print("[bold]Google Trends verisi alınıyor...[/bold]")
    trend_score = get_trends_score(keyword)
    related_queries = get_related_queries(keyword)

    # 6. Fırsat skoru
    opportunity_score = calc_opportunity(avg_monthly, trend_score)

    # --- Video tablosu ---
    table = Table(
        title=f"Top {len(videos)} Video — \"{keyword}\"",
        box=box.ROUNDED,
        show_lines=True,
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("Başlık", style="white", max_width=42)
    table.add_column("Kanal", style="cyan", max_width=18)
    table.add_column("Toplam İzlenme", justify="right", style="green")
    table.add_column("Aylık İzlenme", justify="right", style="yellow")
    table.add_column("Yüklenme", justify="center", width=8)

    for i, v in enumerate(top_videos, 1):
        date_str = ""
        if v["upload_date"]:
            try:
                date_str = datetime.strptime(v["upload_date"], "%Y%m%d").strftime("%Y-%m")
            except Exception:
                pass
        table.add_row(
            str(i),
            v["title"][:42],
            v["channel"][:18],
            format_views(v["view_count"]),
            format_views(v["monthly_views"]) if v["monthly_views"] else "—",
            date_str,
        )

    console.print("\n", table)

    # --- Sık kullanılan tag'lar ---
    all_tags: dict[str, int] = {}
    for v in videos:
        for tag in v["tags"][:10]:
            all_tags[tag.lower()] = all_tags.get(tag.lower(), 0) + 1
    top_tags = sorted(all_tags.items(), key=lambda x: x[1], reverse=True)[:10]

    # --- Özet panel ---
    score_color = "green" if opportunity_score >= 60 else "yellow" if opportunity_score >= 35 else "red"
    verdict = (
        "[green]Video yapmaya DEGER[/green] — bu konuda ciddi trafik var."
        if opportunity_score >= 60
        else "[yellow]Orta fırsat[/yellow] — nişi daralt ya da farklı bir açıdan yaklaş."
        if opportunity_score >= 35
        else "[red]Düşük fırsat[/red] — trafik az veya rekabet çok yüksek."
    )
    trend_display = f"{trend_score}/100" if trend_score is not None else "veri alınamadı"

    summary_text = (
        f"[bold]Özet İstatistikler[/bold]\n\n"
        f"  Ortalama toplam izlenme   : [green]{format_views(avg_views)}[/green]\n"
        f"  Ortalama aylık izlenme    : [yellow]{format_views(avg_monthly)}[/yellow]\n"
        f"  En çok izlenen video      : [cyan]{format_views(top_video['view_count']) if top_video else '-'}[/cyan]\n"
        f"  Google Trends skoru (TR)  : [magenta]{trend_display}[/magenta]\n"
        f"  Fırsat skoru              : [{score_color}]{opportunity_score}/100[/{score_color}]\n\n"
        f"  Karar: {verdict}"
    )
    console.print(Panel(summary_text, title="[bold]Analiz Sonucu[/bold]", expand=False))

    if top_tags:
        console.print("\n[bold]Rakip videolarda sık geçen tag'lar:[/bold]")
        for tag, cnt in top_tags:
            console.print(f"  [{cnt}x] {tag}")

    if related_queries:
        console.print("\n[bold]Google Trends — ilgili aramalar:[/bold]")
        for q in related_queries:
            console.print(f"  • {q}")


if __name__ == "__main__":
    args = sys.argv[1:]
    demo_mode = "--demo" in args
    if demo_mode:
        args.remove("--demo")

    browser = None
    if "--cookies-from-browser" in args:
        idx = args.index("--cookies-from-browser")
        args.pop(idx)
        browser = args.pop(idx) if idx < len(args) else "chrome"

    keyword = " ".join(args) if args else "python programlama"
    analyze_keyword(keyword, cookies_browser=browser, demo=demo_mode)
