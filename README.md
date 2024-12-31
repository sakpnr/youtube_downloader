# YouTube Video İndirici

Bu proje, YouTube videolarını indirmek için kullanılan bir web uygulamasıdır. Flask framework'ü kullanılarak geliştirilmiştir.

## Özellikler

- YouTube video ve playlist indirme
- Farklı kalite seçenekleri
- MP3 formatına dönüştürme
- Kullanıcı dostu arayüz

## Kurulum

1. Projeyi klonlayın:
```bash
git clone https://github.com/KULLANICI_ADINIZ/youtube_downloader.git
cd youtube_downloader
```

2. Sanal ortam oluşturun ve aktif edin:
```bash
python -m venv venv
# Windows için:
venv\Scripts\activate
# Linux/Mac için:
source venv/bin/activate
```

3. Gerekli paketleri yükleyin:
```bash
pip install -r requirements.txt
```

4. FFmpeg'i indirin ve projenin kök dizinine yerleştirin.

5. Uygulamayı çalıştırın:
```bash
python app.py
```

## Kullanım

1. Tarayıcınızda `http://localhost:5000` adresine gidin
2. YouTube video URL'sini girin
3. İstediğiniz indirme seçeneklerini belirleyin
4. İndirme işlemini başlatın

## Lisans

Bu proje MIT lisansı altında lisanslanmıştır. 