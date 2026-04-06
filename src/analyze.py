"""
analyze.py
filtered_videos.json を Anthropic Claude API で分析し、
日本語 HTML レポートを reports/YYYY-MM-DD.html に出力する。
また docs/index.html を更新してレポートへのリンク一覧を生成する。
"""

import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import anthropic

JST = timezone(timedelta(hours=9))

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
MODEL = "claude-opus-4-6"

# YouTube カテゴリID → 日本語名
CATEGORY_MAP = {
    "1": "映画・アニメ",
    "2": "自動車・乗り物",
    "10": "音楽",
    "15": "ペット・動物",
    "17": "スポーツ",
    "18": "ショートムービー",
    "19": "旅行・イベント",
    "20": "ゲーム",
    "21": "動画ブログ",
    "22": "People & Blogs",
    "23": "コメディ",
    "24": "エンタメ",
    "25": "ニュース・政治",
    "26": "ハウツー・スタイル",
    "27": "教育",
    "28": "科学・技術",
    "29": "非営利・社会活動",
}


# ─────────────────────────────────────────────
# データ読み込み
# ─────────────────────────────────────────────

def load_filtered_videos(date_str: str) -> list[dict]:
    path = Path("data") / date_str / "filtered_videos.json"
    if not path.exists():
        print(f"[ERROR] {path} not found.", file=sys.stderr)
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_previous_date(current_date_str: str) -> str | None:
    """data/ 以下で現在日付より前の最新ディレクトリを探す"""
    data_dir = Path("data")
    if not data_dir.exists():
        return None
    dates = sorted(
        [d.name for d in data_dir.iterdir() if d.is_dir() and d.name != current_date_str],
        reverse=True,
    )
    return dates[0] if dates else None


def load_previous_filtered_videos(prev_date_str: str) -> list[dict]:
    path = Path("data") / prev_date_str / "filtered_videos.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────
# ローカル集計
# ─────────────────────────────────────────────

def collect_tags(videos: list[dict]) -> Counter:
    counter: Counter = Counter()
    for v in videos:
        for tag in v.get("tags", []):
            if tag:
                counter[tag.lower()] += 1
    return counter


def collect_categories(videos: list[dict]) -> Counter:
    counter: Counter = Counter()
    for v in videos:
        cid = v.get("categoryId", "")
        name = CATEGORY_MAP.get(cid, f"カテゴリ{cid}")
        counter[name] += 1
    return counter


def top_buzz_videos(videos: list[dict], n: int = 10) -> list[dict]:
    return sorted(videos, key=lambda v: v.get("buzzScore", 0), reverse=True)[:n]


def build_stats_summary(videos: list[dict]) -> dict:
    """Claude に渡すコンパクトな統計サマリーを作る"""
    tag_counter = collect_tags(videos)
    cat_counter = collect_categories(videos)
    top_buzz = top_buzz_videos(videos, 20)

    return {
        "total_videos": len(videos),
        "top_tags": tag_counter.most_common(50),
        "category_distribution": cat_counter.most_common(),
        "top_buzz_videos": [
            {
                "title": v["title"],
                "channelTitle": v["channelTitle"],
                "viewCount": v["viewCount"],
                "subscriberCount": v["subscriberCount"],
                "buzzScore": v.get("buzzScore", 0),
                "tags": v.get("tags", [])[:10],
                "categoryId": v.get("categoryId", ""),
            }
            for v in top_buzz
        ],
    }


def build_prev_stats_summary(prev_videos: list[dict]) -> dict:
    tag_counter = collect_tags(prev_videos)
    return {
        "total_videos": len(prev_videos),
        "top_tags": tag_counter.most_common(50),
    }


# ─────────────────────────────────────────────
# Claude API 分析
# ─────────────────────────────────────────────

