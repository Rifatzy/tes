import logging
import os
import json
import asyncio
import aiohttp
import aiofiles
import subprocess
import tempfile
import shutil
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.error import TelegramError

# ===== KONFIGURASI =====
TELEGRAM_TOKEN = "8331427771:AAGjs1obYWjtw4j4k-B-GgfO6E0W28pnJ4g"
HF_API_KEY = "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"
HF_API_URL = "https://api-inference.huggingface.co/models"

# Model yang PASTI tersedia
VIDEO_MODELS = [
    "damo-vilab/modelscope-text-to-video-synthesis",  # Model alternatif
]

# Model image generation (fallback)
IMAGE_MODELS = [
    "stabilityai/stable-diffusion-2-1",
    "runwayml/stable-diffusion-v1-5",
    "CompVis/stable-diffusion-v1-4"
]

# Konfigurasi
RESIZE_WIDTH = 512
RESIZE_HEIGHT = 384
MAX_SCENES = 2
MAX_CONCURRENT_REQUESTS = 1
TEMP_DIR = tempfile.mkdtemp()

# ===== LOGGING =====
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ===== FUNGSI PEMBANTU =====
def check_dependencies():
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("✅ FFmpeg ditemukan.")
            return True
        else:
            logger.error("❌ FFmpeg error.")
            return False
    except FileNotFoundError:
        logger.error("❌ FFmpeg tidak ditemukan.")
        return False

def cleanup():
    try:
        shutil.rmtree(TEMP_DIR)
        logger.info("✅ Temporary directory cleaned up")
    except Exception as e:
        logger.error(f"Cleanup error: {e}")

