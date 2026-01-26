import os
import sqlite3
import threading
import time
import requests
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext

# --- CONFIGURACIÓN SIMPLIFICADA ---
ID_GRUPO_PEDIDOS = "-5151917747"
TOKEN = os.environ.get("TELEGRAM_TOKEN")
MODO_PRUEBAS = True

# --- BASE DE DATOS SIMPLIFICADA ---
def init_db():
    conn = sqlite3.connect('knocktwice.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS pedidos
                 (id INTEGER PRIMARY KEY,
                  user_id INTEGER,
                  username TEXT,
                  productos TEXT,
                  total REAL,
                  fecha TEXT)''')
    conn.commit()
    conn.close()

# --- MENÚ SIMPLIFICADO ---
MENU = {
    "pizzas": {
        "🍕 PIZZAS": {
            "Margarita": 10,
            "Trufada": 14,
            "Serranúcula": 13,
            "Amatriciana": 12,
            "Pepperoni": 11
        }
    },
    "burgers": {
        "🍔 BURGERS": {
            "Classic Cheese": 11,
            "Al Capone": 12,
            "Bacon BBQ": 12
        }
    },
    "postres": {
        "🍰 POSTRES": {
            "Tarta de La Viña": 6
        }
    }
}

# --- HANDLERS SIMPLIFICADOS ---
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    update.message.reply_text(
        f"🚪 ¡Hola {user.first_name}! Bienvenido a Knock Twice 🤫\n\n"
        "Usa /menu para ver la carta\n"
        "Usa /pedido para ver tu carrito\n"
        "Usa /ayuda para más información"
    )

def menu(update: Update, context: CallbackContext):
    keyboard = []
    for categoria, productos in MENU.items():
        for nombre_cat, items in productos.items():
            keyboard.append([InlineKeyboardButton(nombre_cat, callback_data=f"cat_{categoria}")])
    
    keyboard.append([InlineKeyboardButton("🛒 Ver mi pedido", callback_data="ver_carrito")])
    
    update.message.reply_text(
        "🍽️ **NUESTRA CARTA**\nSelecciona una categoría:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    data = query.data
    
    if data.startswith("cat_"):
        categoria = data.split("_")[1]
        productos = MENU[categoria]
        
        keyboard = []
        for nombre_cat, items in productos.items():
            for producto, precio in items.items():
                keyboard.append([
                    InlineKeyboardButton(f"➕ {producto} - {precio}€", 
                    callback_data=f"add_{categoria}_{producto}_{precio}")
                ])
        
        keyboard.append([InlineKeyboardButton("🔙 Volver", callback_data="volver_menu")])
        
        query.edit_message_text(
            f"Selecciona un producto:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith("add_"):
        # Añadir al carrito
        partes = data.split("_")
        producto = partes[2]
        precio = partes[3]
        
        if 'carrito' not in context.user_data:
            context.user_data['carrito'] = []
        
        context.user_data['carrito'].append(f"{producto} - {precio}€")
        
        query.answer(f"✅ {producto} añadido al carrito")
    
    elif data == "ver_carrito":
        carrito = context.user_data.get('carrito', [])
        if not carrito:
            texto = "🛒 Tu carrito está vacío"
        else:
            texto = "📝 **TU PEDIDO:**\n\n"
            total = 0
            for item in carrito:
                texto += f"• {item}\n"
                # Extraer precio del formato "Producto - 10€"
                try:
                    precio = float(item.split("- ")[1].replace("€", ""))
                    total += precio
                except:
                    pass
            
            texto += f"\n💰 **TOTAL: {total}€**"
        
        keyboard = [
            [InlineKeyboardButton("🍽️ Seguir pidiendo", callback_data="volver_menu")],
            [InlineKeyboardButton("🗑️ Vaciar carrito", callback_data="vaciar_carrito")]
        ]
        
        if carrito:
            keyboard.insert(0, [InlineKeyboardButton("✅ Confirmar pedido", callback_data="confirmar")])
        
        query.edit_message_text(
            texto,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif data == "volver_menu":
        # Volver al menú principal
        keyboard = []
        for categoria, productos in MENU.items():
            for nombre_cat, items in productos.items():
                keyboard.append([InlineKeyboardButton(nombre_cat, callback_data=f"cat_{categoria}")])
        
        keyboard.append([InlineKeyboardButton("🛒 Ver mi pedido", callback_data="ver_carrito")])
        
        query.edit_message_text(
            "🍽️ **NUESTRA CARTA**\nSelecciona una categoría:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif data == "vaciar_carrito":
        context.user_data['carrito'] = []
        query.edit_message_text("🗑️ Carrito vaciado")
    
    elif data == "confirmar":
        carrito = context.user_data.get('carrito', [])
        if not carrito:
            query.edit_message_text("❌ El carrito está vacío")
            return
        
        # Guardar en base de datos
        conn = sqlite3.connect('knocktwice.db')
        c = conn.cursor()
        
        productos_str = ", ".join(carrito)
        user = query.from_user
        
        c.execute('''INSERT INTO pedidos (user_id, username, productos, total, fecha)
                     VALUES (?, ?, ?, ?, ?)''',
                  (user.id, user.username, productos_str, 0, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        # Enviar al grupo
        try:
            context.bot.send_message(
                chat_id=ID_GRUPO_PEDIDOS,
                text=f"🚪 **NUEVO PEDIDO**\n\n"
                     f"👤 Cliente: @{user.username or user.first_name}\n"
                     f"📦 Pedido:\n{productos_str}"
            )
        except:
            pass
        
        context.user_data['carrito'] = []
        query.edit_message_text(
            "✅ **¡PEDIDO CONFIRMADO!**\n\n"
            "Hemos recibido tu pedido. En breve nos pondremos en contacto contigo.\n\n"
            "¡Gracias por elegir Knock Twice! 🤫",
            parse_mode='Markdown'
        )

def pedido(update: Update, context: CallbackContext):
    """Ver el carrito actual"""
    carrito = context.user_data.get('carrito', [])
    if not carrito:
        update.message.reply_text("🛒 Tu carrito está vacío")
    else:
        texto = "📝 **TU PEDIDO:**\n\n"
        for item in carrito:
            texto += f"• {item}\n"
        
        update.message.reply_text(texto, parse_mode='Markdown')

def ayuda(update: Update, context: CallbackContext):
    update.message.reply_text(
        "🆘 **AYUDA**\n\n"
        "• /start - Iniciar bot\n"
        "• /menu - Ver la carta\n"
        "• /pedido - Ver tu carrito\n"
        "• /ayuda - Esta información\n\n"
        "📍 Entregamos en Bilbao centro\n"
        "⏰ Viernes a Domingo: 20:30-23:00\n"
        "📞 Contacto: +34 600 000 000",
        parse_mode='Markdown'
    )

# --- SERVIDOR WEB PARA RENDER ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Knock Twice Bot - Online")
    
    def log_message(self, format, *args):
        pass

def start_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"✅ Servidor en puerto {port}")
    server.serve_forever()

def keep_alive():
    """Mantiene activo el servicio"""
    url = os.environ.get("RENDER_URL", "https://knock-twice.onrender.com")
    while True:
        try:
            time.sleep(300)  # 5 minutos
            requests.get(url, timeout=10)
        except:
            pass

# --- FUNCIÓN PRINCIPAL ---
def main():
    # Inicializar base de datos
    init_db()
    
    if not TOKEN:
        print("❌ ERROR: No hay token de Telegram")
        print("ℹ️ Configura la variable TELEGRAM_TOKEN en Render")
        return
    
    # Iniciar servidor web en hilo separado
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # Iniciar keep-alive en hilo separado
    keepalive_thread = threading.Thread(target=keep_alive, daemon=True)
    keepalive_thread.start()
    
    # Crear y configurar el bot
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # Añadir handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", menu))
    dp.add_handler(CommandHandler("pedido", pedido))
    dp.add_handler(CommandHandler("ayuda", ayuda))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, ayuda))
    
    print("🤖 Bot iniciado correctamente")
    print("✅ Servidor web activo")
    print("✅ Base de datos lista")
    
    # Iniciar el bot
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