def analyze_with_claude(
    current_stats: dict,
    prev_stats: dict | None,
    date_str: str,
    prev_date_str: str | None,
    all_videos: list[dict],
) -> dict:
    """
    Claude に分析を依頼し、JSON 形式の結果を返す。
    all_videos はタイトル・説明文を含む全動画データ（網羅的分析用）。
    """
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # 全動画の簡易リスト（タイトル＋タグ＋カテゴリ）
    video_brief_list = [
        {
            "title": v["title"],
            "tags": v.get("tags", [])[:15],
            "categoryId": CATEGORY_MAP.get(v.get("categoryId", ""), v.get("categoryId", "")),
            "buzzScore": v.get("buzzScore", 0),
            "viewCount": v["viewCount"],
            "description_head": v.get("description", "")[:200],
        }
        for v in all_videos
    ]

    prev_section = ""
    if prev_stats and prev_date_str:
        prev_section = f"""
## 前回データ（{prev_date_str}）
- 動画数: {prev_stats['total_videos']}
- 上位タグ（TOP50）: {json.dumps(prev_stats['top_tags'], ensure_ascii=False)}
"""
    else:
        prev_section = "## 前回データ: なし（初回実行）"

    prompt = f"""あなたはYouTubeトレンド分析の専門家です。
以下の日本語YouTube動画データを網羅的に分析し、厳密にJSON形式のみで回答してください。
余分なテキストや説明は一切不要です。JSONオブジェクトのみを返してください。

## 分析対象日: {date_str}
## フィルタ済み動画数: {current_stats['total_videos']}

## カテゴリ別分布
{json.dumps(current_stats['category_distribution'], ensure_ascii=False)}

## 上位タグ（TOP50）
{json.dumps(current_stats['top_tags'], ensure_ascii=False)}

## バズ係数上位20動画
{json.dumps(current_stats['top_buzz_videos'], ensure_ascii=False)}

## 全動画リスト（タイトル・タグ・カテゴリ・説明冒頭）
{json.dumps(video_brief_list, ensure_ascii=False)}

{prev_section}

## 出力JSON形式（以下の構造を厳守）
{{
  "keyword_ranking": [
    {{"rank": 1, "keyword": "キーワード", "count": 数値, "trend": "↑/↓/→/NEW"}}
  ],
  "category_trends": [
    {{"category": "カテゴリ名", "count": 数値, "percentage": 数値, "insight": "コメント"}}
  ],
  "buzz_common_features": [
    "バズ動画の共通点1",
    "バズ動画の共通点2"
  ],
  "trend_changes": {{
    "new_keywords": ["新登場キーワード"],
    "disappeared_keywords": ["消えたキーワード"],
    "rising_keywords": [{{"keyword": "ワード", "change": "+XX%"}}],
    "declining_keywords": [{{"keyword": "ワード", "change": "-XX%"}}]
  }},
  "keyword_predictions": [
    {{"keyword": "予測キーワード", "reason": "理由", "confidence": "高/中/低"}}
  ],
  "overall_summary": "全体的なトレンドサマリー（200字程度）"
}}

## 分析要件
1. keyword_ranking: TOP20のキーワード（タグ・タイトル・説明文から抽出）
2. category_trends: 全カテゴリの分布と洞察
3. buzz_common_features: バズ係数上位動画の共通点を5〜8点
4. trend_changes: 前回比較（前回データなしの場合は全キーワードをNEWとし、trend_changesは空リスト）
5. keyword_predictions: 今後2週間で注目すべきキーワード TOP10（根拠付き）
6. 全動画データを網羅的に活用すること
"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    # JSONブロックの抽出
    if "```json" in raw:
        raw = raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        raw = raw.split("```")[1].split("```")[0].strip()

    return json.loads(raw)


# ─────────────────────────────────────────────
# HTML レポート生成
# ─────────────────────────────────────────────

TREND_COLOR = {"↑": "#22c55e", "↓": "#ef4444", "→": "#f59e0b", "NEW": "#8b5cf6"}


def _trend_badge(trend: str) -> str:
    color = TREND_COLOR.get(trend, "#6b7280")
    return f'<span class="badge" style="background:{color}">{trend}</span>'


def _escape(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generate_html_report(
    analysis: dict,
    current_stats: dict,
    date_str: str,
    prev_date_str: str | None,
) -> str:
    # ── Chart.js データ準備 ──────────────────────────────
    kw_top10 = analysis.get("keyword_ranking", [])[:10]
    kw_labels = json.dumps([k["keyword"] for k in kw_top10], ensure_ascii=False)
    kw_counts = json.dumps([k["count"] for k in kw_top10])

    cat_data = analysis.get("category_trends", [])
    cat_labels = json.dumps([c["category"] for c in cat_data], ensure_ascii=False)
    cat_counts = json.dumps([c["count"] for c in cat_data])

    buzz_top5 = current_stats.get("top_buzz_videos", [])[:5]
    buzz_labels = json.dumps([v["title"][:20] + "…" for v in buzz_top5], ensure_ascii=False)
    buzz_scores = json.dumps([v["buzzScore"] for v in buzz_top5])

    # ── キーワードランキングテーブル ─────────────────────
    kw_rows = ""
    for k in analysis.get("keyword_ranking", []):
        kw_rows += (
            f"<tr><td>{k['rank']}</td>"
            f"<td>{_escape(k['keyword'])}</td>"
            f"<td>{k['count']}</td>"
            f"<td>{_trend_badge(k.get('trend', '→'))}</td></tr>\n"
        )

    # ── カテゴリトレンドテーブル ─────────────────────────
    cat_rows = ""
    for c in analysis.get("category_trends", []):
        cat_rows += (
            f"<tr><td>{_escape(c['category'])}</td>"
            f"<td>{c['count']}</td>"
            f"<td>{c.get('percentage', 0):.1f}%</td>"
            f"<td>{_escape(c.get('insight', ''))}</td></tr>\n"
        )

    # ── バズ動画共通点 ────────────────────────────────────
    buzz_features_html = "".join(
        f"<li>{_escape(f)}</li>"
        for f in analysis.get("buzz_common_features", [])
    )

    # ── トレンド変化 ─────────────────────────────────────
    tc = analysis.get("trend_changes", {})
    new_kw_html = ", ".join(
        f'<span class="tag new">{_escape(k)}</span>'
        for k in tc.get("new_keywords", [])
    ) or "なし"
    gone_kw_html = ", ".join(
        f'<span class="tag gone">{_escape(k)}</span>'
        for k in tc.get("disappeared_keywords", [])
    ) or "なし"
    rising_rows = "".join(
        f"<tr><td>{_escape(r['keyword'])}</td><td class='up'>{_escape(r['change'])} ↑</td></tr>"
        for r in tc.get("rising_keywords", [])
    ) or "<tr><td colspan='2'>データなし</td></tr>"
    declining_rows = "".join(
        f"<tr><td>{_escape(r['keyword'])}</td><td class='down'>{_escape(r['change'])} ↓</td></tr>"
        for r in tc.get("declining_keywords", [])
    ) or "<tr><td colspan='2'>データなし</td></tr>"

    # ── 予測キーワード ────────────────────────────────────
    pred_rows = ""
    for p in analysis.get("keyword_predictions", []):
        conf = p.get("confidence", "")
        conf_color = {"高": "#22c55e", "中": "#f59e0b", "低": "#ef4444"}.get(conf, "#6b7280")
        pred_rows += (
            f"<tr><td>{_escape(p['keyword'])}</td>"
            f"<td>{_escape(p.get('reason', ''))}</td>"
            f"<td><span class='badge' style='background:{conf_color}'>{conf}</span></td></tr>\n"
        )

    prev_label = f"前回比較対象: {prev_date_str}" if prev_date_str else "初回実行（比較データなし）"

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>YouTube トレンドレポート {date_str}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg: #0f172a;
      --surface: #1e293b;
      --surface2: #334155;
      --text: #f1f5f9;
      --text2: #94a3b8;
      --accent: #38bdf8;
      --border: #475569;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: var(--bg); color: var(--text); font-family: "Helvetica Neue", Arial, sans-serif; padding: 2rem 1rem; }}
    .container {{ max-width: 1100px; margin: 0 auto; }}
    h1 {{ font-size: 2rem; color: var(--accent); margin-bottom: .25rem; }}
    .subtitle {{ color: var(--text2); margin-bottom: 2rem; font-size: .9rem; }}
    .summary-box {{ background: var(--surface); border-left: 4px solid var(--accent); padding: 1rem 1.5rem; border-radius: 8px; margin-bottom: 2rem; line-height: 1.7; }}
    .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }}
    @media(max-width:700px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}
    .card {{ background: var(--surface); border-radius: 12px; padding: 1.5rem; }}
    .card h2 {{ color: var(--accent); font-size: 1.1rem; margin-bottom: 1rem; border-bottom: 1px solid var(--border); padding-bottom: .5rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
    th {{ text-align: left; padding: .5rem .75rem; background: var(--surface2); color: var(--text2); font-size: .8rem; text-transform: uppercase; }}
    td {{ padding: .5rem .75rem; border-bottom: 1px solid var(--border); }}
    tr:last-child td {{ border-bottom: none; }}
    .badge {{ display: inline-block; padding: .15rem .5rem; border-radius: 999px; color: #fff; font-size: .75rem; font-weight: bold; }}
    .tag {{ display: inline-block; padding: .2rem .6rem; border-radius: 6px; margin: .15rem; font-size: .82rem; }}
    .tag.new {{ background: #4c1d95; color: #c4b5fd; }}
    .tag.gone {{ background: #7f1d1d; color: #fca5a5; }}
    .up {{ color: #22c55e; font-weight: bold; }}
    .down {{ color: #ef4444; font-weight: bold; }}
    .buzz-list {{ list-style: none; padding: 0; }}
    .buzz-list li {{ padding: .4rem 0; border-bottom: 1px solid var(--border); font-size: .9rem; line-height: 1.5; }}
    .buzz-list li::before {{ content: "✦ "; color: var(--accent); }}
    .chart-wrapper {{ position: relative; height: 280px; }}
    .section {{ margin-bottom: 2rem; }}
    .meta {{ color: var(--text2); font-size: .8rem; margin-top: 2rem; text-align: right; }}
  </style>
</head>
<body>
<div class="container">
  <h1>YouTube トレンドレポート</h1>
  <p class="subtitle">分析日: {date_str}　｜　{prev_label}　｜　分析動画数: {current_stats['total_videos']}件</p>

  <div class="summary-box">
    <strong>総括:</strong> {_escape(analysis.get('overall_summary', ''))}
  </div>

  <!-- キーワードランキング + カテゴリ分布 -->
  <div class="grid2">
    <div class="card">
      <h2>頻出タグ・キーワード TOP10（グラフ）</h2>
      <div class="chart-wrapper">
        <canvas id="kwChart"></canvas>
      </div>
    </div>
    <div class="card">
      <h2>カテゴリ別トレンド分布</h2>
      <div class="chart-wrapper">
        <canvas id="catChart"></canvas>
      </div>
    </div>
  </div>

  <!-- キーワードランキング表 -->
  <div class="card section">
    <h2>頻出タグ・キーワードランキング TOP20</h2>
    <table>
      <thead><tr><th>#</th><th>キーワード</th><th>件数</th><th>トレンド</th></tr></thead>
      <tbody>{kw_rows}</tbody>
    </table>
  </div>

  <!-- バズ係数上位グラフ + 共通点 -->
  <div class="grid2">
    <div class="card">
      <h2>バズ係数上位5動画</h2>
      <div class="chart-wrapper">
        <canvas id="buzzChart"></canvas>
      </div>
    </div>
    <div class="card">
      <h2>バズ動画の共通点</h2>
      <ul class="buzz-list">{buzz_features_html}</ul>
    </div>
  </div>

  <!-- トレンド変化 -->
  <div class="card section">
    <h2>トレンド変化（前回比較）</h2>
    <div class="grid2">
      <div>
        <p style="margin-bottom:.5rem;color:var(--text2);font-size:.85rem;">新登場キーワード</p>
        <div>{new_kw_html}</div>
        <p style="margin:.75rem 0 .5rem;color:var(--text2);font-size:.85rem;">消えたキーワード</p>
        <div>{gone_kw_html}</div>
      </div>
      <div class="grid2" style="gap:.75rem">
        <div>
          <table>
            <thead><tr><th>上昇ワード</th><th>変化</th></tr></thead>
            <tbody>{rising_rows}</tbody>
          </table>
        </div>
        <div>
          <table>
            <thead><tr><th>下降ワード</th><th>変化</th></tr></thead>
            <tbody>{declining_rows}</tbody>
          </table>
        </div>
      </div>
    </div>
  </div>

  <!-- カテゴリ詳細 -->
  <div class="card section">
    <h2>カテゴリ別詳細</h2>
    <table>
      <thead><tr><th>カテゴリ</th><th>件数</th><th>割合</th><th>分析コメント</th></tr></thead>
      <tbody>{cat_rows}</tbody>
    </table>
  </div>

  <!-- キーワード予測 -->
  <div class="card section">
    <h2>今後2週間の注目キーワード予測 TOP10</h2>
    <table>
      <thead><tr><th>キーワード</th><th>予測根拠</th><th>確信度</th></tr></thead>
      <tbody>{pred_rows}</tbody>
    </table>
  </div>

  <p class="meta">Generated by YouTube Trend Analyzer | {date_str}</p>
</div>

<script>
const chartDefaults = {{
  responsive: true,
  maintainAspectRatio: false,
  plugins: {{ legend: {{ labels: {{ color: '#94a3b8' }} }} }},
}};

// キーワードランキング棒グラフ
new Chart(document.getElementById('kwChart'), {{
  type: 'bar',
  data: {{
    labels: {kw_labels},
    datasets: [{{
      label: '件数',
      data: {kw_counts},
      backgroundColor: 'rgba(56,189,248,0.7)',
      borderColor: '#38bdf8',
      borderWidth: 1,
    }}]
  }},
  options: {{
    ...chartDefaults,
    indexAxis: 'y',
    scales: {{
      x: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }},
      y: {{ ticks: {{ color: '#f1f5f9', font: {{ size: 11 }} }}, grid: {{ color: '#334155' }} }}
    }}
  }}
}});

// カテゴリドーナツグラフ
new Chart(document.getElementById('catChart'), {{
  type: 'doughnut',
  data: {{
    labels: {cat_labels},
    datasets: [{{
      data: {cat_counts},
      backgroundColor: [
        '#38bdf8','#818cf8','#34d399','#fb923c','#f472b6',
        '#a78bfa','#facc15','#4ade80','#60a5fa','#f87171',
        '#2dd4bf','#e879f9','#fb7185','#a3e635','#fdba74',
      ],
    }}]
  }},
  options: {{
    ...chartDefaults,
    plugins: {{
      legend: {{ position: 'right', labels: {{ color: '#94a3b8', font: {{ size: 11 }} }} }}
    }}
  }}
}});

// バズ係数棒グラフ
new Chart(document.getElementById('buzzChart'), {{
  type: 'bar',
  data: {{
    labels: {buzz_labels},
    datasets: [{{
      label: 'バズ係数',
      data: {buzz_scores},
      backgroundColor: 'rgba(52,211,153,0.7)',
      borderColor: '#34d399',
      borderWidth: 1,
    }}]
  }},
  options: {{
    ...chartDefaults,
    scales: {{
      x: {{ ticks: {{ color: '#94a3b8', font: {{ size: 10 }} }}, grid: {{ color: '#334155' }} }},
      y: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#334155' }} }}
    }}
  }}
}});
</script>
</body>
</html>
"""
    return html


