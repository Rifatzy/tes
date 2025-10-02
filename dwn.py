import telebot
import yt_dlp
import os
import time
import re
from threading import Lock
import sys  # Buat restart
import subprocess  # Buat gallery-dl & FFmpeg
from PIL import Image, ImageDraw, ImageFont  # Buat sticker & meme
import io  # Buat in-memory image handling
import glob  # Buat scan files
from dotenv import load_dotenv  # Load .env

load_dotenv()  # Load .env file

# Load token from env (set di Termux: export BOT_TOKEN='your_token')
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    print("CRITICAL: Set BOT_TOKEN env var! (export BOT_TOKEN='your_token_here')")
    sys.exit(1)
bot = telebot.TeleBot(BOT_TOKEN)

# Per-chat progress tracking with lock
progress_lock = Lock()
progress_messages = {}  # {chat_id: {'msg_id': int, 'status': str}}

def get_platform(url):
    """Detect platform from URL."""
    url_lower = url.lower()
    if 'tiktok.com' in url_lower:
        return 'tiktok'
    elif 'instagram.com' in url_lower:
        return 'ig'
    elif 'youtube.com' in url_lower or 'youtu.be' in url_lower:
        return 'yt'
    elif 'x.com' in url_lower or 'twitter.com' in url_lower:
        return 'x'
    elif 'facebook.com' in url_lower:
        return 'fb'
    elif 'reddit.com' in url_lower:
        return 'reddit'
    elif 'pinterest.com' in url_lower:
        return 'pinterest'
    return 'general'

def is_valid_url(url):
    pattern = re.compile(r'https?://(?:www\.|vm\.|vt\.)?(youtube\.com|youtu\.be|tiktok\.com|instagram\.com|x\.com|twitter\.com|reddit\.com|facebook\.com|pinterest\.com)(?:/.*)?')
    return bool(pattern.match(url))

