"""
filter_videos.py
raw_videos.json を読み込み、フィルタ条件を適用して
data/YYYY-MM-DD/filtered_videos.json に保存する。

フィルタ条件: viewCount >= subscriberCount × 2
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))


def load_raw_videos(date_str: str) -> list[dict]:
    path = Path("data") / date_str / "raw_videos.json"
    if not path.exists():
        print(f"[ERROR] {path} not found.", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def filter_videos(videos: list[dict]) -> list[dict]:
    """
    viewCount >= subscriberCount × 2 を満たす動画のみ残す。
    登録者数が 0（非公開 or 取得失敗）の場合は除外する。
    """
    filtered = []
    for v in videos:
        sub = v.get("subscriberCount", 0)
        views = v.get("viewCount", 0)
        if sub > 0 and views >= sub * 2:
            # バズ係数を計算して付与
            v["buzzScore"] = round(views / sub, 4)
            filtered.append(v)
    return filtered


def save_filtered_videos(videos: list[dict], date_str: str) -> Path:
    out_dir = Path("data") / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "filtered_videos.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(videos, f, ensure_ascii=False, indent=2)
    print(f"[INFO] {len(videos)} filtered videos saved to {out_path}")
    return out_path


def main():
    date_str = os.environ.get("RUN_DATE") or datetime.now(tz=JST).strftime("%Y-%m-%d")

    print(f"[INFO] date={date_str}")
    raw_videos = load_raw_videos(date_str)
    print(f"[INFO] raw videos: {len(raw_videos)}")

    filtered = filter_videos(raw_videos)
    print(f"[INFO] filtered videos: {len(filtered)}")

    if not filtered:
        print("[WARN] No videos passed the filter. Saving empty list.")

    save_filtered_videos(filtered, date_str)


if __name__ == "__main__":
    main()