# ─────────────────────────────────────────────
# docs/index.html 生成
# ─────────────────────────────────────────────

def update_index_html(reports_dir: Path, docs_dir: Path) -> None:
    """reports/ 以下の全 HTML を走査して docs/index.html を更新する"""
    report_files = sorted(
        [f for f in reports_dir.glob("*.html") if f.name != "index.html"],
        reverse=True,
    )

    rows = ""
    for rf in report_files:
        date = rf.stem
        rows += (
            f'<tr><td><a href="../reports/{rf.name}">{date}</a></td>'
            f'<td><a href="../reports/{rf.name}" class="btn">レポートを開く</a></td></tr>\n'
        )

    if not rows:
        rows = '<tr><td colspan="2">レポートはまだありません。</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>YouTube トレンド分析 - レポート一覧</title>
  <style>
    :root {{
      --bg: #0f172a; --surface: #1e293b; --text: #f1f5f9;
      --text2: #94a3b8; --accent: #38bdf8; --border: #475569;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: var(--bg); color: var(--text); font-family: "Helvetica Neue", Arial, sans-serif;
            display: flex; flex-direction: column; align-items: center; padding: 3rem 1rem; min-height: 100vh; }}
    h1 {{ font-size: 2rem; color: var(--accent); margin-bottom: .5rem; }}
    p.sub {{ color: var(--text2); margin-bottom: 2rem; }}
    table {{ width: 100%; max-width: 700px; border-collapse: collapse; background: var(--surface); border-radius: 12px; overflow: hidden; }}
    th {{ padding: .75rem 1rem; background: #334155; color: var(--text2); text-align: left; font-size: .85rem; }}
    td {{ padding: .75rem 1rem; border-bottom: 1px solid var(--border); }}
    tr:last-child td {{ border-bottom: none; }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .btn {{ display: inline-block; padding: .3rem .9rem; background: var(--accent); color: #0f172a;
             border-radius: 6px; font-weight: bold; font-size: .85rem; }}
    .btn:hover {{ opacity: .85; text-decoration: none; }}
    footer {{ margin-top: 3rem; color: var(--text2); font-size: .8rem; }}
  </style>
</head>
<body>
  <h1>YouTube トレンド分析</h1>
  <p class="sub">日本語トレンド動画の定期分析レポート一覧</p>
  <table>
    <thead><tr><th>分析日</th><th>レポート</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <footer>Powered by YouTube Data API v3 + Anthropic Claude | GitHub Pages</footer>
</body>
</html>
"""
    docs_dir.mkdir(parents=True, exist_ok=True)
    out = docs_dir / "index.html"
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[INFO] docs/index.html updated ({len(report_files)} reports listed)")


# ─────────────────────────────────────────────
# メイン
# ─────────────────────────────────────────────

def main():
    date_str = datetime.now(tz=JST).strftime("%Y-%m-%d")
    print(f"[INFO] Analyzing data for {date_str}")

    # データ読み込み
    videos = load_filtered_videos(date_str)
    if not videos:
        print("[WARN] No filtered videos to analyze. Exiting.")
        sys.exit(0)

    prev_date_str = find_previous_date(date_str)
    prev_videos = load_previous_filtered_videos(prev_date_str) if prev_date_str else []
    print(f"[INFO] Previous date: {prev_date_str or 'none'} ({len(prev_videos)} videos)")

    # 統計サマリー構築
    current_stats = build_stats_summary(videos)
    prev_stats = build_prev_stats_summary(prev_videos) if prev_videos else None

    # Claude 分析
    print("[INFO] Calling Claude API...")
    analysis = analyze_with_claude(
        current_stats, prev_stats, date_str, prev_date_str, videos
    )

    # HTML レポート生成
    print("[INFO] Generating HTML report...")
    html = generate_html_report(analysis, current_stats, date_str, prev_date_str)

    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{date_str}.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[INFO] Report saved to {report_path}")

    # docs/index.html 更新
    update_index_html(reports_dir, Path("docs"))


if __name__ == "__main__":
    main()
