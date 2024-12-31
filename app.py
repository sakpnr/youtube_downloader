from flask import Flask, render_template, request, jsonify, send_file
from flask_socketio import SocketIO
import yt_dlp
import os
import requests
import zipfile
import shutil
import subprocess
import json
from pathlib import Path
from functools import lru_cache
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

app = Flask(__name__)
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# Uygulama modunu belirle
IS_LOCAL = os.name == 'nt'  # Windows'ta çalışıyorsa yerel moddur

# YouTube API anahtarı
YOUTUBE_API_KEY = os.environ.get('YOUTUBE_API_KEY', '')  # API anahtarı çevre değişkeninden alınacak

# YouTube API servisi
def get_youtube_service():
    try:
        if not YOUTUBE_API_KEY:
            raise Exception("YouTube API anahtarı bulunamadı. Lütfen çevre değişkenlerini kontrol edin.")
        return build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    except Exception as e:
        print(f"YouTube API servis hatası: {str(e)}")
        raise Exception("YouTube API bağlantısı kurulamadı. Lütfen API anahtarını kontrol edin.")

# Video ID'sini URL'den ayıkla
def extract_video_id(url):
    if 'youtu.be' in url:
        return url.split('/')[-1].split('?')[0]
    elif 'youtube.com' in url:
        if 'v=' in url:
            return url.split('v=')[1].split('&')[0]
    return url

# Video bilgilerini YouTube API ile al
def get_video_info_from_api(url):
    try:
        video_id = extract_video_id(url)
        youtube = get_youtube_service()
        
        # Video detaylarını al
        video_response = youtube.videos().list(
            part='snippet,contentDetails,statistics',
            id=video_id
        ).execute()

        if not video_response['items']:
            raise Exception('Video bulunamadı')

        video = video_response['items'][0]
        snippet = video['snippet']
        content_details = video['contentDetails']

        # Video süresini saniyeye çevir
        duration = content_details['duration']
        duration_sec = sum(x * int(t) for x, t in zip([3600, 60, 1], 
            str(duration).replace('PT','').replace('H',':').replace('M',':').replace('S','').split(':')))

        formats = []
        # Video formatları
        video_formats = [
            {'format_id': 'hd1080', 'quality': '1080p', 'height': 1080},
            {'format_id': 'hd720', 'quality': '720p', 'height': 720},
            {'format_id': 'large', 'quality': '480p', 'height': 480},
            {'format_id': 'medium', 'quality': '360p', 'height': 360}
        ]
        
        # Ses formatları
        audio_formats = [
            {'format_id': 'highaudio', 'quality': '192', 'abr': 192},
            {'format_id': 'mediumaudio', 'quality': '128', 'abr': 128},
            {'format_id': 'lowaudio', 'quality': '96', 'abr': 96}
        ]

        return {
            'id': video_id,
            'title': snippet['title'],
            'description': snippet['description'],
            'thumbnail': snippet['thumbnails']['high']['url'],
            'duration': duration_sec,
            'video_formats': video_formats,
            'audio_formats': audio_formats
        }

    except HttpError as e:
        print(f'YouTube API Hatası: {e}')
        raise Exception(f'YouTube API Hatası: {str(e)}')
    except Exception as e:
        print(f'Hata: {e}')
        raise e

def progress_hook(d):
    if d['status'] == 'downloading':
        try:
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes', 0)
            
            if total == 0:
                total = d.get('total_bytes_estimate', 0)
            
            if total > 0:
                percentage = (downloaded / total) * 100
                socketio.emit('download_progress', {'percentage': round(percentage, 1)})
            else:
                downloaded_mb = downloaded / (1024 * 1024)
                socketio.emit('download_progress', {'percentage': -1, 'downloaded': round(downloaded_mb, 1)})
        except Exception as e:
            print(f"İlerleme güncellemesi hatası: {str(e)}")

