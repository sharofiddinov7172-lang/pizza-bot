import os
import sys
import threading
import subprocess
import re
import atexit
import time
import sqlite3
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo, MenuButtonWebApp

# ==========================================
# SOZLAMALAR (SIZNING MA'LUMOTLARINGIZ)
# ==========================================
BOT_TOKEN = "8882834267:AAEDMNbJMryHKxGqlnB9DRpfEq5TFvCayyA"
ADMIN_ID = 8126690617
PORT = int(os.environ.get("PORT", 80))

# WebApp havolasi (Render serveri avtomatik o'zining RENDER_EXTERNAL_URL manzilini beradi)
WEBAPP_URL = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("WEBAPP_URL", "")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__, static_folder="frontend")
CORS(app)

# Mahsulotlar ro'yxati
PRODUCTS = [
    {
        "id": 1,
        "title": "Peperoni",
        "category": "Pitsa",
        "oldPrice": 65000,
        "newPrice": 55000,
        "image": "https://images.unsplash.com/photo-1628840042765-356cda07504e?w=500&q=80",
        "description": "Achchiq mol go'shti kolbasasi, maxsus pomidor sousi va cho'ziluvchan mozarella pishlog'i."
    },
    {
        "id": 2,
        "title": "Margarita",
        "category": "Pitsa",
        "oldPrice": 50000,
        "newPrice": 42000,
        "image": "https://images.unsplash.com/photo-1574071318508-1cdbab80d002?w=500&q=80",
        "description": "Klassik italyancha pitsa: yangi pomidorlar, barra rayhon va ko'p miqdorda mozarella."
    },
    {
        "id": 3,
        "title": "Kombat 4 Pishloq",
        "category": "Pitsa",
        "oldPrice": 75000,
        "newPrice": 68000,
        "image": "https://images.unsplash.com/photo-1513104890138-7c749659a591?w=500&q=80",
        "description": "Haqiqiy pishloq shaydolari uchun: Mozarella, Parmezan, Gorgonzola va Dor-blyu uyg'unligi."
    },
    {
        "id": 4,
        "title": "Qarsildoq Fri",
        "category": "Gazaklar",
        "oldPrice": 20000,
        "newPrice": 16000,
        "image": "https://images.unsplash.com/photo-1576107232684-1279f3908594?w=500&q=80",
        "description": "Tilla rangda qovurilgan qarsildoq kartoshka fri, maxsus sous bilan."
    },
    {
        "id": 5,
        "title": "Koka-Kola 0.5L",
        "category": "Ichimliklar",
        "oldPrice": 8000,
        "newPrice": 6000,
        "image": "https://images.unsplash.com/photo-1622483767028-3f66f32aef97?w=500&q=80",
        "description": "Muzdek, tetiklashtiruvchi klassik Koka-Kola."
    }
]

# ==========================================
# MA'LUMOTLAR BAZASI (SQLite)
# ==========================================
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orders.db")

def init_db():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                customer_name TEXT,
                phone TEXT,
                items TEXT,
                total_sum REAL,
                location TEXT,
                lat REAL,
                lon REAL,
                payment_type TEXT,
                status TEXT DEFAULT 'kutilmoqda',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Baza yaratishda xatolik: {e}")

init_db()

# ----------------- FLASK YO'NALISHLARI -----------------

