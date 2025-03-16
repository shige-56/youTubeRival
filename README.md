# YouTubeライバル分析ボット

YouTubeチャンネルの分析レポートを自動生成し、Discordに定期的に投稿するボットです。

## 機能

- チャンネル統計情報の取得と表示
  - 登録者数
  - 総再生回数
  - 総動画数

- 新着動画の分析（過去24時間）
  - タイトル
  - 再生数
  - 高評価数
  - コメント数

- 人気動画ランキング（過去1ヶ月）
  - TOP3の動画情報
  - 各動画の詳細統計

## セットアップ

1. 必要な環境変数を設定
```bash
DISCORD_TOKEN=your_discord_token
YOUTUBE_API_KEY=your_youtube_api_key
RIVAL_CHANNEL_ID=target_channel_id
```

2. 依存パッケージのインストール
```bash
pip install -r requirements.txt
```

3. プログラムの実行
```bash
python discordYoutube.py
```

## 定期実行

- 毎日午前9時と午後8時に自動でレポートを生成
- 起動時に即時レポートを生成

## 注意事項

- `.env`ファイルに環境変数を設定してください
- YouTube Data APIの利用制限に注意してください 