def resolve_url(url):
    """Resolve shortened URL ke full webpage URL pake yt-dlp (no download). Dengan retry."""
    url_lower = url.lower()
    for attempt in range(3):  # Retry 3x
        try:
            ydl_opts = {'quiet': True}  # Suppress output
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                return info.get('webpage_url', url)  # Fallback ke original kalo gagal
        except Exception as e:
            print(f"[DEBUG] Resolve attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(2)  # Wait before retry
    return url  # Kalo semua gagal, tetep pake original

def progress_hook(d, chat_id, msg_id):
    with progress_lock:
        if d['status'] == 'downloading' and chat_id in progress_messages:
            try:
                percent = d.get('_percent_str', '0%')
                speed = d.get('_speed_str', 'N/A')
                eta = d.get('_eta_str', 'N/A')
                bot.edit_message_text(
                    f"Downloading... {percent} | Speed: {speed} | ETA: {eta}",
                    chat_id, msg_id
                )
            except Exception:
                pass

def send_with_retry(bot_method, *args, max_retries=3, **kwargs):
    """Retry wrapper buat send methods yang timeout-prone."""
    for attempt in range(max_retries):
        try:
            return bot_method(*args, **kwargs)
        except Exception as e:
            if "TimeoutError" in str(e) or "Connection aborted" in str(e):
                print(f"[DEBUG] Send attempt {attempt+1} failed: {e}. Retrying in 5s...")
                if attempt < max_retries - 1:
                    time.sleep(5)
                else:
                    print(f"[DEBUG] All retries failed: {e}")
                    raise
            else:
                raise

# Existing: convert_to_sticker (sama)
def convert_to_sticker(filepath, is_video=False):
    if is_video:
        thumb_path = filepath.replace('.mp4', '_thumb.jpg')
        cmd = ['ffmpeg', '-i', filepath, '-vframes', '1', '-y', thumb_path]
        subprocess.run(cmd, capture_output=True, check=True)
        filepath = thumb_path
    
    with Image.open(filepath) as img:
        img = img.convert('RGBA')
        img.thumbnail((512, 512), Image.Resampling.LANCZOS)
        if img.size[0] != img.size[1]:
            size = min(img.size)
            left = (img.size[0] - size) // 2
            top = (img.size[1] - size) // 2
            img = img.crop((left, top, left + size, top + size))
        sticker_path = filepath.replace('.jpg', '.webp').replace('.png', '.webp')
        img.save(sticker_path, 'WEBP', quality=95)
        return sticker_path

# Existing: create_meme (sama)
def create_meme(filepath, top_text, bottom_text):
    with Image.open(filepath) as img:
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 40)
        except:
            font = ImageFont.load_default()
        
        if top_text:
            bbox = draw.textbbox((0, 0), top_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = (img.width - text_width) / 2
            y = 10
            draw.text((x, y), top_text.upper(), fill="white", font=font, stroke_width=2, stroke_fill="black")
        
        if bottom_text:
            bbox = draw.textbbox((0, 0), bottom_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = (img.width - text_width) / 2
            y = img.height - text_height - 10
            draw.text((x, y), bottom_text.upper(), fill="white", font=font, stroke_width=2, stroke_fill="black")
        
        meme_path = filepath.replace('.jpg', '_meme.jpg').replace('.png', '_meme.png')
        img.save(meme_path, 'JPEG', quality=95)
        return meme_path

@bot.message_handler(commands=['start'])
def start_message(message):
    bot.reply_to(message, 
        "Halo beb! Command simple per-platform GAS POL:\n"
        "/tiktok <link> - Download TikTok video/foto 📱\n"
        "/ig <link> - Instagram post/reel/carousel 📸\n"
        "/yt <link> - YouTube video/playlist 🎥\n"
        "/x <link> - Twitter/X video/thread 🐦\n"
        "/fb <link> - Facebook video/post 📱\n"
        "/reddit <link> - Reddit post/video 🐻\n"
        "/sticker <link> - Convert ke sticker 🔥\n"
        "/compress <link> - Kompres video 💨\n"
        "/music <query> - Cari lagu YouTube 🎵\n"
        "/playlist <link> - Playlist (max 5) 📂\n"
        "/slowmo <link> - Slow motion 🐌\n"
        "/meme <top> | <bottom> <link> - Bikin meme 😂\n"
        "/voice <link> - Voice note extract 🔊\n"
        "/batch <link1> <link2> ... (max 5)\n"
        "Kirim link biasa auto detect platform! Progress on! 🚀\n\nUpgrade: pip install --upgrade gallery-dl pillow yt-dlp")

# NEW: Platform-specific handlers
@bot.message_handler(commands=['tiktok'])
def handle_tiktok(message):
    if len(message.text.split()) < 2:
        bot.reply_to(message, "Gunakan: /tiktok <link>")
        return
    url = message.text.split(maxsplit=1)[1].strip()
    if not is_valid_url(url):
        bot.reply_to(message, "Link gak valid, beb!")
        return
    full_url = resolve_url(url)
    url_lower = full_url.lower()
    if "/photo/" in url_lower:
        bot.reply_to(message, "TikTok photo detected – gallery mode! 📸")
        download_with_gallery(message, full_url)
    else:
        download_with_progress(message, full_url)

@bot.message_handler(commands=['ig'])
def handle_ig(message):
    if len(message.text.split()) < 2:
        bot.reply_to(message, "Gunakan: /ig <link> (post/reel)")
        return
    url = message.text.split(maxsplit=1)[1].strip()
    if not is_valid_url(url):
        bot.reply_to(message, "Link gak valid, beb!")
        return
    full_url = resolve_url(url)
    download_with_progress(message, full_url)

@bot.message_handler(commands=['yt'])
def handle_yt(message):
    if len(message.text.split()) < 2:
        bot.reply_to(message, "Gunakan: /yt <link> (video/playlist)")
        return
    url = message.text.split(maxsplit=1)[1].strip()
    if not is_valid_url(url):
        bot.reply_to(message, "Link gak valid, beb!")
        return
    full_url = resolve_url(url)
    download_with_progress(message, full_url)

@bot.message_handler(commands=['x'])
def handle_x(message):
    if len(message.text.split()) < 2:
        bot.reply_to(message, "Gunakan: /x <link> (status/video)")
        return
    url = message.text.split(maxsplit=1)[1].strip()
    if not is_valid_url(url):
        bot.reply_to(message, "Link gak valid, beb!")
        return
    full_url = resolve_url(url)
    download_with_progress(message, full_url)

@bot.message_handler(commands=['fb'])
def handle_fb(message):
    if len(message.text.split()) < 2:
        bot.reply_to(message, "Gunakan: /fb <link> (video/post)")
        return
    url = message.text.split(maxsplit=1)[1].strip()
    if not is_valid_url(url):
        bot.reply_to(message, "Link gak valid, beb!")
        return
    full_url = resolve_url(url)
    download_with_progress(message, full_url)

@bot.message_handler(commands=['reddit'])
def handle_reddit(message):
    if len(message.text.split()) < 2:
        bot.reply_to(message, "Gunakan: /reddit <link> (post/video)")
        return
    url = message.text.split(maxsplit=1)[1].strip()
    if not is_valid_url(url):
        bot.reply_to(message, "Link gak valid, beb!")
        return
    full_url = resolve_url(url)
    download_with_progress(message, full_url)

@bot.message_handler(commands=['sticker'])
def handle_sticker(message):
    if len(message.text.split()) < 2:
        bot.reply_to(message, "Gunakan: /sticker <link>")
        return
    url = message.text.split(maxsplit=1)[1].strip()
    if not is_valid_url(url):
        bot.reply_to(message, "Link gak valid, beb!")
        return
    full_url = resolve_url(url)
    download_with_progress(message, full_url, sticker_only=True)

@bot.message_handler(commands=['compress'])
def handle_compress(message):
    if len(message.text.split()) < 2:
        bot.reply_to(message, "Gunakan: /compress <link>")
        return
    url = message.text.split(maxsplit=1)[1].strip()
    if not is_valid_url(url):
        bot.reply_to(message, "Link gak valid, beb!")
        return
    full_url = resolve_url(url)
    download_with_progress(message, full_url, compress_only=True)

@bot.message_handler(commands=['music'])
def handle_music(message):
    if len(message.text.split()) < 2:
        bot.reply_to(message, "Gunakan: /music <query>")
        return
    query = message.text.split(maxsplit=1)[1].strip()
    search_url = f"ytsearch1:{query}"
    bot.reply_to(message, f"Searching music: {query}... 🎵")
    download_with_progress(message, search_url, audio_only=True)

@bot.message_handler(commands=['playlist'])
def handle_playlist(message):
    if len(message.text.split()) < 2:
        bot.reply_to(message, "Gunakan: /playlist <link>")
        return
    url = message.text.split(maxsplit=1)[1].strip()
    if not is_valid_url(url):
        bot.reply_to(message, "Link gak valid, beb!")
        return
    full_url = resolve_url(url)
    download_with_progress(message, full_url, playlist_limit=5)

@bot.message_handler(commands=['slowmo'])
def handle_slowmo(message):
    if len(message.text.split()) < 2:
        bot.reply_to(message, "Gunakan: /slowmo <link>")
        return
    url = message.text.split(maxsplit=1)[1].strip()
    if not is_valid_url(url):
        bot.reply_to(message, "Link gak valid, beb!")
        return
    full_url = resolve_url(url)
    download_with_progress(message, full_url, slowmo_only=True)

@bot.message_handler(commands=['meme'])
def handle_meme(message):
    parts = message.text.split(maxsplit=3)
    if len(parts) < 4 or '|' not in parts[1]:
        bot.reply_to(message, "Gunakan: /meme <top> | <bottom> <link>")
        return
    top_text = parts[1].split('|')[0].strip()
    bottom_text = parts[2].split('|')[1].strip() if len(parts) > 2 and '|' in parts[2] else ''
    url = parts[3].strip()
    if not is_valid_url(url):
        bot.reply_to(message, "Link gak valid, beb!")
        return
    full_url = resolve_url(url)
    download_with_progress(message, full_url, meme_only=True, top_text=top_text, bottom_text=bottom_text)

@bot.message_handler(commands=['voice'])
def handle_voice(message):
    if len(message.text.split()) < 2:
        bot.reply_to(message, "Gunakan: /voice <link>")
        return
    url = message.text.split(maxsplit=1)[1].strip()
    if not is_valid_url(url):
        bot.reply_to(message, "Link gak valid, beb!")
        return
    full_url = resolve_url(url)
    download_with_progress(message, full_url, voice_only=True)

@bot.message_handler(commands=['batch'])
def handle_batch(message):
    parts = message.text.split(maxsplit=1)[1].split() if len(message.text.split()) > 1 else []
    parts = [p.strip() for p in parts if is_valid_url(p)]
    if len(parts) > 5:
        bot.reply_to(message, "Max 5 link aja beb!")
        return
    if not parts:
        bot.reply_to(message, "Gunakan: /batch <link1> <link2> ...")
        return
    bot.reply_to(message, f"Starting batch {len(parts)} items... ⏳")
    for i, url in enumerate(parts, 1):
        status_msg = bot.reply_to(message, f"Processing {i}/{len(parts)}: {url}")
        full_url = resolve_url(url)
        download_with_progress(message, full_url, status_msg=status_msg)
        time.sleep(2)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    url = message.text.strip()
    if not is_valid_url(url):
        bot.reply_to(message, "Kirim link valid ya! Contoh: https://www.tiktok.com/@user/video/123")
        return
    
    full_url = resolve_url(url)
    url_lower = full_url.lower()
    platform = get_platform(full_url)
    
    # Auto-route based on platform
    if "tiktok.com" in url_lower and "/photo/" in url_lower:
        bot.reply_to(message, f"Auto TikTok photo – gallery mode! 📸")
        download_with_gallery(message, full_url)
    else:
        plat_msg = f"Auto {platform.upper()} mode! ⏳"
        bot.reply_to(message, plat_msg)
        download_with_progress(message, full_url)

# FIXED: download_with_progress (check empty file + manual convert fallback + TikTok extractor fix)
def download_with_progress(message, url, audio_only=False, photo_only=False, sticker_only=False, compress_only=False, playlist_limit=None, slowmo_only=False, meme_only=False, top_text='', bottom_text='', voice_only=False, status_msg=None):
    chat_id = message.chat.id
    mode = 'Slowmo' if slowmo_only else 'Meme' if meme_only else 'Voice' if voice_only else ('Sticker' if sticker_only else 'Compress' if compress_only else ('Extracting audio' if audio_only else 'Grabbing photo' if photo_only else 'Sedang download'))
    with progress_lock:
        msg_id = status_msg.message_id if status_msg else None
        if not msg_id:
            init_msg = bot.reply_to(message, f"{mode}... 0% ⏳")
            msg_id = init_msg.message_id
        progress_messages[chat_id] = {'msg_id': msg_id, 'status': 'downloading'}
    
    def hooked_progress(d):
        progress_hook(d, chat_id, msg_id)
    
    try:
        ydl_opts = {
            'format': 'bestaudio/best' if audio_only or voice_only else 'best' if not (photo_only or sticker_only or meme_only) else 'bestimage',
            'outtmpl': '%(title)s.%(ext)s',
            'progress_hooks': [hooked_progress],
            'keepvideo': False,  # FIXED: Auto-hapus original setelah extract
            # FIXED for TikTok extraction
            'extractor_args': {
                'tiktok': {
                    'skip_mobile': False,
                    'player_skip': False
                }
            }
        }
        
        if playlist_limit:
            ydl_opts['playlistend'] = playlist_limit
        
        if audio_only or voice_only:
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3' if audio_only else 'libopus',
                'preferredquality': '192',
            }]
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            entries = info.get('entries', [info]) if info.get('entries') else [info]
            sent_count = 0
            for entry in entries or []:
                original_filename = ydl.prepare_filename(entry)
                print(f"[DEBUG] Original prepared filename: {original_filename}")
                print(f"[DEBUG] Entry ext after download: {entry.get('ext', 'N/A')}")
                
                # FIXED for audio: Cek .mp3 path post-extract
                audio_base = None
                if audio_only:
                    audio_base = original_filename.rsplit('.', 1)[0] if '.' in original_filename else original_filename
                    mp3_filename = audio_base + '.mp3'
                    print(f"[DEBUG] Checking MP3 path: {mp3_filename}")
                    if os.path.exists(mp3_filename):
                        filename = mp3_filename
                        print(f"[DEBUG] Using MP3: {filename}")
                    # Fallback ke original ext kalo gak ada .mp3
                    elif os.path.exists(original_filename):
                        filename = original_filename
                        print(f"[DEBUG] Fallback to original: {filename}")
                    else:
                        # Ultimate scan
                        title_pattern = re.escape(entry.get('title', '').replace(' ', '.*')) + '.*'
                        possible_files = glob.glob(f"*{title_pattern}*")
                        if possible_files:
                            filename = possible_files[0]
                            print(f"[DEBUG] Glob found: {filename}")
                        else:
                            print(f"[DEBUG] No file found via glob")
                            print(f"[DEBUG] Current dir: {os.listdir('.')}")
                            continue
                else:
                    filename = original_filename
                
                # FIXED: Cek exists & size (skip kalo empty)
                if os.path.exists(filename):
                    file_size = os.path.getsize(filename) / (1024 * 1024)
                    print(f"[DEBUG] File exists, size: {file_size:.1f}MB")
                    if file_size < 0.01:  # FIXED: Skip empty file (<10KB)
                        print(f"[DEBUG] File empty ({file_size:.1f}MB), skipping & deleting {filename}")
                        os.remove(filename)
                        continue
                else:
                    print(f"[DEBUG] File STILL NOT exists: {filename}")
                    print(f"[DEBUG] Current dir after scan: {os.listdir('.')}")
                    continue
                
                caption = f"{entry.get('title', 'Unknown')[:100]}... from: {url}"
                try:
                    if audio_only and not filename.endswith('.mp3') and audio_base:
                        # FIXED: Manual convert kalo mp3 gak ada/gagal
                        try:
                            print(f"[DEBUG] Manual converting {filename} to MP3...")
                            mp3_filename = audio_base + '.mp3'
                            cmd = ['ffmpeg', '-i', filename, '-vn', '-ar', '44100', '-ac', '2', '-b:a', '192k', '-y', mp3_filename]
                            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                            if result.returncode == 0 and os.path.exists(mp3_filename) and os.path.getsize(mp3_filename) > 10000:  # >10KB
                                filename = mp3_filename
                                file_size = os.path.getsize(filename) / (1024 * 1024)
                                print(f"[DEBUG] Manual convert success: {filename} ({file_size:.1f}MB)")
                            else:
                                print(f"[DEBUG] Manual convert failed: {result.stderr[:100]}")
                                os.remove(filename) if os.path.exists(filename) else None
                                continue
                        except Exception as conv_e:
                            print(f"[DEBUG] Convert error: {conv_e}")
                            continue
                    
                    if slowmo_only and filename.lower().endswith(('.mp4', '.mkv', '.webm')):
                        slowmo_path = filename.replace('.mp4', '_slowmo.mp4')
                        cmd = ['ffmpeg', '-i', filename, '-filter:v', 'setpts=2.0*PTS', '-filter:a', 'atempo=0.5', '-y', slowmo_path]
                        subprocess.run(cmd, capture_output=True, check=True)
                        filename = slowmo_path
                        file_size = os.path.getsize(filename) / (1024 * 1024)
                    
                    if meme_only and filename.lower().endswith(('.jpg', '.png', '.webp')):
                        meme_path = create_meme(filename, top_text, bottom_text)
                        with open(meme_path, 'rb') as meme:
                            send_with_retry(bot.send_photo if file_size <= 10 else bot.send_document, chat_id, meme, caption=caption + " 😂 Meme Mode!")
                        os.remove(meme_path)
                        os.remove(filename)
                        sent_count += 1
                        continue
                    
                    if voice_only and filename.endswith('.mp3'):
                        voice_path = filename.replace('.mp3', '.ogg')
                        cmd = ['ffmpeg', '-i', filename, '-c:a', 'libopus', '-b:a', '64k', '-y', voice_path]
                        subprocess.run(cmd, capture_output=True, check=True)
                        with open(voice_path, 'rb') as voice:
                            send_with_retry(bot.send_voice, chat_id, voice, caption=caption + " 🔊 Voice Note!")
                        os.remove(voice_path)
                        os.remove(filename)
                        sent_count += 1
                        continue
                    
                    if sticker_only:
                        sticker_path = convert_to_sticker(filename, filename.lower().endswith(('.mp4', '.webm', '.mkv')))
                        with open(sticker_path, 'rb') as sticker:
                            send_with_retry(bot.send_sticker, chat_id, sticker, caption=caption)
                        os.remove(sticker_path)
                        if filename.lower().endswith(('.mp4', '.webm', '.mkv')):
                            os.remove(filename)
                        sent_count += 1
                        continue
                    
                    if compress_only and filename.lower().endswith(('.mp4', '.mkv', '.webm')):
                        compressed_path = filename.replace('.mp4', '_compressed.mp4')
                        cmd = ['ffmpeg', '-i', filename, '-vcodec', 'libx264', '-crf', '28', '-preset', 'fast', '-vf', 'scale=1280:720', '-y', compressed_path]
                        subprocess.run(cmd, capture_output=True, check=True)
                        filename = compressed_path
                        file_size = os.path.getsize(filename) / (1024 * 1024)
                    
                    # FIXED audio send: Check size lagi sebelum send
                    if audio_only:
                        if file_size < 0.01:  # Double-check
                            print(f"[DEBUG] Audio file still empty after fallback, skipping")
                            os.remove(filename)
                            continue
                        print(f"[DEBUG] Sending audio: {filename} ({file_size:.1f}MB)")
                        if filename.endswith('.mp3'):
                            if file_size > 50:
                                send_with_retry(bot.send_document, chat_id, open(filename, 'rb'), caption=caption)
                            else:
                                send_with_retry(bot.send_audio, chat_id, open(filename, 'rb'), caption=caption)
                        else:
                            send_with_retry(bot.send_document, chat_id, open(filename, 'rb'), caption=caption + " (Audio fallback)")
                        sent_count += 1
                        os.remove(filename)
                        continue
                    
                    # Sisanya sama, pake retry
                    elif photo_only and filename.lower().endswith(('.jpg', '.png', '.webp')):
                        with open(filename, 'rb') as photo:
                            send_with_retry(bot.send_photo if file_size <= 10 else bot.send_document, chat_id, photo, caption=caption)
                    elif slowmo_only or compress_only or (not photo_only and not audio_only and filename.lower().endswith(('.mp4', '.mkv', '.webm'))):
                        if file_size > 50:
                            send_with_retry(bot.send_document, chat_id, open(filename, 'rb'), caption=caption + f" ({'Slowmo' if slowmo_only else 'Compressed'}: {file_size:.1f}MB)")
                        else:
                            with open(filename, 'rb') as video:
                                send_with_retry(bot.send_video, chat_id, video, caption=caption + f" ({'Slowmo' if slowmo_only else 'Compressed'}: {file_size:.1f}MB)")
                    else:
                        send_with_retry(bot.send_document, chat_id, open(filename, 'rb'), caption=caption)
                    sent_count += 1
                    os.remove(filename)
                    if slowmo_only and '_slowmo' in filename:
                        os.remove(filename)
                    if compress_only and '_compressed' in filename:
                        os.remove(filename)
                except Exception as send_e:
                    print(f"[DEBUG] Send error for {filename}: {send_e}")
                    bot.reply_to(message, f"Failed to send {filename}: {str(send_e)[:100]}")
            
            if sent_count > 0:
                status = f"Batch complete! Sent {sent_count} files. 🎉" if len(entries) > 1 else "Download selesai! 🎉"
                if sticker_only:
                    status = f"Sticker ready! Sent {sent_count} stickers. 🔥"
                elif compress_only:
                    status = f"Compressed & sent! {sent_count} files ready. 💨"
                elif playlist_limit:
                    status = f"Playlist done! Sent first {sent_count} tracks. 📂"
                elif audio_only and 'ytsearch' in url:
                    status = f"Music sent! 🎵 ({sent_count} tracks)"
                elif slowmo_only:
                    status = f"Slowmo magic! Sent {sent_count} clips. 🐌"
                elif meme_only:
                    status = f"Meme created! Laugh out loud 😂"
                elif voice_only:
                    status = f"Voice note ready! 🔊"
            else:
                status = "Download ok, but no valid file (empty?). Cek log. 😅"
            bot.edit_message_text(status, chat_id, msg_id)
    
    except yt_dlp.DownloadError as e:
        error_msg = str(e).splitlines()[0]
        url_lower = url.lower()
        if "unsupported url" in error_msg.lower() and "tiktok.com" in url_lower:
            error_msg = "TikTok unsupported di yt-dlp. Coba /tiktok buat auto! 📸"
        elif (photo_only or meme_only) and "format" in error_msg.lower():
            error_msg += " (Coba link image valid)"
        elif (audio_only or voice_only) and "FFmpeg" in error_msg:
            error_msg += " (Install FFmpeg: pkg install ffmpeg)"
        elif audio_only or voice_only:
            error_msg += " (FFmpeg missing? pkg install ffmpeg)"
        bot.edit_message_text(f"Download error: {error_msg}", chat_id, msg_id)
    except Exception as e:
        print(f"[DEBUG] Unexpected error: {e}")
        bot.edit_message_text(f"Unexpected error: {str(e)[:100]}. Coba link lain!", chat_id, msg_id)
    finally:
        with progress_lock:
            progress_messages.pop(chat_id, None)

