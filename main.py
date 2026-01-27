import os
import sqlite3
import threading
import time
import requests
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext

# ============ CONFIGURACIÓN GLOBAL ============
ID_GRUPO_PEDIDOS = "-5151917747"
TOKEN = os.environ.get("TELEGRAM_TOKEN")
MODO_PRUEBAS = True  # True: Deja pedir siempre | False: Bloquea según reloj
URL_PROYECTO = "https://pizzeria-bot-l4y4.onrender.com"
NOMBRE_BOT_ALIAS = "pizzaioloo_bot" 

admin_ids_str = os.environ.get("ADMIN_IDS", "")
if admin_ids_str:
    ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip().isdigit()]
else:
    ADMIN_IDS = [123456789]

# ============ WEB LANDING PAGE ============
HTML_WEB = f"""
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Knock Twice | Pizza & Burgers</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;800&display=swap" rel="stylesheet">
    <style>
        :root {{ --primary: #ff4757; --dark: #0f1113; }}
        body {{ margin: 0; font-family: 'Poppins', sans-serif; background: var(--dark); color: white; text-align: center; }}
        .hero {{ height: 100vh; display: flex; flex-direction: column; justify-content: center; align-items: center; 
                 background: linear-gradient(rgba(0,0,0,0.7), rgba(0,0,0,0.7)), url('https://images.unsplash.com/photo-1513104890138-7c749659a591?q=80&w=2000&auto=format&fit=crop');
                 background-size: cover; background-position: center; }}
        .btn {{ background: var(--primary); color: white; text-decoration: none; padding: 20px 60px; border-radius: 100px; font-weight: 600; transition: 0.3s; }}
        .btn:hover {{ transform: scale(1.05); background: #ff6b81; }}
        .info {{ padding: 60px 20px; background: white; color: #1e2229; }}
    </style>
</head>
<body>
    <div class="hero">
        <h1>KNOCK TWICE 🤫</h1>
        <p>Pizzas & Burgers de autor.</p>
        <a href="https://t.me/{NOMBRE_BOT_ALIAS}" class="btn">🚀 PEDIR AHORA</a>
    </div>
    <div class="info">
        <h2>Viernes a Domingo</h2>
        <p>Centro y alrededores</p>
    </div>
</body>
</html>
"""

# ============ BASE DE DATOS ============
def init_db():
    conn = sqlite3.connect('knocktwice.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS pedidos (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, productos TEXT, total REAL, direccion TEXT, hora_entrega TEXT, estado TEXT DEFAULT 'pendiente', valoracion INTEGER DEFAULT 0, fecha TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (user_id INTEGER PRIMARY KEY, username TEXT, ultimo_pedido TEXT, puntos INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS valoraciones (id INTEGER PRIMARY KEY AUTOINCREMENT, pedido_id INTEGER, user_id INTEGER, estrellas INTEGER, comentario TEXT, fecha TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS faq_stats (pregunta TEXT PRIMARY KEY, veces_preguntada INTEGER DEFAULT 0)''')
    conn.commit(); conn.close()

def get_db():
    return sqlite3.connect('knocktwice.db')