# ===== FUNGSI CARI MODEL YANG WORKING =====
async def find_working_models(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cari model yang benar-benar working."""
    await update.message.reply_text("🔍 Searching for working models...")
    
    headers = {
        "Authorization": f"Bearer {HF_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Test video models
    video_results = []
    async with aiohttp.ClientSession() as session:
        for model in VIDEO_MODELS:
            api_url = f"{HF_API_URL}/{model}"
            payload = {"inputs": "cat"}
            
            try:
                async with session.post(api_url, json=payload, headers=headers, timeout=30) as resp:
                    if resp.status == 200:
                        video_results.append(f"✅ {model} - WORKING")
                    else:
                        video_results.append(f"❌ {model} - Error {resp.status}")
            except Exception as e:
                video_results.append(f"❌ {model} - {str(e)[:30]}")
    
    # Test image models
    image_results = []
    async with aiohttp.ClientSession() as session:
        for model in IMAGE_MODELS[:2]:  # Test 2 models saja
            api_url = f"{HF_API_URL}/{model}"
            payload = {"inputs": "clay cat"}
            
            try:
                async with session.post(api_url, json=payload, headers=headers, timeout=30) as resp:
                    if resp.status == 200:
                        image_results.append(f"✅ {model} - WORKING")
                    else:
                        image_results.append(f"❌ {model} - Error {resp.status}")
            except Exception as e:
                image_results.append(f"❌ {model} - {str(e)[:30]}")
    
    message = "📊 Model Status:\n\n"
    message += "🎬 Video Models:\n" + "\n".join(video_results) + "\n\n"
    message += "🖼️ Image Models (Fallback):\n" + "\n".join(image_results)
    
    await update.message.reply_text(message)

# ===== FUNGSI GENERATE IMAGE SLIDESHOW =====
async def generate_image_slideshow(session, idx, scene, semaphore):
    """Generate image dan buat slideshow."""
    async with semaphore:
        base_text = scene.get("text", "clay figure").strip()
        duration = scene.get("duration", 3)
        
        # Prompt untuk image
        prompt = f"claymation of {base_text}, cute, 3D, soft lighting"
        if len(prompt) > 50:
            prompt = f"claymation {base_text}"
        
        logger.info(f"Scene {idx+1}: Generating image '{prompt}'")
        
        # Coba semua image models
        for model in IMAGE_MODELS:
            api_url = f"{HF_API_URL}/{model}"
            payload = {"inputs": prompt}
            headers = {
                "Authorization": f"Bearer {HF_API_KEY}",
                "Content-Type": "application/json"
            }
            
            try:
                async with session.post(api_url, json=payload, headers=headers, timeout=60) as resp:
                    if resp.status == 200:
                        # Handle image response
                        content_type = resp.headers.get('content-type', '')
                        
                        if 'image' in content_type:
                            # Direct image response
                            image_bytes = await resp.read()
                        else:
                            # JSON response with base64
                            result = await resp.json()
                            if isinstance(result, list) and len(result) > 0:
                                import base64
                                image_data = result[0]
                                if isinstance(image_data, str):
                                    image_bytes = base64.b64decode(image_data)
                                else:
                                    continue
                            else:
                                continue
                        
                        # Simpan image
                        img_path = os.path.join(TEMP_DIR, f"scene_{idx+1}.png")
                        async with aiofiles.open(img_path, "wb") as f:
                            await f.write(image_bytes)
                        
                        # Buat video dari image (slideshow)
                        video_path = os.path.join(TEMP_DIR, f"scene_{idx+1}.mp4")
                        cmd = [
                            "ffmpeg", "-y",
                            "-loop", "1",
                            "-i", img_path,
                            "-t", str(duration),
                            "-vf", f"scale={RESIZE_WIDTH}:{RESIZE_HEIGHT}",
                            "-c:v", "libx264",
                            "-pix_fmt", "yuv420p",
                            video_path
                        ]
                        
                        result = subprocess.run(cmd, capture_output=True, text=True)
                        if result.returncode == 0:
                            os.remove(img_path)
                            logger.info(f"Scene {idx+1}: Success with image slideshow")
                            return video_path, f"✅ Scene {idx+1}: {base_text} (image slideshow)"
                        else:
                            logger.error(f"FFmpeg error: {result.stderr}")
                            os.remove(img_path)
                            continue
                    else:
                        continue
                        
            except Exception as e:
                logger.error(f"Error with {model}: {e}")
                continue
        
        return None, f"❌ Scene {idx+1}: All models failed"

# ===== FUNGSI GENERATE VIDEO =====
async def generate_video_or_slideshow(session, idx, scene, semaphore):
    """Coba video dulu, fallback ke image slideshow."""
    async with semaphore:
        base_text = scene.get("text", "clay figure").strip()
        
        # Coba video models dulu
        for model in VIDEO_MODELS:
            api_url = f"{HF_API_URL}/{model}"
            payload = {"inputs": f"claymation of {base_text}"}
            headers = {
                "Authorization": f"Bearer {HF_API_KEY}",
                "Content-Type": "application/json"
            }
            
            try:
                async with session.post(api_url, json=payload, headers=headers, timeout=120) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        
                        if isinstance(result, list) and len(result) > 0:
                            video_data = result[0]
                            
                            if isinstance(video_data, dict) and "url" in video_data:
                                video_url = video_data["url"]
                                async with session.get(video_url, timeout=60) as vresp:
                                    if vresp.status == 200:
                                        video_bytes = await vresp.read()
                                        path = os.path.join(TEMP_DIR, f"scene_{idx+1}.mp4")
                                        async with aiofiles.open(path, "wb") as f:
                                            await f.write(video_bytes)
                                        
                                        if os.path.getsize(path) > 1000:
                                            return path, f"✅ Scene {idx+1}: {base_text} (video)"
                                        else:
                                            os.remove(path)
                                            continue
            except Exception as e:
                logger.error(f"Video model {model} failed: {e}")
                continue
        
        # Jika video gagal, fallback ke image slideshow
        logger.info(f"Scene {idx+1}: Video failed, trying image slideshow")
        return await generate_image_slideshow(session, idx, scene, semaphore)

# ===== FUNGSI BOT =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 **Clay Animation Bot v4**\n\n"
        "Commands:\n"
        "/start - Show help\n"
        "/findmodels - Find working models\n\n"
        "Kirim JSON:\n"
        "```json\n"
        "{\n"
        "  \"scenes\": [\n"
        "    {\"text\": \"cat\", \"duration\": 3}\n"
        "  ]\n"
        "}\n"
        "```\n\n"
        "📌 Bot akan coba video dulu,\n"
        "   jika gagal pakai image slideshow"
    )

async def handle_json(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text.strip()
    
    try:
        json_data = json.loads(user_text)
        scenes = json_data.get("scenes", [])
        
        if not scenes:
            raise ValueError("Perlu array 'scenes'")
        if len(scenes) > MAX_SCENES:
            raise ValueError(f"Maksimal {MAX_SCENES} scene")
            
        for i, scene in enumerate(scenes):
            text = scene.get("text", "").strip()
            if not text:
                raise ValueError(f"Scene {i+1}: Text tidak boleh kosong")
            if len(text) > 15:
                raise ValueError(f"Scene {i+1}: Text max 15 karakter")
                
    except json.JSONDecodeError:
        await update.message.reply_text("❌ JSON tidak valid")
        return
    except ValueError as e:
        await update.message.reply_text(f"❌ {str(e)}")
        return

    progress = await update.message.reply_text("🎨 Processing... Mohon tunggu")
    
    scene_paths = []
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    async with aiohttp.ClientSession() as session:
        tasks = [generate_video_or_slideshow(session, idx, scene, semaphore) for idx, scene in enumerate(scenes)]
        
        for coro in asyncio.as_completed(tasks):
            path, msg = await coro
            await progress.edit_text(f"⏳ {msg}")
            if path:
                scene_paths.append(path)

    if not scene_paths:
        await progress.edit_text(
            "❌ Gagal membuat video.\n\n"
            "💡 Tips:\n"
            "1. Ketik /findmodels untuk cek model\n"
            "2. Gunakan kata sangat sederhana\n"
            "3. Coba 'cat' atau 'dog'"
        )
        return

    try:
        await progress.edit_text("🔗 Menggabungkan video...")
        
        # Urutkan scene
        scene_paths.sort(key=lambda x: int(x.split('_')[1].split('.')[0]))
        
        # Buat file list
        list_file = os.path.join(TEMP_DIR, "videos.txt")
        with open(list_file, "w") as f:
            for p in scene_paths:
                f.write(f"file '{p}'\n")

        # Gabungkan video
        final_path = os.path.join(TEMP_DIR, "final.mp4")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", 
            "-i", list_file, "-c", "copy", final_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            raise Exception("Gagal menggabungkan video")

        # Kirim video
        with open(final_path, "rb") as video_file:
            await update.message.reply_video(
                video=video_file,
                caption="✅ Clay animation ready!"
            )
        
        await progress.edit_text("✅ Selesai!")
        
        # Cleanup
        for p in scene_paths:
            try:
                os.remove(p)
            except:
                pass
        os.remove(list_file)
        os.remove(final_path)
        
    except Exception as e:
        logger.error(f"Final error: {str(e)}")
        await progress.edit_text(f"❌ Error: {str(e)}")

# ===== MAIN =====
def main():
    print("=" * 50)
    print("🤖 Clay Animation Bot v4 - Smart Fallback")
    print("=" * 50)
    print("📍 Strategy: Video → Image Slideshow")
    print("📍 Image Models: 3 available")
    print("📍 Video Models: 1 available")
    print("=" * 50)
    
    if not check_dependencies():
        print("❌ Install FFmpeg first!")
        return
    
    print("✅ All dependencies OK")
    print("🚀 Starting bot...")
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("findmodels", find_working_models))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_json))
    
    try:
        app.run_polling()
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped.")
    finally:
        cleanup()

if __name__ == "__main__":
    main()