# Keep download_with_gallery (sama, buat TikTok photo)
def download_with_gallery(message, url):
    chat_id = message.chat.id
    init_msg = bot.reply_to(message, "Grabbing with gallery-dl... ⏳")
    print(f"[DEBUG] Starting gallery-dl for URL: {url}")
    
    try:
        subprocess.run(['gallery-dl', '--version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        bot.edit_message_text("Error: Install gallery-dl: pip install --upgrade gallery-dl", chat_id, init_msg.message_id)
        return
    
    try:
        temp_dir = f"temp_gallery_{int(time.time())}"
        os.makedirs(temp_dir, exist_ok=True)
        
        cmd = ['gallery-dl', '-D', temp_dir, url]
        print(f"[DEBUG] Running cmd: {' '.join(cmd)}")
        
        success = False
        for attempt in range(2):
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode == 0:
                    success = True
                    break
                else:
                    print(f"[DEBUG] Attempt {attempt+1} failed: {result.stderr[:200]}")
            except subprocess.TimeoutExpired:
                print(f"[DEBUG] Attempt {attempt+1} timeout")
                if attempt == 1:
                    raise
                time.sleep(5)
        
        if not success:
            bot.edit_message_text(f"Gallery-dl failed: {result.stderr[:200]}.", chat_id, init_msg.message_id)
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            return
        
        files = [f for f in os.listdir(temp_dir) if f.lower().endswith(('.jpg', '.png', '.webp'))]
        print(f"[DEBUG] Found {len(files)} files in {temp_dir}")
        if not files:
            bot.edit_message_text("No photos found! Update gallery-dl.", chat_id, init_msg.message_id)
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
            return
        
        sent_count = 0
        for file in files:
            filepath = os.path.join(temp_dir, file)
            try:
                file_size = os.path.getsize(filepath) / (1024 * 1024)
                if file_size < 0.01:  # FIXED: Skip empty images
                    print(f"[DEBUG] Empty image {file}, skipping")
                    continue
                with open(filepath, 'rb') as photo:
                    send_with_retry(bot.send_photo if file_size <= 10 else bot.send_document, chat_id, photo, caption=f"Photo from: {url}")
                sent_count += 1
                time.sleep(1)
            except Exception as send_e:
                bot.reply_to(message, f"Failed to send {file}: {str(send_e)[:100]}")
        
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
        
        status = f"Gallery complete! Sent {sent_count} photos. 📸"
        bot.edit_message_text(status, chat_id, init_msg.message_id)
    
    except subprocess.TimeoutExpired:
        bot.edit_message_text("Timeout! Link lambat.", chat_id, init_msg.message_id)
    except Exception as e:
        print(f"[DEBUG] Gallery exception: {e}")
        bot.edit_message_text(f"Error: {str(e)[:100]}. Manual: gallery-dl '{url}'", chat_id, init_msg.message_id)

# Setup & polling (sama)
try:
    bot.delete_webhook()
    print("Webhook deleted!")
except Exception as e:
    print(f"Warning: {e}")

try:
    updates = bot.get_updates(offset=-1, limit=50)
    print(f"Dropped {len(updates)} pending updates.")
except Exception as e:
    print(f"Warning: {e}")

def run_polling():
    retry_delay = 5
    while True:
        try:
            print("Starting polling...")
            bot.polling(none_stop=True, interval=1, timeout=20, long_polling_timeout=20)
        except Exception as e:
            print(f"Polling error: {e}. Restarting in {retry_delay}s...")
            time.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)
            if "ConnectionError" in str(e) or "RemoteDisconnected" in str(e):
                print("Network issue – cek koneksi lo!")

if __name__ == '__main__':
    print("Bot SIMPLE CMD Edition! 🔥 /tiktok /ig /yt ready – Gampang abis bro!")
    run_polling()