@app.route('/')
def serve_index():
    return send_from_directory('frontend', 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory('frontend', path)

@app.route('/api/products', methods=['GET'])
def get_products():
    return jsonify(PRODUCTS)

@app.route('/api/orders', methods=['GET'])
def get_orders():
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, telegram_id, customer_name, phone, items, total_sum, location, payment_type, status, created_at FROM orders ORDER BY id DESC LIMIT 50")
        rows = cursor.fetchall()
        conn.close()
        orders = []
        for r in rows:
            orders.append({
                "id": r[0],
                "telegramId": r[1],
                "customerName": r[2],
                "phone": r[3],
                "items": json.loads(r[4]) if r[4] else [],
                "totalSum": r[5],
                "location": r[6],
                "paymentType": r[7],
                "status": r[8],
                "createdAt": r[9]
            })
        return jsonify(orders)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/orders', methods=['POST'])
def create_order():
    data = request.json or {}
    telegram_id = data.get('telegramId')
    customer_name = data.get('name', 'Mijoz')
    phone = data.get('phone', "Kiritilmagan")
    items = data.get('items', [])
    total_sum = data.get('totalSum', 0)
    location = data.get('location', "Ko'rsatilmagan")
    coords = data.get('coords') or {}
    payment_type = data.get('paymentType', 'Naqd')

    lat = coords.get('lat') if isinstance(coords, dict) else None
    lon = coords.get('lon') if isinstance(coords, dict) else None

    # 1. Bazaga saqlash
    order_id = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO orders (telegram_id, customer_name, phone, items, total_sum, location, lat, lon, payment_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (telegram_id, customer_name, phone, json.dumps(items, ensure_ascii=False), total_sum, location, lat, lon, payment_type))
        order_id = cursor.lastrowid
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Bazaga yozishda xatolik: {e}")

    # 2. Adminga xabar matnini tayyorlash
    order_num = f"#{order_id}" if order_id else ""
    payment_icon = "💵" if payment_type == "Naqd" else "💳"
    
    admin_msg = f"🛒 <b>YANGI BUYURTMA {order_num}!</b>\n\n"
    admin_msg += f"👤 <b>Mijoz:</b> {customer_name} (ID: <code>{telegram_id}</code>)\n"
    admin_msg += f"📞 <b>Telefon:</b> {phone}\n"
    admin_msg += f"📍 <b>Manzil:</b> {location}\n"
    admin_msg += f"💳 <b>To'lov turi:</b> {payment_icon} <b>{payment_type}</b>\n"
    admin_msg += f"⏰ <b>Vaqti:</b> Hozir\n\n"
    admin_msg += "📦 <b>Buyurtma tarkibi:</b>\n"
    
    for i, item in enumerate(items, 1):
        admin_msg += f"{i}. <b>{item.get('title')}</b> — {item.get('qty')} dona x {item.get('newPrice', 0):,} so'm\n"

    admin_msg += f"\n💰 <b>JAMI TO'LOV:</b> <u>{total_sum:,} so'm</u>"

    # Adminga xabar va lokatsiyani yuborish
    try:
        bot.send_message(ADMIN_ID, admin_msg)
        # Agar GPS koordinatalari mavjud bo'lsa, xaritadagi pinni ham yuboramiz
        if lat and lon:
            try:
                bot.send_location(ADMIN_ID, latitude=lat, longitude=lon)
            except Exception as loc_e:
                print(f"Lokatsiya pinini yuborishda xatolik: {loc_e}")
    except Exception as e:
        print(f"Adminga xabar yuborishda xatolik: {e}")

    # Mijozga tasdiq xabarini yuborish
    try:
        if telegram_id:
            client_msg = (
                f"✅ <b>Buyurtmangiz muvaffaqiyatli qabul qilindi! 🍕</b>\n\n"
                f"📍 <b>Yetkazish manzili:</b> {location}\n"
                f"💳 <b>To'lov turi:</b> {payment_icon} {payment_type}\n"
                f"💰 <b>Jami summa:</b> {total_sum:,} so'm\n\n"
                f"🛵 Kuryerimiz tez orada siz bilan bog'lanadi!"
            )
            bot.send_message(telegram_id, client_msg)
    except Exception as e:
        print(f"Mijozga xabar yuborishda xatolik: {e}")

    return jsonify({"status": "success", "orderId": order_id, "message": "Buyurtma qabul qilindi"})


# ----------------- TELEGRAM BOT BUYRUQLARI -----------------

@bot.message_handler(commands=['start'])
def handle_start(message):
    first_name = message.from_user.first_name or "Hurmatli mijoz"
    
    text = (
        f"Assalomu alaykum, <b>{first_name}</b>! 🍕\n\n"
        f"Bizning pitsaxonamizga xush kelibsiz! "
        f"Pastdagi <b>«🍕 Pitsa buyurtma qilish»</b> tugmasini bosib, "
        f"mazali va issiq pitsalarni to'g'ridan-to'g'ri Telegram ichida tanlang va buyurtma bering!"
    )
    
    markup = InlineKeyboardMarkup()
    if WEBAPP_URL and WEBAPP_URL.startswith("https://"):
        # Telegram Mini App (TMA) faqat HTTPS bo'lganda ochiladi
        markup.add(InlineKeyboardButton("🍕 Pitsa buyurtma qilish", web_app=WebAppInfo(url=WEBAPP_URL)))
        try:
            bot.send_message(message.chat.id, text, reply_markup=markup)
        except Exception as e:
            print(f"Xabar yuborishda xatolik: {e}")
    else:
        # Telegram Bot API 'localhost' ni inline tugmaga qo'yishni taqiqlaydi (Wrong HTTP URL xatosi bermasligi uchun)
        info_text = (
            f"{text}\n\n"
            f"⚠️ <b>Diqqat:</b> Telegram ilovasi faqat <b>HTTPS</b> havolalarni qabul qiladi.\n"
            f"Lokal test uchun havolani brauzerda oching: {WEBAPP_URL}\n\n"
            f"Telegram ichida ochish uchun <code>start_tunnel.bat</code> faylini ishga tushirib, "
            f"olingan <b>https://...</b> havolani server.py ga qo'ying."
        )
        try:
            bot.send_message(message.chat.id, info_text)
        except Exception as e:
            print(f"Xabar yuborishda xatolik: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "no_url")
def handle_no_url(call):
    bot.answer_callback_query(
        call.id,
        "⚠️ Administrator hali WebApp havolasini o'rnatmadi.",
        show_alert=True
    )


def run_flask():
    print(f"🚀 Veb-server {PORT}-portda ishga tushmoqda (http://localhost:{PORT})...")
    try:
        app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
    except PermissionError:
        print(f"⚠️ 80-port uchun administrator huquqi kerak bo'lishi mumkin yoki boshqa dastur band qilgan. 5000-portga o'tilmoqda...")
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)

def update_menu_button(url):
    try:
        if url.startswith("https://"):
            bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="🍕 Buyurtma", web_app=WebAppInfo(url=url)))
            print(f"✅ Botning pastki 'Menu' tugmasi avtomatik {url} ga sozlandi!")
        else:
            print("ℹ️ Eslatma: Telegram pastki 'Menu' tugmasiga faqat HTTPS havolalarni qo'yishga ruxsat beradi.")
    except Exception as e:
        print(f"Menu tugmasini sozlashda xatolik: {e}")

