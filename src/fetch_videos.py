"""
fetch_videos.py
YouTube Data API v3 を使って日本語トレンド動画を最大200件取得し、
data/YYYY-MM-DD/raw_videos.json に保存する。
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


def get_published_after() -> str:
    """実行日から30日前のISO8601文字列を返す（UTC）"""
    dt = datetime.now(tz=timezone.utc) - timedelta(days=DAYS_BACK)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def search_videos(youtube, published_after: str) -> list[dict]:
    """
    検索APIで動画IDリストを収集する（最大200件、ページネーション対応）。
    クォータ節約のため search.list は必要最小限のフィールドのみ取得。
    """
    video_ids: list[str] = []
    next_page_token = None

    while len(video_ids) < MAX_RESULTS:
        remaining = MAX_RESULTS - len(video_ids)
        request_count = min(PAGE_SIZE, remaining)

        params = {
            "part": "id",
            "type": "video",
            "regionCode": REGION_CODE,
            "relevanceLanguage": RELEVANCE_LANGUAGE,
            "publishedAfter": published_after,
            "order": "viewCount",
            "maxResults": request_count,
        }
        if next_page_token:
            params["pageToken"] = next_page_token

        try:
            response = youtube.search().list(**params).execute()
        except HttpError as e:
            print(f"[ERROR] search.list failed: {e}", file=sys.stderr)
            break

        items = response.get("items", [])
        for item in items:
            vid = item.get("id", {}).get("videoId")
            if vid:
                video_ids.append(vid)

        next_page_token = response.get("nextPageToken")
        if not next_page_token:
            break

    return video_ids


def get_video_details(youtube, video_ids: list[str]) -> list[dict]:
    """
    videos.list で統計情報・スニペット・トピックを一括取得する。
    50件ずつバッチ処理してクォータを節約。
    """
    videos: list[dict] = []

    for i in range(0, len(video_ids), PAGE_SIZE):
        batch_ids = video_ids[i : i + PAGE_SIZE]
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
            print(f"[ERROR] videos.list failed: {e}", file=sys.stderr)
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
                    "channelId": snippet.get("channelId", ""),
                    "channelTitle": snippet.get("channelTitle", ""),
                    "viewCount": int(stats.get("viewCount", 0)),
                    "likeCount": int(stats.get("likeCount", 0)),
                    "commentCount": int(stats.get("commentCount", 0)),
                    "topicCategories": item.get("topicDetails", {}).get(
                        "topicCategories", []
                    ),
                }
            )

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
        batch = channel_ids[i : i + PAGE_SIZE]
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
    out_dir = Path("data") / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "raw_videos.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(videos, f, ensure_ascii=False, indent=2)
    print(f"[INFO] {len(videos)} videos saved to {out_path}")
    return out_path


def main():
    date_str = os.environ.get("RUN_DATE") or datetime.now(tz=JST).strftime("%Y-%m-%d")
    published_after = get_published_after()
    print(f"[INFO] date={date_str}, publishedAfter={published_after}")

    youtube = build_youtube_client()

    print("[INFO] Searching videos...")
    video_ids = search_videos(youtube, published_after)
    print(f"[INFO] Found {len(video_ids)} video IDs")

    if not video_ids:
        print("[WARN] No videos found. Exiting.")
        sys.exit(0)

    print("[INFO] Fetching video details...")
    videos = get_video_details(youtube, video_ids)

    print("[INFO] Fetching channel subscriber counts...")
    subscriber_map = get_channel_subscriber_counts(youtube, videos)
    for v in videos:
        v["subscriberCount"] = subscriber_map.get(v["channelId"], 0)

    save_raw_videos(videos, date_str)


if __name__ == "__main__":
    main()
