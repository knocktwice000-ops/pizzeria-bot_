import os
import sqlite3
import threading
import time
import requests
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext

# ============ CONFIGURACIÓN ============
ID_GRUPO_PEDIDOS = "-5151917747"
TOKEN = os.environ.get("TELEGRAM_TOKEN")
MODO_PRUEBAS = True  # Cambiar a False para activar horarios reales

admin_ids_str = os.environ.get("ADMIN_IDS", "")
if admin_ids_str:
    ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip().isdigit()]
else:
    ADMIN_IDS = [123456789] # Reemplaza con tu ID real

# ============ BASE DE DATOS ============
def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS pedidos
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, 
                 productos TEXT, total REAL, direccion TEXT, hora_entrega TEXT, 
                 estado TEXT DEFAULT 'pendiente', valoracion INTEGER DEFAULT 0, fecha TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios
                 (user_id INTEGER PRIMARY KEY, username TEXT, ultimo_pedido TEXT, puntos INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS valoraciones
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, pedido_id INTEGER, user_id INTEGER, 
                 estrellas INTEGER, comentario TEXT, fecha TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS faq_stats
                 (pregunta TEXT PRIMARY KEY, veces_preguntada INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

def get_db():
    return sqlite3.connect('knocktwice.db')

# ============ MENÚ COMPLETO ============
MENU = {
    "pizzas": {
        "titulo": "🍕 PIZZAS",
        "productos": {
            "margarita": {"nombre": "Margarita", "precio": 10, "desc": "Tomate, mozzarella y albahaca.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "trufada": {"nombre": "Trufada", "precio": 14, "desc": "Salsa de trufa, mozzarella y setas.", "alergenos": ["LACTEOS", "GLUTEN", "SETAS"]},
            "serranucula": {"nombre": "Serranúcula", "precio": 13, "desc": "Jamón ibérico y rúcula.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "amatriciana": {"nombre": "Amatriciana", "precio": 12, "desc": "Tomate, mozzarella y bacon.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "pepperoni": {"nombre": "Pepperoni", "precio": 11, "desc": "Tomate, mozzarella y pepperoni.", "alergenos": ["LACTEOS", "GLUTEN"]}
        }
    },
    "burgers": {
        "titulo": "🍔 BURGERS",
        "productos": {
            "classic": {"nombre": "Classic Cheese", "precio": 11, "desc": "Doble carne, cheddar y cebolla.", "alergenos": ["LACTEOS", "GLUTEN", "HUEVO"]},
            "capone": {"nombre": "Al Capone", "precio": 12, "desc": "Queso de cabra y cebolla caramelizada.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "bacon": {"nombre": "Bacon BBQ", "precio": 12, "desc": "Doble bacon y salsa barbacoa.", "alergenos": ["LACTEOS", "GLUTEN"]}
        }
    },
    "postres": {
        "titulo": "🍰 POSTRES",
        "productos": {
            "vinya": {"nombre": "Tarta de La Viña", "precio": 6, "desc": "Tarta de queso cremosa al horno.", "alergenos": ["LACTEOS", "GLUTEN"]}
        }
    }
}

FAQ = {
    "horario": {"pregunta": "🕒 ¿Horario?", "respuesta": "*VIERNES:* 20:30-23:00\n*SÁB/DOM:* 13:30-16:00 / 20:30-23:00"},
    "zona": {"pregunta": "📍 ¿Zona?", "respuesta": "Entregamos en centro y alrededores."},
    "alergenos": {"pregunta": "⚠️ ¿Alérgenos?", "respuesta": "Consulta cada plato en la carta."}
}

TURNOS = {
    "VIERNES": ["20:30", "21:00", "21:30", "22:00", "22:30"],
    "SABADO": ["13:30", "14:00", "14:30", "15:00", "20:30", "21:00", "21:30", "22:00", "22:30"],
    "DOMINGO": ["13:30", "14:00", "14:30", "15:00", "20:30", "21:00", "21:30", "22:00", "22:30"]
}

# ============ LÓGICA DE TIEMPO Y CERRADO ============
def obtener_dia_actual():
    dias = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]
    ahora = datetime.utcnow() + timedelta(hours=1)
    return dias[ahora.weekday()]

def obtener_hora_actual():
    ahora = datetime.utcnow() + timedelta(hours=1)
    return ahora.strftime("%H:%M")

def esta_abierto():
    """Check de horario real"""
    if MODO_PRUEBAS: return True, ""
    dia = obtener_dia_actual()
    hora = obtener_hora_actual()
    if dia == "VIERNES" and ("20:30" <= hora <= "23:00"): return True, ""
    if dia in ["SABADO", "DOMINGO"]:
        if ("13:30" <= hora <= "16:00") or ("20:30" <= hora <= "23:00"): return True, ""
    return False, "Actualmente estamos cerrados. Abrimos de Viernes a Domingo. 🕗"

# ============ FUNCIONES ADMIN (RESTAURADAS) ============
def es_admin(user_id):
    return user_id in ADMIN_IDS

def obtener_estadisticas():
    conn = get_db(); c = conn.cursor()
    hoy = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*), SUM(total) FROM pedidos WHERE DATE(fecha) = ?", (hoy,))
    hoy_data = c.fetchone()
    c.execute("SELECT COUNT(*), SUM(total) FROM pedidos")
    hist_data = c.fetchone()
    c.execute("SELECT AVG(valoracion) FROM pedidos WHERE valoracion > 0")
    val = c.fetchone()[0] or 0
    conn.close()
    return {"hoy": hoy_data, "total": hist_data, "avg": round(val, 1)}

# ============ NAVEGACIÓN Y MENÚS ============
def mostrar_inicio(update: Update, context: CallbackContext, query=None):
    user = update.effective_user
    val_promedio = obtener_valoracion_promedio()
    
    texto = (f"🚪 **KNOCK TWICE** 🤫\n\n"
             f"🍕 *Pizza & Burgers de autor*\n"
             f"⭐ *Valoración:* {val_promedio}/5\n\n"
             f"¿Qué deseas hacer?")
    
    keyboard = [
        [InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal')],
        [InlineKeyboardButton("🛒 MI PEDIDO", callback_data='ver_carrito')],
        [InlineKeyboardButton("❓ PREGUNTAS", callback_data='faq_menu')],
        [InlineKeyboardButton("⭐ VALORAR", callback_data='valorar_menu')]
    ]
    if es_admin(user.id):
        keyboard.append([InlineKeyboardButton("🔧 PANEL ADMIN", callback_data='admin_panel')])

    if query:
        query.edit_message_text(texto, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        update.message.reply_text(texto, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def start(update: Update, context: CallbackContext):
    if 'carrito' not in context.user_data: context.user_data['carrito'] = []
    mostrar_inicio(update, context)

def menu_principal(update: Update, context: CallbackContext, query=None):
    abierto, msg = esta_abierto()
    if not abierto:
        txt = f"🚫 **LOCAL CERRADO**\n\n{msg}"
        kb = [[InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
        if query: query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        else: update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        return

    kb = [[InlineKeyboardButton(v['titulo'], callback_data=f"cat_{k}")] for k, v in MENU.items()]
    kb.append([InlineKeyboardButton("🛒 VER MI PEDIDO", callback_data='ver_carrito')])
    kb.append([InlineKeyboardButton("🏠 INICIO", callback_data='inicio')])
    
    if query: query.edit_message_text("📂 **SELECCIONA CATEGORÍA**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else: update.message.reply_text("📂 **SELECCIONA CATEGORÍA**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

# ============ MANEJO DE BOTONES CENTRAL ============
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    query.answer()

    if data == 'inicio': mostrar_inicio(update, context, query)
    elif data == 'menu_principal': menu_principal(update, context, query)
    elif data == 'ver_carrito': ver_carrito(update, context, query)
    elif data == 'pedir_direccion': pedir_direccion(update, context)
    elif data == 'tramitar_pedido': pedir_direccion(update, context)
    elif data == 'vaciar_carrito':
        context.user_data['carrito'] = []
        ver_carrito(update, context, query)
    elif data.startswith('cat_'):
        mostrar_categoria(update, context, data.split('_')[1])
    elif data.startswith('info_'):
        mostrar_info_producto(update, context, data.split('_')[1], data.split('_')[2])
    elif data.startswith('add_'):
        partes = data.split('_')
        añadir_al_carrito(update, context, partes[1], partes[2], partes[3])
    elif data.startswith('hora_'):
        confirmar_hora(update, context, data.split('_')[1])
    
    # --- Secciones Especiales ---
    elif data == 'faq_menu': mostrar_faq_menu(update, context, query)
    elif data.startswith('faq_'): mostrar_faq_detalle(update, context, data.split('_')[1])
    elif data == 'valorar_menu': mostrar_valorar_menu(update, context, query)
    elif data.startswith('val_p_'): mostrar_puntuacion(update, context, data.split('_')[2])
    elif data.startswith('pnt_'): procesar_puntuacion(update, context, data.split('_')[1], data.split('_')[2])
    
    # --- Admin Panels ---
    elif data == 'admin_panel': mostrar_admin_panel(update, context, query)
    elif data == 'admin_stats': 
        s = obtener_estadisticas()
        txt = f"📊 **STATS**\nHoy: {s['hoy'][0]} ped. ({s['hoy'][1] or 0}€)\nTotal: {s['total'][0]} ped.\n⭐ Media: {s['avg']}"
        query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data='admin_panel')]]), parse_mode='Markdown')

# ============ FUNCIONES DE APOYO (RESTAURADAS) ============
def mostrar_categoria(update: Update, context: CallbackContext, cat):
    kb = [[InlineKeyboardButton(f"{p['nombre']} - {p['precio']}€", callback_data=f"info_{cat}_{pid}")] 
          for pid, p in MENU[cat]['productos'].items()]
    kb.append([InlineKeyboardButton("🔙 VOLVER", callback_data='menu_principal')])
    update.callback_query.edit_message_text(f"👇 **{MENU[cat]['titulo']}**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def mostrar_info_producto(update: Update, context: CallbackContext, cat, pid):
    p = MENU[cat]['productos'][pid]
    txt = f"🍽️ **{p['nombre']}**\n_{p['desc']}_\n\n💰 Precio: {p['precio']}€\n⚠️ Alérgenos: {', '.join(p['alergenos'])}"
    kb = [[InlineKeyboardButton(str(i), callback_data=f"add_{cat}_{pid}_{i}") for i in range(1, 4)],
          [InlineKeyboardButton("🔙 VOLVER", callback_data=f"cat_{cat}")]]
    update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def añadir_al_carrito(update: Update, context: CallbackContext, cat, pid, cant):
    p = MENU[cat]['productos'][pid]
    for _ in range(int(cant)):
        context.user_data['carrito'].append({'nombre': p['nombre'], 'precio': p['precio']})
    kb = [[InlineKeyboardButton("🍽️ SEGUIR PIDIENDO", callback_data='menu_principal')],
          [InlineKeyboardButton("🛒 VER CARRITO", callback_data='ver_carrito')]]
    update.callback_query.edit_message_text(f"✅ {cant}x {p['nombre']} añadido.", reply_markup=InlineKeyboardMarkup(kb))

def ver_carrito(update: Update, context: CallbackContext, query=None):
    car = context.user_data.get('carrito', [])
    if not car:
        txt, kb = "🛒 **Tu carrito está vacío**", [[InlineKeyboardButton("🍽️ IR A LA CARTA", callback_data='menu_principal')]]
    else:
        total = sum(item['precio'] for item in car)
        txt = "📝 **TU PEDIDO**\n\n" + "\n".join([f"• {i['nombre']} ({i['precio']}€)" for i in car]) + f"\n\n💰 **TOTAL: {total}€**"
        kb = [[InlineKeyboardButton("📍 PONER DIRECCIÓN", callback_data='pedir_direccion')],
              [InlineKeyboardButton("🗑️ VACIAR", callback_data='vaciar_carrito')],
              [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
    
    if query: query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else: update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def pedir_direccion(update: Update, context: CallbackContext):
    context.user_data['esperando_direccion'] = True
    update.callback_query.edit_message_text("📍 **PASO 1/2: DIRECCIÓN**\nEscribe tu calle y número por favor:")

def confirmar_hora(update: Update, context: CallbackContext, hora):
    query = update.callback_query
    user = query.from_user
    car = context.user_data.get('carrito', [])
    total = sum(i['precio'] for i in car)
    prods = ", ".join([i['nombre'] for i in car])
    dir_entrega = context.user_data.get('direccion', 'No especificada')
    
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT INTO pedidos (user_id, username, productos, total, direccion, hora_entrega, fecha) VALUES (?,?,?,?,?,?,?)",
              (user.id, user.username, prods, total, dir_entrega, hora, datetime.now().isoformat()))
    p_id = c.lastrowid; conn.commit(); conn.close()
    
    # Notificar al grupo
    context.bot.send_message(ID_GRUPO_PEDIDOS, f"🚪 **PEDIDO #{p_id}**\n👤 @{user.username}\n📍 {dir_entrega}\n⏰ {hora}\n🍽️ {prods}\n💰 {total}€")
    
    context.user_data['carrito'] = []
    query.edit_message_text(f"✅ **¡PEDIDO #{p_id} CONFIRMADO!**\n\nCocina está avisada. ¡Gracias! 🤫")

# ============ FUNCIONES RESTAURADAS ADICIONALES ============
def mostrar_faq_menu(update, context, query):
    kb = [[InlineKeyboardButton(f['pregunta'], callback_data=f"faq_{k}")] for k, f in FAQ.items()]
    kb.append([InlineKeyboardButton("🏠 INICIO", callback_data='inicio')])
    query.edit_message_text("❓ **PREGUNTAS FRECUENTES**", reply_markup=InlineKeyboardMarkup(kb))

def mostrar_faq_detalle(update, context, key):
    f = FAQ[key]
    query = update.callback_query
    # Registro de stats FAQ
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO faq_stats (pregunta, veces_preguntada) VALUES (?, COALESCE((SELECT veces_preguntada FROM faq_stats WHERE pregunta=?),0)+1)", (f['pregunta'], f['pregunta']))
    conn.commit(); conn.close()
    query.edit_message_text(f['respuesta'], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 VOLVER", callback_data='faq_menu')]]), parse_mode='Markdown')

def mostrar_admin_panel(update, context, query):
    if not es_admin(query.from_user.id): return
    kb = [[InlineKeyboardButton("📊 ESTADÍSTICAS", callback_data='admin_stats')],
          [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
    query.edit_message_text("🔧 **PANEL DE CONTROL**", reply_markup=InlineKeyboardMarkup(kb))

def obtener_valoracion_promedio():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT AVG(valoracion) FROM pedidos WHERE valoracion > 0")
    res = c.fetchone()[0]
    conn.close()
    return round(res, 1) if res else 0.0

# ============ SERVIDOR Y ANTISLEEP ============
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Knock Twice Online")
    def log_message(self, format, *args): pass

def start_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(('0.0.0.0', port), HealthHandler).serve_forever()

def keep_alive():
    """Antisleep Reforzado"""
    url = "https://knock-twice.onrender.com" # <--- TU URL DE RENDER
    time.sleep(15)
    while True:
        try:
            r = requests.get(url, timeout=10)
            print(f"✅ Keep-alive OK ({r.status_code})")
        except Exception as e: print(f"⚠️ Keep-alive error: {e}")
        time.sleep(840) # 14 minutos

# ============ MAIN ============
def main():
    init_db()
    threading.Thread(target=start_server, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button_handler))
    
    # Manejo de texto para la dirección
    def text_handler(update: Update, context: CallbackContext):
        if context.user_data.get('esperando_direccion'):
            context.user_data['direccion'] = update.message.text
            context.user_data['esperando_direccion'] = False
            dia = obtener_dia_actual()
            hora = obtener_hora_actual()
            horarios = [h for h in TURNOS.get(dia, []) if h > hora]
            if horarios:
                kb = [[InlineKeyboardButton(h, callback_data=f"hora_{h}")] for h in horarios[:6]]
                update.message.reply_text("⏰ **SELECCIONA HORA:**", reply_markup=InlineKeyboardMarkup(kb))
            else:
                update.message.reply_text("❌ No hay más turnos disponibles hoy.")
        else:
            mostrar_inicio(update, context)

    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, text_handler))
    
    updater.start_polling()
    print("🤖 Bot Knock Twice funcionando al 100% de potencia.")
    updater.idle()

if __name__ == "__main__":
    main()
