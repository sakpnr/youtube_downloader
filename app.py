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

app = Flask(__name__)
socketio = SocketIO(app, async_mode='eventlet', cors_allowed_origins="*")

# Uygulama modunu belirle
IS_LOCAL = os.name == 'nt'  # Windows'ta çalışıyorsa yerel moddur

# Video bilgilerini önbelleğe alma
@lru_cache(maxsize=100)
def get_video_info(url):
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,  # Sadece video bilgilerini al
            'no_playlist': True,   # Oynatma listelerini devre dışı bırak
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
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        if not IS_LOCAL and 'Sign in to confirm' in str(e):
            raise Exception('Bu video için giriş yapmanız gerekiyor. Uygulamayı yerel olarak kullanarak tüm videoları indirebilirsiniz.')
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
        
        info = get_video_info(url)
        formats = []
        seen_qualities = set()
        
        if download_type == 'audio':
            audio_formats = [f for f in info['formats'] if 
                           f.get('acodec', 'none') != 'none' and 
                           f.get('vcodec', 'none') == 'none']
            
            for f in audio_formats:
                abr = f.get('abr', 0)
                if abr > 0:
                    quality = f'{abr}'
                    if quality not in seen_qualities:
                        formats.append({
                            'format_id': f['format_id'],
                            'quality': quality,
                            'ext': 'mp3',
                            'filesize': f.get('filesize', 0),
                            'abr': abr
                        })
                        seen_qualities.add(quality)
            
            formats.sort(key=lambda x: x.get('abr', 0), reverse=True)
            
        else:
            for f in info['formats']:
                if f.get('vcodec', 'none') != 'none' and f.get('ext', '') == 'mp4':
                    height = f.get('height', 0)
                    quality = f'{height}p' if height else f.get('format_note', 'unknown')
                    
                    if f.get('acodec') == 'none':
                        audio_formats = [af for af in info['formats'] if 
                                      af.get('vcodec') == 'none' and 
                                      af.get('acodec') != 'none']
                        if audio_formats:
                            best_audio = max(audio_formats, 
                                          key=lambda x: x.get('abr', 0) or 0)
                            format_id = f'{f["format_id"]}+{best_audio["format_id"]}'
                        else:
                            continue
                    else:
                        format_id = f['format_id']
                    
                    if quality not in seen_qualities and height >= 360:
                        formats.append({
                            'format_id': format_id,
                            'quality': quality,
                            'ext': f['ext'],
                            'filesize': f.get('filesize', 0),
                            'format_note': f.get('format_note', ''),
                            'height': height
                        })
                        seen_qualities.add(quality)
            
            formats.sort(key=lambda x: x.get('height', 0), reverse=True)
        
        return jsonify({
            'success': True,
            'title': info['title'],
            'formats': formats,
            'thumbnail': info.get('thumbnail', ''),
            'duration': info.get('duration', 0),
            'description': info.get('description', ''),
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
            info = get_video_info(url)  # Önce video bilgilerini kontrol et
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