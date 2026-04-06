"""
fetch_videos.py
YouTube Data API v3 を使って日本語トレンド動画を最大200件取得し、
data/YYYY-MM-DD/raw_videos.json に保存する。

取得方針:
  1. videos.list (chart=mostPopular, regionCode=JP) — 日本の人気動画を直接取得
     クォータ: 1ユニット/リクエスト（search.list の 100分の1）
  2. 取得後に publishedAt で直近 DAYS_BACK 日以内にフィルタ
  3. 不足分を search.list (order=date, relevanceLanguage=ja) で補完
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ─────────────────────────────────────────────
# 設定
# ─────────────────────────────────────────────
YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
MAX_RESULTS = 200          # 最大取得件数
PAGE_SIZE = 50             # 1リクエストあたりの件数（API上限）
REGION_CODE = "JP"
RELEVANCE_LANGUAGE = "ja"
DAYS_BACK = 30             # 何日前まで遡るか

JST = timezone(timedelta(hours=9))


def build_youtube_client():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)


def get_cutoff_dt() -> datetime:
    """直近 DAYS_BACK 日の cutoff datetime（UTC aware）を返す"""
    return datetime.now(tz=timezone.utc) - timedelta(days=DAYS_BACK)


def fetch_most_popular(youtube, cutoff_dt: datetime) -> list[dict]:
    """
    videos.list の chart=mostPopular で日本の人気動画を取得し、
    cutoff_dt 以降に投稿されたものだけ返す。
    クォータ: 1ユニット/リクエスト。
    """
    videos: list[dict] = []
    next_page_token = None
    fetched_total = 0

    # mostPopular は最大 200件程度しか返らないので全ページ取得する
    while fetched_total < MAX_RESULTS:
        params: dict = {
            "part": "snippet,statistics,topicDetails",
            "chart": "mostPopular",
            "regionCode": REGION_CODE,
            "hl": RELEVANCE_LANGUAGE,
            "maxResults": PAGE_SIZE,
        }
        if next_page_token:
            params["pageToken"] = next_page_token

        try:
            response = youtube.videos().list(**params).execute()
        except HttpError as e:
            print(f"[ERROR] videos.list(chart=mostPopular) failed: {e}", file=sys.stderr)
            break

        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            published_at_str = snippet.get("publishedAt", "")
            try:
                published_dt = datetime.fromisoformat(
                    published_at_str.replace("Z", "+00:00")
                )
            except ValueError:
                published_dt = None

            stats = item.get("statistics", {})
            videos.append(
                {
                    "videoId": item["id"],
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "tags": snippet.get("tags", []),
                    "categoryId": snippet.get("categoryId", ""),
                    "publishedAt": published_at_str,
                    "publishedDt": published_dt,
                    "channelId": snippet.get("channelId", ""),
                    "channelTitle": snippet.get("channelTitle", ""),
                    "viewCount": int(stats.get("viewCount", 0)),
                    "likeCount": int(stats.get("likeCount", 0)),
                    "commentCount": int(stats.get("commentCount", 0)),
                    "topicCategories": item.get("topicDetails", {}).get(
                        "topicCategories", []
                    ),
                    "source": "mostPopular",
                }
            )
            fetched_total += 1

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    print(f"[INFO] mostPopular: fetched {len(videos)} total, "
          f"filtering to last {DAYS_BACK} days...")

    # 日付フィルタ（cutoff_dt 以降のみ）
    recent = [
        v for v in videos
        if v["publishedDt"] is not None and v["publishedDt"] >= cutoff_dt
    ]
    print(f"[INFO] mostPopular after date filter: {len(recent)}")
    return recent


def fetch_recent_search(
    youtube,
    published_after_str: str,
    exclude_ids: set[str],
    need: int,
) -> list[dict]:
    """
    search.list (order=date) で直近の動画を補完取得する。
    mostPopular で取得済みの動画はスキップ。
    クォータ: 100ユニット/リクエスト なので最小限に抑える。
    """
    if need <= 0:
        return []

    video_ids: list[str] = []
    next_page_token = None

    while len(video_ids) < need:
        remaining = need - len(video_ids)
        params: dict = {
            "part": "id",
            "type": "video",
            "regionCode": REGION_CODE,
            "relevanceLanguage": RELEVANCE_LANGUAGE,
            "publishedAfter": published_after_str,
            "order": "date",
            "maxResults": min(PAGE_SIZE, remaining + 10),  # 除外分を見越して多めに
        }
        if next_page_token:
            params["pageToken"] = next_page_token

        try:
            response = youtube.search().list(**params).execute()
        except HttpError as e:
            print(f"[ERROR] search.list failed: {e}", file=sys.stderr)
            break

        for item in response.get("items", []):
            vid = item.get("id", {}).get("videoId")
            if vid and vid not in exclude_ids:
                video_ids.append(vid)
                if len(video_ids) >= need:
                    break

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    if not video_ids:
        return []

    # 詳細情報を取得
    videos: list[dict] = []
    for i in range(0, len(video_ids), PAGE_SIZE):
        batch_ids = video_ids[i: i + PAGE_SIZE]
        try:
            response = (
                youtube.videos()
                .list(
                    part="snippet,statistics,topicDetails",
                    id=",".join(batch_ids),
                )
                .execute()
            )
        except HttpError as e:
            print(f"[ERROR] videos.list(id=...) failed: {e}", file=sys.stderr)
            continue

        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            videos.append(
                {
                    "videoId": item["id"],
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "tags": snippet.get("tags", []),
                    "categoryId": snippet.get("categoryId", ""),
                    "publishedAt": snippet.get("publishedAt", ""),
                    "publishedDt": None,
                    "channelId": snippet.get("channelId", ""),
                    "channelTitle": snippet.get("channelTitle", ""),
                    "viewCount": int(stats.get("viewCount", 0)),
                    "likeCount": int(stats.get("likeCount", 0)),
                    "commentCount": int(stats.get("commentCount", 0)),
                    "topicCategories": item.get("topicDetails", {}).get(
                        "topicCategories", []
                    ),
                    "source": "search",
                }
            )

    print(f"[INFO] search補完: {len(videos)} videos")
    return videos


def get_channel_subscriber_counts(
    youtube, videos: list[dict]
) -> dict[str, int]:
    """
    channels.list でチャンネル登録者数を一括取得。
    重複チャンネルを排除してクォータを節約。
    """
    channel_ids = list({v["channelId"] for v in videos if v["channelId"]})
    subscriber_map: dict[str, int] = {}

    for i in range(0, len(channel_ids), PAGE_SIZE):
        batch = channel_ids[i: i + PAGE_SIZE]
        try:
            response = (
                youtube.channels()
                .list(
                    part="statistics",
                    id=",".join(batch),
                )
                .execute()
            )
        except HttpError as e:
            print(f"[ERROR] channels.list failed: {e}", file=sys.stderr)
            continue

        for item in response.get("items", []):
            cid = item["id"]
            count = int(
                item.get("statistics", {}).get("subscriberCount", 0)
            )
            subscriber_map[cid] = count

    return subscriber_map


def save_raw_videos(videos: list[dict], date_str: str) -> Path:
    # publishedDt は JSON 非対応のため保存前に除去
    clean = [{k: v for k, v in video.items() if k != "publishedDt"} for video in videos]
    out_dir = Path("data") / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "raw_videos.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    print(f"[INFO] {len(clean)} videos saved to {out_path}")
    return out_path


def main():
    date_str = os.environ.get("RUN_DATE") or datetime.now(tz=JST).strftime("%Y-%m-%d")
    cutoff_dt = get_cutoff_dt()
    published_after_str = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[INFO] date={date_str}, publishedAfter={published_after_str}")

    youtube = build_youtube_client()

    # Step 1: mostPopular で日本の人気動画を取得
    print("[INFO] Fetching mostPopular videos (chart=mostPopular, regionCode=JP)...")
    popular_videos = fetch_most_popular(youtube, cutoff_dt)

    # Step 2: 不足分を search.list で補完
    need = MAX_RESULTS - len(popular_videos)
    all_videos = popular_videos
    if need > 0:
        print(f"[INFO] Supplementing with search.list (need {need} more)...")
        existing_ids = {v["videoId"] for v in popular_videos}
        search_videos = fetch_recent_search(
            youtube, published_after_str, existing_ids, need
        )
        all_videos = popular_videos + search_videos

    print(f"[INFO] Total videos collected: {len(all_videos)}")

    if not all_videos:
        print("[WARN] No videos fetched. Saving empty list.", file=sys.stderr)
        save_raw_videos([], date_str)
        sys.exit(0)

    # Step 3: チャンネル登録者数を一括取得
    print("[INFO] Fetching channel subscriber counts...")
    subscriber_map = get_channel_subscriber_counts(youtube, all_videos)
    for v in all_videos:
        v["subscriberCount"] = subscriber_map.get(v["channelId"], 0)

    save_raw_videos(all_videos, date_str)


if __name__ == "__main__":
    main()