# ============ MENÚ COMPLETO ============
MENU = {
    "pizzas": {
        "titulo": "🍕 PIZZAS",
        "productos": {
            "margarita": {"nombre": "Margarita", "precio": 10, "desc": "Tomate, mozzarella y albahaca.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "trufada": {"nombre": "Trufada", "precio": 14, "desc": "Trufa y champiñones.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "serranucula": {"nombre": "Serranúcula", "precio": 13, "desc": "Jamón y rúcula.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "amatriciana": {"nombre": "Amatriciana", "precio": 12, "desc": "Bacon y mozzarella.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "pepperoni": {"nombre": "Pepperoni", "precio": 11, "desc": "Pepperoni y mozzarella.", "alergenos": ["LACTEOS", "GLUTEN"]}
        }
    },
    "burgers": {
        "titulo": "🍔 BURGERS",
        "productos": {
            "classic": {"nombre": "Classic Cheese", "precio": 11, "desc": "Doble carne y cheddar.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "capone": {"nombre": "Al Capone", "precio": 12, "desc": "Queso de cabra.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "bacon": {"nombre": "Bacon BBQ", "precio": 12, "desc": "Bacon BBQ.", "alergenos": ["LACTEOS", "GLUTEN"]}
        }
    },
    "postres": {
        "titulo": "🍰 POSTRES",
        "productos": {
            "vinya": {"nombre": "Tarta de La Viña", "precio": 6, "desc": "Tarta de queso.", "alergenos": ["LACTEOS", "GLUTEN"]}
        }
    }
}

FAQ = {
    "horario": {"pregunta": "🕒 Horario", "respuesta": "*VIE-DOM:* Cenas."},
    "zona": {"pregunta": "📍 Zona", "respuesta": "Centro."},
    "alergenos": {"pregunta": "⚠️ Alérgenos", "respuesta": "Ver descripción."}
}

TURNOS = {
    "VIERNES": ["20:30", "21:00", "21:30", "22:00", "22:30"],
    "SABADO": ["13:30", "14:00", "15:00", "20:30", "21:00", "22:00"],
    "DOMINGO": ["13:30", "14:00", "15:00", "20:30", "21:00", "22:00"]
}

# ============ LÓGICA DE TIEMPO ============
def obtener_dia_actual():
    dias = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]
    ahora = datetime.utcnow() + timedelta(hours=1); return dias[ahora.weekday()]

def obtener_hora_actual():
    ahora = datetime.utcnow() + timedelta(hours=1); return ahora.strftime("%H:%M")

def esta_abierto():
    if MODO_PRUEBAS: return True, ""
    dia = obtener_dia_actual(); hora = obtener_hora_actual()
    if dia not in TURNOS: return False, "Cerrado hoy. Abrimos Viernes a Domingo. 🚪"
    futuros = [h for h in TURNOS[dia] if h > hora]
    if not futuros: return False, "Cocina cerrada por hoy. 🕗"
    return True, ""

# ============ FUNCIONES DE APOYO ============
def verificar_cooldown(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT ultimo_pedido FROM usuarios WHERE user_id = ?", (user_id,))
    res = c.fetchone(); conn.close()
    if res and res[0] and not MODO_PRUEBAS:
        diff = datetime.now() - datetime.fromisoformat(res[0])
        if diff < timedelta(minutes=30): return False, 30 - int(diff.total_seconds() / 60)
    return True, 0

def obtener_valoracion_promedio():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT AVG(valoracion) FROM pedidos WHERE valoracion > 0")
    res = c.fetchone()[0]; conn.close(); return round(res, 1) if res else 0.0

def obtener_pedidos_sin_valorar(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id, productos FROM pedidos WHERE user_id=? AND valoracion=0 ORDER BY fecha DESC LIMIT 3", (user_id,))
    res = c.fetchall(); conn.close(); return res

def obtener_estadisticas():
    conn = get_db(); c = conn.cursor(); hoy = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*), SUM(total) FROM pedidos WHERE DATE(fecha) = ?", (hoy,))
    h = c.fetchone(); c.execute("SELECT COUNT(*), SUM(total) FROM pedidos"); t = c.fetchone()
    conn.close(); return {'hoy': h, 'total': t}

def es_admin(user_id): return user_id in ADMIN_IDS

# ============ HANDLERS DE MENÚ ============
def start(update: Update, context: CallbackContext, query=None):
    user_id = update.effective_user.id
    if 'carrito' not in context.user_data: context.user_data['carrito'] = []
    
    val_avg = obtener_valoracion_promedio()
    txt = f"🚪 **KNOCK TWICE** 🤫\n⭐ Valoración: {val_avg}/5\n\n¿Qué deseas hacer?"
    
    kb = [[InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal')],
          [InlineKeyboardButton("🛒 MI PEDIDO", callback_data='ver_carrito')],
          [InlineKeyboardButton("❓ FAQ", callback_data='faq_menu')],
          [InlineKeyboardButton("⭐ VALORAR", callback_data='valorar_menu')]]
    
    if es_admin(user_id): kb.append([InlineKeyboardButton("🔧 PANEL ADMIN", callback_data='admin_panel')])

    if query: query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else: update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def menu_principal(update: Update, context: CallbackContext, query=None):
    kb = [[InlineKeyboardButton("🍕 PIZZAS", callback_data='cat_pizzas')],
          [InlineKeyboardButton("🍔 BURGERS", callback_data='cat_burgers')],
          [InlineKeyboardButton("🍰 POSTRES", callback_data='cat_postres')],
          [InlineKeyboardButton("🛒 VER MI PEDIDO", callback_data='ver_carrito')],
          [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
    txt = "📂 **SELECCIONA UNA CATEGORÍA:**"
    if query: query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else: update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def añadir_al_carrito(update: Update, context: CallbackContext, cat, pid, cant):
    query = update.callback_query; query.answer()
    abierto, msg = esta_abierto()
    if not abierto:
        query.edit_message_text(f"🚫 **LO SENTIMOS**\n\n{msg}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 VOLVER", callback_data='menu_principal')]]))
        return
    p = MENU[cat]['productos'][pid]
    for _ in range(int(cant)): context.user_data['carrito'].append({'nombre': p['nombre'], 'precio': p['precio']})
    kb = [[InlineKeyboardButton("🛒 VER PEDIDO", callback_data='ver_carrito')], [InlineKeyboardButton("🍽️ SEGUIR", callback_data='menu_principal')]]
    query.edit_message_text(f"✅ {cant}x {p['nombre']} añadido.", reply_markup=InlineKeyboardMarkup(kb))

# ============ PEDIDOS Y DIRECCIÓN ============
def ver_carrito(update: Update, context: CallbackContext, query=None):
    car = context.user_data.get('carrito', [])
    if not car:
        txt, kb = "🛒 **VACÍO**", [[InlineKeyboardButton("🍽️ CARTA", callback_data='menu_principal')]]
    else:
        total = sum(i['precio'] for i in car)
        txt = f"📝 **TU PEDIDO:**\n" + "\n".join([f"• {i['nombre']}" for i in car]) + f"\n\n💰 **TOTAL: {total}€**"
        kb = [[InlineKeyboardButton("📍 PONER DIRECCIÓN", callback_data='pedir_direccion')],
              [InlineKeyboardButton("🗑️ VACIAR", callback_data='vaciar_carrito')],
              [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
    if query: query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else: update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def handle_message(update: Update, context: CallbackContext):
    if context.user_data.get('esperando_direccion'):
        context.user_data['direccion'] = update.message.text
        context.user_data['esperando_direccion'] = False
        dia = obtener_dia_actual(); hora = obtener_hora_actual()
        
        # FIX MODO PRUEBAS: Si es prueba, muestra todos los turnos del día
        if MODO_PRUEBAS:
            turnos_hoy = TURNOS.get(dia, TURNOS["VIERNES"]) # Si es lunes/martes, pilla viernes por defecto en pruebas
        else:
            turnos_hoy = [h for h in TURNOS.get(dia, []) if h > hora]
            
        if turnos_hoy:
            kb = [[InlineKeyboardButton(f"🕒 {h}", callback_data=f"hora_{h}")] for h in turnos_hoy[:8]]
            update.message.reply_text("✅ Dirección guardada. Elige hora de entrega:", reply_markup=InlineKeyboardMarkup(kb))
        else:
            update.message.reply_text("❌ No hay horarios disponibles para hoy.")
    else:
        abierto, msg = esta_abierto()
        if not abierto:
            update.message.reply_text(f"👋 ¡Hola! Actualmente estamos cerrados. {msg}", parse_mode='Markdown')
        else:
            update.message.reply_text("Usa /menu o los botones para pedir.")

# ============ ADMIN PANEL ============
def admin_panel(update: Update, context: CallbackContext, query=None):
    user_id = update.effective_user.id
    if not es_admin(user_id): return
    kb = [[InlineKeyboardButton("📊 ESTADÍSTICAS", callback_data='admin_stats')],
          [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
    if query: query.edit_message_text("🔧 **PANEL ADMIN**", reply_markup=InlineKeyboardMarkup(kb))
    else: update.message.reply_text("🔧 **PANEL ADMIN**", reply_markup=InlineKeyboardMarkup(kb))

# ============ BUTTON HANDLER CENTRAL ============
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query; data = query.data
    if data == 'inicio': query.answer(); start(update, context, query=query)
    elif data == 'menu_principal': menu_principal(update, context, query)
    elif data == 'ver_carrito': ver_carrito(update, context, query)
    elif data in ['pedir_direccion', 'tramitar_pedido']:
        query.answer(); context.user_data['esperando_direccion'] = True
        query.edit_message_text("📍 Por favor, escribe tu dirección completa:")
    elif data == 'vaciar_carrito': context.user_data['carrito'] = []; ver_carrito(update, context, query)
    elif data.startswith('cat_'):
        cat = data.split('_')[1]; kb = [[InlineKeyboardButton(p['nombre'], callback_data=f"info_{cat}_{pid}")] for pid, p in MENU[cat]['productos'].items()]
        kb.append([InlineKeyboardButton("🔙 VOLVER", callback_data='menu_principal')])
        query.edit_message_text("Elige un producto:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('info_'):
        pt = data.split('_'); p = MENU[pt[1]]['productos'][pt[2]]
        kb = [[InlineKeyboardButton(str(i), callback_data=f"add_{pt[1]}_{pt[2]}_{i}") for i in range(1, 4)], [InlineKeyboardButton("🔙 VOLVER", callback_data=f"cat_{pt[1]}")]]
        query.edit_message_text(f"🍽️ {p['nombre']}\n💰 {p['precio']}€\n¿Unidades?", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('add_'): p = data.split('_'); añadir_al_carrito(update, context, p[1], p[2], p[3])
    elif data.startswith('hora_'):
        hora = data.split('_')[1]; user = query.from_user; car = context.user_data.get('carrito', [])
        total = sum(i['precio'] for i in car); prods = ", ".join([i['nombre'] for i in car])
        # DB
        conn = get_db(); c = conn.cursor()
        c.execute("INSERT INTO pedidos (user_id, username, productos, total, direccion, hora_entrega, fecha) VALUES (?,?,?,?,?,?,?)",
                  (user.id, user.username, prods, total, context.user_data.get('direccion'), hora, datetime.now().isoformat()))
        p_id = c.lastrowid; conn.commit(); conn.close()
        # Grupo
        context.bot.send_message(chat_id=ID_GRUPO_PEDIDOS, text=f"🚪 **PEDIDO #{p_id}**\n👤 @{user.username}\n📍 {context.user_data.get('direccion')}\n⏰ {hora}\n🍽️ {prods}\n💰 {total}€")
        context.user_data['carrito'] = []
        query.edit_message_text(f"✅ **PEDIDO #{p_id} CONFIRMADO!**")
    elif data == 'admin_panel': admin_panel(update, context, query=query)
    elif data == 'admin_stats':
        s = obtener_estadisticas()
        query.edit_message_text(f"📊 Hoy: {s['hoy'][1] or 0}€ | Total: {s['total'][0]} pedidos", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data='admin_panel')]]))

# ============ SERVIDOR Y KEEPALIVE ============
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-type", "text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(HTML_WEB.encode("utf-8"))
    def log_message(self, format, *args): pass

def keep_alive():
    time.sleep(20)
    while True:
        try: requests.get(URL_PROYECTO, timeout=15); print("✅ Ping OK")
        except: pass
        time.sleep(840)

def main():
    init_db()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthHandler).serve_forever(), daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    updater = Updater(TOKEN, use_context=True); dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", menu_principal))
    dp.add_handler(CommandHandler("admin", lambda u, c: admin_panel(u, c)))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    updater.start_polling(); updater.idle()

if __name__ == "__main__": main()