def setup_ffmpeg():
    ffmpeg_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg')
    ffmpeg_exe = os.path.join(ffmpeg_dir, 'bin', 'ffmpeg.exe')
    
    if os.path.exists(ffmpeg_exe):
        return ffmpeg_dir
    
    ffmpeg_url = "https://github.com/GyanD/codexffmpeg/releases/download/6.1.1/ffmpeg-6.1.1-full_build.zip"
    zip_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg.zip')
    
    print("FFmpeg indiriliyor...")
    response = requests.get(ffmpeg_url, stream=True)
    with open(zip_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    
    print("FFmpeg çıkartılıyor...")
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(os.path.dirname(os.path.abspath(__file__)))
    
    os.remove(zip_path)
    
    extracted_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ffmpeg-6.1.1-full_build')
    if os.path.exists(ffmpeg_dir):
        shutil.rmtree(ffmpeg_dir)
    os.rename(extracted_dir, ffmpeg_dir)
    
    return ffmpeg_dir

@app.route('/')
def home():
    return render_template('index.html', is_local=IS_LOCAL)

@app.route('/get-formats', methods=['POST'])
def get_video_formats():
    try:
        url = request.json['url']
        download_type = request.json.get('type', 'video')
        
        if not url:
            return jsonify({
                'success': False,
                'message': 'URL boş olamaz!'
            }), 400
        
        info = get_video_info_from_api(url)
        formats = []
        
        if download_type == 'audio':
            for f in info['audio_formats']:
                formats.append({
                    'format_id': f['format_id'],
                    'quality': f'{f["quality"]} kbps',
                    'ext': 'mp3',
                    'abr': f['abr']
                })
        else:
            for f in info['video_formats']:
                formats.append({
                    'format_id': f['format_id'],
                    'quality': f['quality'],
                    'ext': 'mp4',
                    'height': f['height']
                })
        
        return jsonify({
            'success': True,
            'title': info['title'],
            'formats': formats,
            'thumbnail': info['thumbnail'],
            'duration': info['duration'],
            'description': info['description'],
            'is_local': IS_LOCAL
        })
        
    except Exception as e:
        print(f"Hata detayı: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Hata oluştu: {str(e)}'
        }), 400

@app.route('/select-folder', methods=['POST'])
def select_folder():
    try:
        # PowerShell komutu ile klasör seçme dialogunu aç
        ps_command = '''
        Add-Type -AssemblyName System.Windows.Forms
        $folderBrowser = New-Object System.Windows.Forms.FolderBrowserDialog
        $folderBrowser.Description = "İndirme konumunu seçin"
        $folderBrowser.RootFolder = "MyComputer"
        $null = $folderBrowser.ShowDialog()
        $folderBrowser.SelectedPath
        '''
        
        # PowerShell komutunu çalıştır
        result = subprocess.run(["powershell", "-Command", ps_command], 
                              capture_output=True, text=True, encoding='utf-8')
        
        folder_path = result.stdout.strip()
        
        if folder_path:
            return jsonify({
                'success': True,
                'path': folder_path
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Klasör seçilmedi'
            })
    except Exception as e:
        print(f"Klasör seçme hatası: {str(e)}")
        return jsonify({
            'success': False,
            'message': str(e)
        })

@app.route('/download', methods=['POST'])
def download_video():
    try:
        url = request.json['url']
        format_id = request.json.get('format_id', 'best')
        download_type = request.json.get('type', 'video')
        download_path = request.json.get('download_path', 'downloads')

        if not url:
            return jsonify({
                'success': False,
                'message': 'URL boş olamaz!'
            }), 400
        
        ffmpeg_dir = setup_ffmpeg()
        ffmpeg_path = os.path.join(ffmpeg_dir, 'bin', 'ffmpeg.exe')
        
        if not os.path.exists(download_path):
            os.makedirs(download_path)
        
        ydl_opts = {
            'format': format_id,
            'outtmpl': os.path.join(download_path, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'ffmpeg_location': ffmpeg_path,
            'progress_hooks': [progress_hook],
            'concurrent_fragments': 3,
            'retries': 10,
            'fragment_retries': 10,
            'buffersize': 1024 * 1024,
            'no_playlist': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate'
            }
        }
        
        # Yerel modda Chrome çerezlerini kullan
        if IS_LOCAL:
            ydl_opts['cookies_from_browser'] = 'chrome'
        
        if download_type == 'audio':
            ydl_opts.update({
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }, {
                    'key': 'EmbedThumbnail',
                }, {
                    'key': 'FFmpegMetadata',
                    'add_metadata': True,
                }],
                'writethumbnail': True,
                'keepvideo': False,
                'clean_infojson': True,
                'postprocessor_args': [
                    '-id3v2_version', '3',
                    '-metadata', 'title=%(title)s',
                ],
            })
        else:
            ydl_opts.update({
                'merge_output_format': 'mp4'
            })
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = get_video_info_from_api(url)  # Önce video bilgilerini kontrol et
            video_title = info.get('title', 'Video')
            ydl.download([url])
            
            ext = 'mp3' if download_type == 'audio' else 'mp4'
            filename = f"{video_title}.{ext}"
            
            return jsonify({
                'success': True,
                'message': f'{"Ses" if download_type == "audio" else "Video"} başarıyla indirildi!',
                'filename': filename,
                'title': video_title,
                'is_local': IS_LOCAL
            })
            
    except Exception as e:
        print(f"Hata detayı: {str(e)}")
        return jsonify({
            'success': False,
            'message': f'Hata oluştu: {str(e)}'
        }), 400

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0')