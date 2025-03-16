import discord
import os
import googleapiclient.discovery
import schedule
import time
import ssl
import certifi
import aiohttp
import asyncio
import sqlite3
import json
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv
import cv2
import numpy as np
from PIL import Image
import requests
import io
from collections import Counter
import traceback

# .envファイルから環境変数を読み込む
load_dotenv()

# 非同期イベントループの作成
try:
    loop = asyncio.get_running_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

# SSL 証明書の設定
ssl_context = ssl.create_default_context(cafile=certifi.where())

# クライアントの作成を修正
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.presences = True
client = discord.Client(intents=intents)

TOKEN = os.getenv('DISCORD_TOKEN')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
RIVAL_CHANNEL_ID = os.getenv('RIVAL_CHANNEL_ID')
LAST_VIDEO_ID = None  # 直近の動画IDを保存

# データベースの初期化
def init_db():
    conn = sqlite3.connect('youtube_stats.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS channel_stats (
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            subscribers INTEGER,
            views INTEGER,
            videos INTEGER
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS video_stats (
            video_id TEXT PRIMARY KEY,
            title TEXT,
            published_at DATETIME,
            views INTEGER,
            likes INTEGER,
            comments INTEGER,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS channel_info (
            channel_id TEXT PRIMARY KEY,
            channel_name TEXT,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS top_videos_cache (
            last_updated DATETIME,
            video_data TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS top_videos_history (
            video_id TEXT,
            rank INTEGER,
            views INTEGER,
            likes INTEGER,
            comments INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (video_id, timestamp)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS video_performance_metrics (
            video_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            views INTEGER,
            likes INTEGER,
            comments INTEGER,
            engagement_rate REAL,
            views_per_hour REAL,
            PRIMARY KEY (video_id, timestamp)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS content_analysis (
            video_id TEXT PRIMARY KEY,
            title_keywords TEXT,
            video_length INTEGER,
            upload_hour INTEGER,
            day_of_week INTEGER,
            category_id TEXT,
            performance_score REAL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS historical_trends (
            date DATE,
            avg_views INTEGER,
            avg_likes INTEGER,
            avg_comments INTEGER,
            total_videos INTEGER,
            growth_rate REAL,
            PRIMARY KEY (date)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS thumbnail_analysis (
            video_id TEXT PRIMARY KEY,
            analyzed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            dominant_colors TEXT,  -- JSON形式で色情報を保存
            text_placement TEXT,   -- テキスト配置位置
            composition_score REAL,
            impact_score REAL,
            template_type TEXT,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS title_analysis (
            video_id TEXT PRIMARY KEY,
            analyzed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            keywords TEXT,         -- JSON形式でキーワードリストを保存
            keyword_scores TEXT,   -- JSON形式でキーワードごとのスコアを保存
            pattern_type TEXT,     -- タイトルパターンの分類
            effectiveness_score REAL,
            last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS keyword_performance (
            keyword TEXT,
            month_year TEXT,
            use_count INTEGER,
            avg_views REAL,
            avg_engagement REAL,
            PRIMARY KEY (keyword, month_year)
        )
    ''')
    conn.commit()
    conn.close()

# 統計情報の保存
def save_stats(stats):
    conn = sqlite3.connect('youtube_stats.db')
    c = conn.cursor()
    
    # チャンネル統計を保存
    c.execute('''
        INSERT INTO channel_stats (subscribers, views, videos)
        VALUES (?, ?, ?)
    ''', (stats['subscribers'], stats['views'], stats['videos']))
    
    # 動画統計を保存/更新
    c.execute('''
        INSERT OR REPLACE INTO video_stats 
        (video_id, title, published_at, views, likes, comments, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
    ''', (
        stats['latest_video_id'],
        stats['latest_video_title'],
        stats['latest_video_published_at'],
        stats['latest_video_views'],
        stats['latest_video_likes'],
        stats['latest_video_comments']
    ))
    
    conn.commit()
    conn.close()

# 統計の変化を取得
def get_stats_changes():
    conn = sqlite3.connect('youtube_stats.db')
    c = conn.cursor()
    
    # 24時間前との比較
    c.execute('''
        SELECT 
            subscribers, views, videos
        FROM channel_stats 
        WHERE timestamp >= datetime('now', '-1 day')
        ORDER BY timestamp ASC
        LIMIT 1
    ''')
    yesterday_stats = c.fetchone()
    
    # 7日前との比較
    c.execute('''
        SELECT 
            subscribers, views, videos
        FROM channel_stats 
        WHERE timestamp >= datetime('now', '-7 day')
        ORDER BY timestamp ASC
        LIMIT 1
    ''')
    week_ago_stats = c.fetchone()
    
    # 最新の統計
    c.execute('''
        SELECT 
            subscribers, views, videos
        FROM channel_stats 
        ORDER BY timestamp DESC
        LIMIT 1
    ''')
    current_stats = c.fetchone()
    
    conn.close()
    
    if not all([yesterday_stats, week_ago_stats, current_stats]):
        return {
            'daily': {'subscribers': 0, 'views': 0, 'videos': 0},
            'weekly': {'subscribers': 0, 'views': 0, 'videos': 0},
            'weekly_growth': {'subscribers': 0, 'views': 0}
        }
    
    daily_changes = {
        'subscribers': current_stats[0] - yesterday_stats[0],
        'views': current_stats[1] - yesterday_stats[1],
        'videos': current_stats[2] - yesterday_stats[2]
    }
    
    weekly_changes = {
        'subscribers': current_stats[0] - week_ago_stats[0],
        'views': current_stats[1] - week_ago_stats[1],
        'videos': current_stats[2] - week_ago_stats[2]
    }
    
    weekly_growth = {
        'subscribers': round((weekly_changes['subscribers'] / week_ago_stats[0]) * 100, 1) if week_ago_stats[0] > 0 else 0,
        'views': round((weekly_changes['views'] / week_ago_stats[1]) * 100, 1) if week_ago_stats[1] > 0 else 0
    }
    
    return {
        'daily': daily_changes,
        'weekly': weekly_changes,
        'weekly_growth': weekly_growth
    }

def get_channel_name():
    conn = sqlite3.connect('youtube_stats.db')
    c = conn.cursor()
    
    # キャッシュされたチャンネル名を確認
    c.execute('''
        SELECT channel_name, last_updated 
        FROM channel_info 
        WHERE channel_id = ?
    ''', (RIVAL_CHANNEL_ID,))
    result = c.fetchone()
    
    # キャッシュが24時間以内なら、それを使用
    if result and (datetime.now() - datetime.fromisoformat(result[1])) < timedelta(hours=24):
        conn.close()
        return result[0]
    
    # キャッシュがない、または古い場合はAPIで取得
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    channel_request = youtube.channels().list(
        part="snippet",
        id=RIVAL_CHANNEL_ID
    )
    channel_response = channel_request.execute()
    channel_name = channel_response["items"][0]["snippet"]["title"]
    
    # チャンネル名を更新
    c.execute('''
        INSERT OR REPLACE INTO channel_info (channel_id, channel_name, last_updated)
        VALUES (?, ?, CURRENT_TIMESTAMP)
    ''', (RIVAL_CHANNEL_ID, channel_name))
    conn.commit()
    conn.close()
    
    return channel_name

def get_channel_stats():
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    
    # チャンネル統計を取得
    channel_request = youtube.channels().list(
        part="statistics,snippet",
        id=RIVAL_CHANNEL_ID
    )
    channel_response = channel_request.execute()
    stats = channel_response["items"][0]["statistics"]
    channel_name = channel_response["items"][0]["snippet"]["title"]

    # 最新の動画のパフォーマンスを取得
    videos_request = youtube.search().list(
        part="snippet",
        channelId=RIVAL_CHANNEL_ID,
        order="date",
        maxResults=1,
        type="video"
    )
    videos_response = videos_request.execute()
    
    if videos_response["items"]:
        latest_video = videos_response["items"][0]
        latest_video_id = latest_video["id"]["videoId"]
        latest_video_title = latest_video["snippet"]["title"]
        latest_video_published_at = latest_video["snippet"]["publishedAt"]
        
        video_request = youtube.videos().list(
            part="statistics",
            id=latest_video_id
        )
        video_response = video_request.execute()
        video_stats = video_response["items"][0]["statistics"]
    else:
        latest_video_id = None
        latest_video_title = None
        latest_video_published_at = None
        video_stats = {"viewCount": "0", "likeCount": "0", "commentCount": "0"}

    stats_data = {
        "channel_name": channel_name,
        "subscribers": int(stats.get("subscriberCount", "0")),
        "views": int(stats.get("viewCount", "0")),
        "videos": int(stats.get("videoCount", "0")),
        "latest_video_id": latest_video_id,
        "latest_video_title": latest_video_title,
        "latest_video_published_at": latest_video_published_at,
        "latest_video_views": int(video_stats.get("viewCount", "0")),
        "latest_video_likes": int(video_stats.get("likeCount", "0")),
        "latest_video_comments": int(video_stats.get("commentCount", "0"))
    }
    
    # 統計を保存
    save_stats(stats_data)
    
    return stats_data

def get_top_videos():
    conn = sqlite3.connect('youtube_stats.db')
    c = conn.cursor()
    
    # 最後の更新時刻を確認
    c.execute('SELECT last_updated, video_data FROM top_videos_cache')
    cache_data = c.fetchone()
    
    # キャッシュが1週間以内なら、それを使用
    if cache_data and (datetime.now() - datetime.fromisoformat(cache_data[0])) < timedelta(days=7):
        import json
        videos = json.loads(cache_data[1])
        
        # published_atを文字列からdatetimeに変換
        for video in videos:
            video["published_at"] = datetime.fromisoformat(video["published_at"])
        
        # 前回のランキングデータを取得（1週間前）
        c.execute('''
            SELECT video_id, rank, views, likes, comments
            FROM top_videos_history
            WHERE timestamp <= datetime('now', '-7 days')
            ORDER BY timestamp DESC
            LIMIT 3
        ''')
        last_week_data = {row[0]: {"rank": row[1], "views": row[2], "likes": row[3], "comments": row[4]} 
                         for row in c.fetchall()}
        
        # 投稿日時を取得
        video_ids = [v["video_id"] for v in videos]
        placeholders = ','.join('?' * len(video_ids))
        c.execute(f'''
            SELECT video_id, published_at
            FROM video_stats
            WHERE video_id IN ({placeholders})
        ''', video_ids)
        publish_dates = {row[0]: datetime.fromisoformat(row[1]) for row in c.fetchall()}
        
        # 各動画の情報を更新
        for i, video in enumerate(videos, 1):
            video_id = video["video_id"]
            last_week = last_week_data.get(video_id, {"rank": None, "views": 0, "likes": 0, "comments": 0})
            
            # ランキング変動を計算
            if last_week["rank"] is None:
                rank_change = "🆕"  # 新規ランクイン
            else:
                rank_diff = last_week["rank"] - i
                if rank_diff > 0:
                    rank_change = f"⬆️ +{rank_diff}"
                elif rank_diff < 0:
                    rank_change = f"⬇️ {rank_diff}"
                else:
                    rank_change = "➡️"
            
            # 統計の増加を計算
            views_increase = video["views"] - last_week["views"]
            likes_increase = video["likes"] - last_week["likes"]
            comments_increase = video["comments"] - last_week["comments"]
            
            # 投稿日時を追加
            video["published_at"] = publish_dates.get(video_id, datetime.now())
            video["rank_change"] = rank_change
            video["views_increase"] = views_increase
            video["likes_increase"] = likes_increase
            video["comments_increase"] = comments_increase
        
        conn.close()
        return videos
    
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    
    # 1ヶ月前の時刻を計算
    one_month_ago = (datetime.now() - timedelta(days=30)).isoformat() + 'Z'
    
    # チャンネルの動画を取得（過去1ヶ月のみ）
    videos = []
    next_page_token = None
    
    while True:
        # 動画一覧を取得
        request = youtube.search().list(
            part="snippet",
            channelId=RIVAL_CHANNEL_ID,
            maxResults=50,
            type="video",
            order="viewCount",
            publishedAfter=one_month_ago,
            pageToken=next_page_token
        )
        response = request.execute()
        
        video_ids = [item["id"]["videoId"] for item in response["items"]]
        
        # 動画の詳細情報を取得
        if video_ids:
            video_request = youtube.videos().list(
                part="statistics,snippet",
                id=",".join(video_ids)
            )
            video_response = video_request.execute()
            
            for video in video_response["items"]:
                published_at = video["snippet"]["publishedAt"]
                videos.append({
                    "title": video["snippet"]["title"],
                    "views": int(video["statistics"].get("viewCount", 0)),
                    "likes": int(video["statistics"].get("likeCount", 0)),
                    "comments": int(video["statistics"].get("commentCount", 0)),
                    "video_id": video["id"],
                    "published_at": datetime.fromisoformat(published_at.replace('Z', '+00:00')),
                    "rank_change": "🆕",  # 新規取得時は全て新規
                    "views_increase": 0,   # 新規取得時は増加分を0に
                    "likes_increase": 0,   # 新規取得時は増加分を0に
                    "comments_increase": 0  # 新規取得時は増加分を0に
                })
        
        next_page_token = response.get("nextPageToken")
        if not next_page_token or len(videos) >= 100:  # 最大100動画まで取得
            break
    
    # 再生回数で降順ソート
    videos.sort(key=lambda x: x["views"], reverse=True)
    top_3_videos = videos[:3]
    
    # ランキング履歴を保存
    for i, video in enumerate(top_3_videos, 1):
        c.execute('''
            INSERT INTO top_videos_history (video_id, rank, views, likes, comments)
            VALUES (?, ?, ?, ?, ?)
        ''', (video["video_id"], i, video["views"], video["likes"], video["comments"]))
    
    # キャッシュを更新する前に、datetime オブジェクトを文字列に変換
    cache_videos = []
    for video in top_3_videos:
        video_copy = video.copy()
        video_copy["published_at"] = video_copy["published_at"].isoformat()
        cache_videos.append(video_copy)
    
    # キャッシュを更新
    import json
    c.execute('DELETE FROM top_videos_cache')  # 古いキャッシュを削除
    c.execute('''
        INSERT INTO top_videos_cache (last_updated, video_data)
        VALUES (CURRENT_TIMESTAMP, ?)
    ''', (json.dumps(cache_videos),))
    conn.commit()
    conn.close()
    
    return top_3_videos

def get_recent_videos():
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    
    # 24時間前の時刻を計算
    one_day_ago = (datetime.now() - timedelta(days=1)).isoformat() + 'Z'
    
    # 最新の動画を取得
    request = youtube.search().list(
        part="snippet",
        channelId=RIVAL_CHANNEL_ID,
        order="date",
        maxResults=10,  # 十分な数を指定
        type="video",
        publishedAfter=one_day_ago
    )
    response = request.execute()
    
    recent_videos = []
    if response["items"]:
        video_ids = [item["id"]["videoId"] for item in response["items"]]
        
        # 動画の詳細情報を一括取得
        video_request = youtube.videos().list(
            part="statistics",
            id=",".join(video_ids)
        )
        video_response = video_request.execute()
        
        # 動画情報とstatisticsを結合
        for search_item, video_item in zip(response["items"], video_response["items"]):
            published_at = search_item["snippet"]["publishedAt"]
            published_datetime = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
            
            recent_videos.append({
                "title": search_item["snippet"]["title"],
                "published_at": published_datetime,
                "views": int(video_item["statistics"].get("viewCount", 0)),
                "likes": int(video_item["statistics"].get("likeCount", 0)),
                "comments": int(video_item["statistics"].get("commentCount", 0)),
                "video_id": video_item["id"]
            })
    
    return recent_videos

def calculate_engagement_rate(views, likes, comments):
    if views == 0:
        return 0
    return round(((likes + comments) / views) * 100, 2)

def analyze_video_performance(video_data):
    # 動画のパフォーマンスを分析
    current_time = datetime.now(video_data["published_at"].tzinfo)  # 同じタイムゾーンを使用
    hours_since_upload = (current_time - video_data["published_at"]).total_seconds() / 3600
    views_per_hour = video_data["views"] / hours_since_upload if hours_since_upload > 0 else 0
    
    engagement_rate = calculate_engagement_rate(
        video_data["views"],
        video_data["likes"],
        video_data["comments"]
    )

    return {
        "views_per_hour": round(views_per_hour, 2),
        "engagement_rate": engagement_rate
    }

def calculate_posting_pace():
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    
    # 最新の10件の動画を取得
    request = youtube.search().list(
        part="snippet",
        channelId=RIVAL_CHANNEL_ID,
        order="date",
        maxResults=10,
        type="video"
    )
    response = request.execute()
    
    if len(response["items"]) < 2:
        return "不明"  # データが不十分な場合
    
    # 投稿日時のリストを作成
    dates = []
    for item in response["items"]:
        published_at = datetime.fromisoformat(item["snippet"]["publishedAt"].replace('Z', '+00:00'))
        dates.append(published_at)
    
    # 投稿間隔を計算
    intervals = []
    for i in range(len(dates) - 1):
        interval = dates[i] - dates[i + 1]
        intervals.append(interval.total_seconds() / 3600)  # 時間単位に変換
    
    # 平均投稿間隔を計算
    avg_interval = sum(intervals) / len(intervals)
    
    # 投稿ペースを分かりやすい表現に変換
    if avg_interval < 24:
        return f"{round(avg_interval, 1)}時間に1回"
    else:
        days = avg_interval / 24
        return f"{round(days, 1)}日に1回"

def analyze_title(title, views=0):
    # 基本的な単語分割
    words = re.findall(r'\w+', title.lower())
    word_count = Counter(words)
    
    # パターンの検出
    patterns = []
    if re.search(r'#\d+', title):
        patterns.append('numbered_series')
    if re.search(r'【.*】', title):
        patterns.append('bracketed')
    if re.search(r'\d+分|分間', title):
        patterns.append('duration_mentioned')
    
    # 効果的なキーワードの抽出
    keywords = [word for word, count in word_count.most_common(5)]
    
    return {
        'keywords': keywords,
        'pattern_type': ','.join(patterns) if patterns else 'standard',
        'effectiveness_score': min(100, len(title) * 2),  # 仮のスコアリング
        'keyword_scores': {word: 1.0 for word in keywords}  # 将来の分析のために
    }

def analyze_thumbnail_image(image_url):
    try:
        # 画像をダウンロード
        response = requests.get(image_url)
        image_array = np.asarray(bytearray(response.content), dtype=np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        
        if image is None:
            return None
        
        # 画像サイズを取得
        height, width = image.shape[:2]
        
        # 色分析
        pixels = image.reshape(-1, 3)
        pixels = np.float32(pixels)
        n_colors = 3
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 200, .1)
        _, labels, palette = cv2.kmeans(pixels, n_colors, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)
        
        # 各色の割合を計算
        _, counts = np.unique(labels, return_counts=True)
        percentages = counts / counts.sum() * 100
        
        # 色情報をRGB形式で保存
        colors = []
        for color, percentage in zip(palette, percentages):
            b, g, r = color
            colors.append({
                'rgb': f'#{int(r):02x}{int(g):02x}{int(b):02x}',
                'percentage': round(percentage, 1)
            })
        
        # テキスト領域の検出
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # テキスト配置の分析
        text_regions = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w * h > (width * height * 0.01):  # 小さすぎる領域を除外
                region = {
                    'x': x / width,
                    'y': y / height,
                    'width': w / width,
                    'height': h / height
                }
                text_regions.append(region)
        
        # テキスト配置の分類
        text_placement = 'center'  # デフォルト
        if text_regions:
            avg_x = np.mean([r['x'] for r in text_regions])
            avg_y = np.mean([r['y'] for r in text_regions])
            
            if avg_x < 0.33:
                text_placement = 'left'
            elif avg_x > 0.66:
                text_placement = 'right'
            
            if avg_y < 0.33:
                text_placement = f'top_{text_placement}'
            elif avg_y > 0.66:
                text_placement = f'bottom_{text_placement}'
        
        # インパクトスコアの計算
        impact_score = min(100, (
            len(text_regions) * 20 +  # テキスト領域の数
            len(colors) * 15 +        # 使用色数
            (max(percentages) - min(percentages)) * 0.5  # 色の対比
        ))
        
        return {
            'dominant_colors': colors,
            'text_placement': text_placement,
            'composition_score': round(min(100, len(text_regions) * 25), 1),
            'impact_score': round(impact_score, 1),
            'template_type': 'standard'  # 今後のパターン分析のために
        }
        
    except Exception as e:
        print(f"サムネイル分析エラー: {str(e)}")
        return None

def get_title_analysis_report(video_id, title, views):
    conn = sqlite3.connect('youtube_stats.db')
    c = conn.cursor()
    
    # 分析実行
    analysis = analyze_title(title, views)
    
    # 分析結果を保存
    import json
    c.execute('''
        INSERT OR REPLACE INTO title_analysis 
        (video_id, keywords, keyword_scores, pattern_type, effectiveness_score)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        video_id,
        json.dumps(analysis['keywords']),
        json.dumps(analysis['keyword_scores']),
        analysis['pattern_type'],
        analysis['effectiveness_score']
    ))
    
    # キーワードのパフォーマンスを更新
    current_month = datetime.now().strftime('%Y-%m')
    for keyword in analysis['keywords']:
        c.execute('''
            INSERT OR REPLACE INTO keyword_performance 
            (keyword, month_year, use_count, avg_views, avg_engagement)
            VALUES (
                ?,
                ?,
                COALESCE((SELECT use_count FROM keyword_performance 
                          WHERE keyword = ? AND month_year = ?) + 1, 1),
                ?,
                COALESCE((SELECT avg_engagement FROM keyword_performance 
                          WHERE keyword = ? AND month_year = ?), 0)
            )
        ''', (keyword, current_month, keyword, current_month, views, keyword, current_month))
    
    conn.commit()
    
    # トレンドキーワードを取得
    c.execute('''
        SELECT keyword, use_count, avg_views
        FROM keyword_performance
        WHERE month_year = ?
        ORDER BY use_count DESC, avg_views DESC
        LIMIT 3
    ''', (current_month,))
    trending_keywords = c.fetchall()
    
    conn.close()
    
    return {
        'pattern_type': analysis['pattern_type'],
        'effectiveness_score': analysis['effectiveness_score'],
        'keywords': analysis['keywords'],
        'trending_keywords': trending_keywords
    }

def get_thumbnail_analysis_report(video_id, thumbnail_url):
    conn = sqlite3.connect('youtube_stats.db')
    c = conn.cursor()
    
    # サムネイル分析を実行
    analysis = analyze_thumbnail_image(thumbnail_url)
    if not analysis:
        conn.close()
        return None
    
    # 分析結果を保存
    import json
    c.execute('''
        INSERT OR REPLACE INTO thumbnail_analysis 
        (video_id, dominant_colors, text_placement, composition_score, 
         impact_score, template_type)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        video_id,
        json.dumps(analysis['dominant_colors']),
        analysis['text_placement'],
        analysis['composition_score'],
        analysis['impact_score'],
        analysis['template_type']
    ))
    
    conn.commit()
    conn.close()
    
    return analysis

def get_cached_stats(max_age_hours=1):
    """キャッシュされた統計情報を取得"""
    conn = sqlite3.connect('youtube_stats.db')
    c = conn.cursor()
    
    # チャンネル統計の取得
    c.execute('''
        SELECT subscribers, views, videos, timestamp, channel_name
        FROM channel_stats cs
        JOIN channel_info ci ON ci.channel_id = ?
        WHERE cs.timestamp >= datetime('now', ? || ' hours')
        ORDER BY cs.timestamp DESC
        LIMIT 1
    ''', (RIVAL_CHANNEL_ID, -max_age_hours))
    
    result = c.fetchone()
    
    if result:
        stats = {
            "subscribers": result[0],
            "views": result[1],
            "videos": result[2],
            "channel_name": result[4],
            "is_cached": True,
            "cache_age": result[3]
        }
        
        # 最新の動画情報も取得
        c.execute('''
            SELECT video_id, title, published_at, views, likes, comments
            FROM video_stats
            WHERE published_at >= datetime('now', '-1 day')
            ORDER BY published_at DESC
            LIMIT 1
        ''')
        latest_video = c.fetchone()
        
        if latest_video:
            stats.update({
                "latest_video_id": latest_video[0],
                "latest_video_title": latest_video[1],
                "latest_video_published_at": latest_video[2],
                "latest_video_views": latest_video[3],
                "latest_video_likes": latest_video[4],
                "latest_video_comments": latest_video[5]
            })
        
        conn.close()
        return stats
    
    conn.close()
    return None

def get_cached_videos(cache_type="top", max_age_hours=12):
    """キャッシュされた動画情報を取得"""
    conn = sqlite3.connect('youtube_stats.db')
    c = conn.cursor()
    
    if cache_type == "top":
        c.execute('''
            SELECT last_updated, video_data 
            FROM top_videos_cache
            WHERE last_updated >= datetime('now', ? || ' hours')
        ''', (-max_age_hours,))
    else:  # recent
        c.execute('''
            SELECT video_id, title, published_at, views, likes, comments
            FROM video_stats
            WHERE published_at >= datetime('now', '-1 day')
            AND last_updated >= datetime('now', ? || ' hours')
            ORDER BY published_at DESC
        ''', (-max_age_hours,))
    
    result = c.fetchall()
    conn.close()
    
    if result:
        if cache_type == "top":
            import json
            videos = json.loads(result[0][1])
            for video in videos:
                video["published_at"] = datetime.fromisoformat(video["published_at"])
            return videos
        else:
            return [{
                "video_id": r[0],
                "title": r[1],
                "published_at": datetime.fromisoformat(r[2]),
                "views": r[3],
                "likes": r[4],
                "comments": r[5]
            } for r in result]
    
    return None

def calculate_engagement_metrics():
    """保存済みデータを使用したエンゲージメント分析"""
    conn = sqlite3.connect('youtube_stats.db')
    c = conn.cursor()
    
    # 過去30日間の動画のエンゲージメント率を計算
    thirty_days_ago = (datetime.now() - timedelta(days=30)).isoformat()
    c.execute('''
        SELECT 
            title,
            views,
            likes,
            comments,
            published_at,
            video_id
        FROM video_stats
        WHERE published_at >= ?
        ORDER BY views DESC
    ''', (thirty_days_ago,))
    
    videos = c.fetchall()
    engagement_data = []
    
    for video in videos:
        title, views, likes, comments, published_at, video_id = video
        if views > 0:
            engagement_rate = ((likes + comments) / views) * 100
            engagement_data.append({
                "title": title,
                "engagement_rate": round(engagement_rate, 2),
                "views": views,
                "published_at": published_at,
                "video_id": video_id
            })
    
    conn.close()
    return engagement_data

def analyze_posting_pattern():
    """投稿パターンの分析"""
    conn = sqlite3.connect('youtube_stats.db')
    c = conn.cursor()
    
    c.execute('''
        SELECT 
            strftime('%H', published_at) as hour,
            strftime('%w', published_at) as day_of_week,
            AVG(views) as avg_views,
            COUNT(*) as post_count
        FROM video_stats
        GROUP BY hour, day_of_week
        ORDER BY avg_views DESC
    ''')
    
    patterns = c.fetchall()
    conn.close()
    
    days = ['日', '月', '火', '水', '木', '金', '土']
    best_patterns = []
    
    for hour, day_of_week, avg_views, post_count in patterns[:5]:
        best_patterns.append({
            "day": days[int(day_of_week)],
            "hour": int(hour),
            "avg_views": int(avg_views),
            "post_count": post_count
        })
    
    return best_patterns

async def send_daily_report(channel):
    try:
        print("\n=== レポート生成開始 ===")
        
        # チャンネル統計を取得
        channel_stats = get_channel_stats()
        print("チャンネル統計を取得しました")
        
        # 人気動画を取得（過去1ヶ月以内、再生数トップ3）
        top_videos = get_top_videos()
        print("人気動画情報を取得しました")
        
        # 新着動画を取得（過去24時間以内）
        recent_videos = get_recent_videos()
        print("新着動画情報を取得しました")

        # レポートの作成
        report = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
　　🎥 **YouTubeチャンネル分析レポート** 🎥
　　　　　　{datetime.now().strftime('%m/%d %H:%M')}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 **{channel_stats.get('channel_name', '不明')}**
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
┃ 👥 チャンネル登録者数: {channel_stats['subscribers']:,}
┃ 👀 総再生回数: {channel_stats['views']:,}
┃ 📹 総動画数: {channel_stats['videos']}
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

        # 新着動画セクション（過去24時間）
        if recent_videos:
            report += "\n\n📝 **新着動画（過去24時間）**"
            for video in recent_videos:
                report += f"""
・{video['title']}
　👀 {video['views']:,} 👍 {video['likes']:,} 💭 {video['comments']:,}
　🔗 https://youtu.be/{video['video_id']}"""
        else:
            report += "\n\n📝 新着動画はありません"

        # 人気動画セクション（過去1ヶ月）
        if top_videos:
            report += "\n\n🎬 **人気動画TOP3（過去1ヶ月）**"
            medals = ["🥇", "🥈", "🥉"]
            for i, video in enumerate(top_videos[:3]):
                report += f"""
{medals[i]} {video['title']}
　👀 {video['views']:,}
　👍 {video['likes']:,}
　💭 {video['comments']:,}
　🔗 https://youtu.be/{video['video_id']}"""

        # レポートの送信
        await channel.send(report)
        print("✨ レポート生成・送信が完了しました")

    except Exception as e:
        print(f"❌ エラーが発生しました: {str(e)}")
        traceback.print_exc()

# スケジュール設定を朝9時のみに変更
@client.event
async def on_ready():
    print(f'{client.user} としてログインしました')
    
    # データベースの初期化
    init_db()
    
    # レポートの送信
    target_channel = client.get_channel(1350462901541929060)
    if target_channel:
        await send_daily_report(target_channel)
    else:
        print('エラー: 対象のチャンネルが見つかりません')
    
    # 定期実行タスクの設定（朝9時のみ）
    schedule.every().day.at("09:00").do(lambda: asyncio.create_task(send_daily_report(client.get_channel(1350462901541929060))))
    
    while True:
        schedule.run_pending()
        await asyncio.sleep(60)

# Discordクライアントを実行
load_dotenv()
client.run(os.getenv('DISCORD_TOKEN'))