def start_cloudflared(port):
    global WEBAPP_URL
    cloudflared_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloudflared.exe")
    if not os.path.exists(cloudflared_path):
        return None
    
    print("🌐 Cloudflare Tunnel orqali bepul va uzluksiz HTTPS havola olinmoqda...")
    try:
        proc = subprocess.Popen(
            [cloudflared_path, 'tunnel', '--url', f'http://127.0.0.1:{port}'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        atexit.register(lambda: proc.terminate())
        
        start_time = time.time()
        while time.time() - start_time < 20:
            line = proc.stderr.readline()
            if not line:
                time.sleep(0.1)
                continue
            m = re.search(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com', line)
            if m:
                url = m.group(0)
                print(f"✨ Bepul va barqaror HTTPS havola olindi: {url}")
                return url
    except Exception as e:
        print(f"Cloudflare tunnel xatoligi: {e}")
    return None

if __name__ == '__main__':
    print("=" * 50)
    print("🍕 PIZZA BOT & WEBAPP SERVER ISHGA TUSHMOQDA...")
    print(f"🤖 Bot Token: {BOT_TOKEN[:10]}... (faol)")
    print(f"👤 Admin ID: {ADMIN_ID}")
    print("=" * 50)

    # 1. Flask serverni alohida oqimda ishga tushirish
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    time.sleep(1)

    # 2. Agar WEBAPP_URL belgilanmagan bo'lsa va lokal kompyuter bo'lsa, Cloudflare tunnel ishlatish
    if not WEBAPP_URL and os.name == 'nt':
        tunnel_url = start_cloudflared(PORT)
        if tunnel_url:
            WEBAPP_URL = tunnel_url

    if WEBAPP_URL:
        print(f"🌐 WebApp URL: {WEBAPP_URL}")
        update_menu_button(WEBAPP_URL)

    print("🤖 Telegram Bot xabarlarni tinglamoqda (Polling)...")
    try:
        bot.infinity_polling(skip_pending=True)
    except (KeyboardInterrupt, SystemExit):
        print("\nTo'xtatildi.")
