import os
import sqlite3
import logging

from flask import Flask, request, jsonify
from datetime import datetime
from dotenv import load_dotenv
from telebot import types, apihelper

apihelper.ENABLE_MIDDLEWARE = True

# --- CONFIGURAÇÃO E INFRA ---
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN", "")
raw_allowed = os.getenv("ALLOWED_USERS", "")
ALLOWED_USERS = [int(u.strip()) for u in raw_allowed.split(",") if u.strip()]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.getenv("DB_PATH", os.path.join(BASE_DIR, "database", "compras.db"))

import telebot
bot = telebot.TeleBot(TOKEN)

# Inicializa Flask
app = Flask(__name__)
app.logger.setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# Flag para evitar múltiplas inicializações
_webhook_initialized = False


# --- MIDDLEWARE DE SEGURANÇA ---
@bot.middleware_handler(update_types=['message', 'callback_query'])
def restrict_access(bot_instance, update):
    """Bloqueia qualquer interação de usuários não autorizados."""
    user_id = update.from_user.id
    if user_id not in ALLOWED_USERS:
        if hasattr(update, 'text'):
            bot.send_message(update.chat.id, "🚫 Acesso Negado. Este bot é privado.")
        return False


# --- BANCO DE DADOS ---
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
with get_db_connection() as conn:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS compras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item TEXT NOT NULL,
            comprado INTEGER DEFAULT 0,
            adicionado_por TEXT,
            data_criacao TEXT
        )
    """)


# --- EMOJIS DINÂMICOS ---
MAPA_CATEGORIAS = {
    "🍎": ["maçã", "banana", "fruta", "pera", "uva", "abacaxi", "morango", "limão"],
    "🥦": ["alface", "brócolis", "cenoura", "legume", "verdura", "tomate", "cebola", "batata", "alho"],
    "🥩": ["carne", "picanha", "frango", "linguiça", "peixe", "presunto", "bacon", "ovo", "ovos"],
    "🥛": ["leite", "iogurte", "queijo", "manteiga", "requijão", "danone", "creme"],
    "🍞": ["pão", "biscoito", "bolacha", "torrada", "farinha", "massa", "macarrão"],
    "🥤": ["coca", "refri", "suco", "água", "cerveja", "vinho", "bebida", "gatorade"],
    "🧼": ["detergente", "sabão", "limpeza", "amaciante", "cloro", "desinfetante", "veja"],
    "🧻": ["papel", "higiênico", "guardanapo", "fralda", "absorvente"],
    "🍫": ["chocolate", "doce", "bala", "sobremesa", "nutella"],
    "☕": ["café", "pó", "açúcar", "adoçante", "chá", "nescau", "toddy"]
}


def get_emoji(texto):
    t = texto.lower()
    for e, palavras in MAPA_CATEGORIAS.items():
        if any(p in t for p in palavras):
            return e
    return "🛒"


# --- INTERFACE ---
def main_menu():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True)
    m.add(types.KeyboardButton("📋 Ver Lista"), types.KeyboardButton("🛒 Ver Carrinho"))
    m.add(types.KeyboardButton("🧹 Limpar Comprados"))
    return m


# --- HANDLERS ---
@bot.message_handler(commands=['start', 'menu'])
def welcome(message):
    bot.send_message(message.chat.id, "🛒 **Lista de Compras Privada**\n\nEnvie os itens diretamente!",
                     reply_markup=main_menu(), parse_mode="Markdown")


@bot.message_handler(func=lambda m: not m.text.startswith('/'))
def handle_text(m):
    t = m.text.strip()
    if t == "📋 Ver Lista": return show_list(m)
    if t == "🛒 Ver Carrinho": return show_cart(m)
    if t == "🧹 Limpar Comprados": return clear_db(m)

    agora = datetime.now().isoformat()
    with get_db_connection() as conn:
        if "," in t:
            itens = [f"{get_emoji(i.strip())} {i.strip().capitalize()}" for i in t.split(',') if i.strip()]
            conn.executemany("INSERT INTO compras (item, adicionado_por, data_criacao) VALUES (?, ?, ?)",
                             [(i, m.from_user.first_name, agora) for i in itens])
            bot.reply_to(m, f"🚀 {len(itens)} itens anotados!")
        else:
            item = f"{get_emoji(t)} {t.capitalize()}"
            conn.execute("INSERT INTO compras (item, adicionado_por, data_criacao) VALUES (?, ?, ?)",
                         (item, m.from_user.first_name, agora))
            bot.reply_to(m, f"➕ {item} anotado!")


def show_list(m):
    with get_db_connection() as conn:
        items = conn.execute("SELECT id, item FROM compras WHERE comprado = 0").fetchall()
    if not items:
        return bot.send_message(m.chat.id, "✅ Lista vazia!")

    markup = types.InlineKeyboardMarkup(row_width=1)
    for r in items:
        markup.add(types.InlineKeyboardButton(text=r['item'], callback_data=f"buy_{r['id']}"))
    bot.send_message(m.chat.id, "🛒 **O que falta comprar:**", reply_markup=markup, parse_mode="Markdown")


def show_cart(m):
    with get_db_connection() as conn:
        items = conn.execute("SELECT item FROM compras WHERE comprado = 1").fetchall()
    if not items:
        return bot.send_message(m.chat.id, "🛒 Carrinho vazio!")

    res = "🛒 **No Carrinho:**\n\n" + "\n".join([f"✅ {r['item']}" for r in items])
    bot.send_message(m.chat.id, res, parse_mode="Markdown")


@bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
def handle_buy(call):
    item_id = call.data.split('_')[1]
    with get_db_connection() as conn:
        conn.execute("UPDATE compras SET comprado = 1 WHERE id = ?", (item_id,))
        items = conn.execute("SELECT id, item FROM compras WHERE comprado = 0").fetchall()

    if not items:
        bot.edit_message_text("✅ Tudo comprado!", call.message.chat.id, call.message.message_id)
    else:
        markup = types.InlineKeyboardMarkup(row_width=1)
        for r in items:
            markup.add(types.InlineKeyboardButton(text=r['item'], callback_data=f"buy_{r['id']}"))
        bot.edit_message_text("🛒 **O que falta comprar:**", call.message.chat.id, call.message.message_id,
                              reply_markup=markup, parse_mode="Markdown")
    bot.answer_callback_query(call.id, "Peguei!")


def clear_db(m):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM compras WHERE comprado = 1")
    bot.reply_to(m, "🧹 Histórico de compras limpo!", reply_markup=main_menu())


# --- WEBHOOK ---
def inicializar_webhook():
    """Registra o webhook no Telegram na primeira execução."""
    global _webhook_initialized
    if _webhook_initialized:
        return
    _webhook_initialized = True

    WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')
    logger.info(f"📋 WEBHOOK_URL configurada: {WEBHOOK_URL if WEBHOOK_URL else '❌ NÃO CONFIGURADA'}")

    if not WEBHOOK_URL:
        logger.error("❌ WEBHOOK_URL não configurada. O bot não receberá mensagens.")
        return

    try:
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL)
        logger.info("✅ Webhook registrado com sucesso.")
    except Exception as e:
        logger.error(f"❌ Erro ao registrar webhook: {e}")


@app.before_request
def setup():
    """Executa uma vez antes do primeiro request."""
    inicializar_webhook()


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        json_data = request.get_json()
        update = types.Update.de_json(json_data)
        bot.process_new_updates([update])
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"❌ Erro ao processar webhook: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"}), 200


@app.route('/webhook-register', methods=['POST'])
def webhook_register():
    WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')
    if not WEBHOOK_URL:
        return jsonify({"error": "WEBHOOK_URL not configured"}), 400
    try:
        bot.remove_webhook()
        bot.set_webhook(url=WEBHOOK_URL)
        webhook_info = bot.get_webhook_info()
        return jsonify({
            "status": "webhook registered",
            "url": webhook_info.url,
            "pending_update_count": webhook_info.pending_update_count,
            "last_error_message": webhook_info.last_error_message if webhook_info.last_error_date else None
        }), 200
    except Exception as e:
        logger.error(f"❌ Erro ao configurar webhook: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/webhook-info', methods=['GET'])
def webhook_info():
    try:
        info = bot.get_webhook_info()
        return jsonify({
            "url": info.url,
            "pending_update_count": info.pending_update_count,
            "last_error_date": info.last_error_date,
            "last_error_message": info.last_error_message if info.last_error_date else None,
            "max_connections": info.max_connections
        }), 200
    except Exception as e:
        logger.error(f"❌ Erro ao obter webhook info: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    inicializar_webhook()
    logger.info("🤖 ComprasDaCasaBot Online via webhook")
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8000)), debug=False)
