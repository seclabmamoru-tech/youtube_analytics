# YouTube トレンド分析システム

日本語 YouTube トレンド動画を定期取得し、Anthropic Claude API で分析して HTML レポートを自動生成するシステムです。

## 概要

- **取得条件**: regionCode=JP / relevanceLanguage=ja / 直近30日以内 / 最大200件
- **フィルタ**: `viewCount >= subscriberCount × 2`（バズ動画のみ）
- **分析**: Anthropic Claude API によるキーワードランキング・カテゴリ分布・トレンド変化・予測
- **レポート**: 日本語 HTML（Chart.js グラフ付き）
- **公開**: GitHub Pages（`docs/index.html` からリンク一覧）

## ディレクトリ構成

```
youtube-trend-analyzer/
├── .github/workflows/analyze.yml  # GitHub Actions ワークフロー
├── src/
│   ├── fetch_videos.py            # YouTube API からデータ取得
│   ├── filter_videos.py           # フィルタリング
│   └── analyze.py                 # Claude API 分析 + HTML レポート生成
├── data/
│   └── YYYY-MM-DD/
│       ├── raw_videos.json        # 取得生データ
│       └── filtered_videos.json   # フィルタ済みデータ
├── reports/
│   └── YYYY-MM-DD.html            # 日次レポート
├── docs/
│   └── index.html                 # GitHub Pages トップ（レポート一覧）
├── requirements.txt
└── README.md
```

## セットアップ

### 1. GitHub Secrets の設定

リポジトリの **Settings → Secrets and variables → Actions** に以下を登録:

| シークレット名       | 説明                          |
|---------------------|-------------------------------|
| `YOUTUBE_API_KEY`   | YouTube Data API v3 のキー    |
| `ANTHROPIC_API_KEY` | Anthropic Claude API のキー   |

### 2. GitHub Pages の有効化

**Settings → Pages → Source** を `Deploy from a branch` / ブランチ `main` / フォルダ `/ (root)` に設定。  
`docs/` フォルダが公開されます。

### 3. ローカル実行

```bash
pip install -r requirements.txt

export YOUTUBE_API_KEY=your_key
export ANTHROPIC_API_KEY=your_key

python src/fetch_videos.py
python src/filter_videos.py
python src/analyze.py
```

## GitHub Actions スケジュール

| タイミング          | cron              |
|--------------------|-------------------|
| 毎月 1日 JST 10:00 | `0 1 1,15 * *`    |
| 毎月 15日 JST 10:00| `0 1 1,15 * *`    |

手動実行: Actions タブ → **YouTube Trend Analysis** → **Run workflow**

## レポート内容

1. **頻出タグ・キーワードランキング TOP20** — タイトル・タグ・説明文から抽出
2. **カテゴリ別トレンド分布** — ドーナツグラフ＋詳細テーブル
3. **バズ係数上位動画の共通点** — `viewCount / subscriberCount` が高い動画の傾向
4. **トレンド変化比較** — 新登場 / 消滅 / 上昇 / 下降キーワードを矢印（↑↓→）で表示
5. **今後2週間の注目キーワード予測** — 確信度付き TOP10

## 技術スタック

- Python 3.11
- `google-api-python-client` — YouTube Data API v3
- `anthropic` — Claude API（`claude-opus-4-6`）
- Chart.js 4（CDN、HTMLレポート内）
- GitHub Actions + GitHub Pages
