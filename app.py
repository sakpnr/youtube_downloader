from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from pytube import YouTube
import os
import tempfile

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

@app.route('/download', methods=['POST'])
def download_video():
    try:
        data = request.get_json()
        url = data.get('url')
        format_type = data.get('format')
        quality = data.get('quality')

        if not url:
            return jsonify({'error': 'URL is required'}), 400

        yt = YouTube(url)
        
        # Create a temporary directory for downloads
        temp_dir = tempfile.mkdtemp()
        
        if format_type == 'audio':
            # Download as MP3
            video = yt.streams.filter(only_audio=True).first()
            download_path = video.download(temp_dir)
            
            # Convert to MP3
            base, ext = os.path.splitext(download_path)
            new_file = base + '.mp3'
            os.rename(download_path, new_file)
            
            response = send_file(
                new_file,
                as_attachment=True,
                download_name=f"{yt.title}.mp3",
                mimetype="audio/mpeg"
            )
            
        else:
            # Download as video
            if quality == 'highest':
                video = yt.streams.get_highest_resolution()
            else:
                video = yt.streams.filter(res=quality, file_extension='mp4').first()
                if not video:
                    video = yt.streams.get_highest_resolution()
            
            download_path = video.download(temp_dir)
            
            response = send_file(
                download_path,
                as_attachment=True,
                download_name=f"{yt.title}.mp4",
                mimetype="video/mp4"
            )
        
        # Clean up temp files after sending
        @response.call_on_close
        def cleanup():
            try:
                os.remove(download_path)
                os.rmdir(temp_dir)
            except:
                pass
                
        return response
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)