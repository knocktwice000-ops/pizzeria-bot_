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
MODO_PRUEBAS = False  # <--- PONLO EN 'False' PARA PROBAR EL CIERRE POR HORARIO
URL_PROYECTO = "https://pizzeria-bot-l4y4.onrender.com"
NOMBRE_BOT_ALIAS = "pizzaioloo_bot" 

# Carga de Admins desde Render
admin_ids_str = os.environ.get("ADMIN_IDS", "")
if admin_ids_str:
    ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip().isdigit()]
else:
    ADMIN_IDS = [123456789]

# ============ WEB LANDING PAGE (DISEÑO) ============
HTML_WEB = f"""
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Knock Twice | Pizza & Burgers</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;800&display=swap" rel="stylesheet">
    <style>
        :root {{ --primary: #ff4757; --dark: #0f1113; }}
        body {{ margin: 0; font-family: 'Poppins', sans-serif; background: var(--dark); color: white; text-align: center; }}
        .hero {{ height: 100vh; display: flex; flex-direction: column; justify-content: center; align-items: center; 
                 background: linear-gradient(rgba(0,0,0,0.7), rgba(0,0,0,0.7)), url('https://images.unsplash.com/photo-1513104890138-7c749659a591?q=80&w=2000&auto=format&fit=crop');
                 background-size: cover; background-position: center; }}
        h1 {{ font-size: 4.5rem; margin: 0; text-transform: uppercase; letter-spacing: -2px; }}
        p {{ font-size: 1.4rem; color: #ced4da; max-width: 650px; margin: 25px 0 45px; }}
        .btn {{ background: var(--primary); color: white; text-decoration: none; padding: 22px 60px; 
                border-radius: 100px; font-weight: 600; font-size: 1.3rem; transition: 0.3s; box-shadow: 0 10px 30px rgba(255, 71, 87, 0.4); }}
        .btn:hover {{ transform: scale(1.08); background: #ff6b81; }}
        .info {{ padding: 80px 20px; background: white; color: #1e2229; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 40px; max-width: 1200px; margin: 0 auto; }}
        .card {{ background: #f1f2f6; padding: 40px; border-radius: 30px; box-shadow: 0 10px 20px rgba(0,0,0,0.05); }}
        footer {{ padding: 40px; opacity: 0.6; font-size: 0.9rem; }}
    </style>
</head>
<body>
    <div class="hero">
        <h1>KNOCK TWICE 🤫</h1>
        <p>Auténtica Pizza & Burger de autor. Haz tu pedido a través de nuestro bot oficial.</p>
        <a href="https://t.me/{NOMBRE_BOT_ALIAS}" class="btn">🚀 EMPEZAR PEDIDO</a>
    </div>
    <div class="info">
        <div class="grid">
            <div class="card"><h3>🕒 Horarios</h3><p>Viernes a Domingo</p></div>
            <div class="card"><h3>📍 Zona</h3><p>Centro y alrededores</p></div>
            <div class="card"><h3>💳 Pago</h3><p>Efectivo en entrega</p></div>
        </div>
    </div>
    <footer>© 2024 Knock Twice.</footer>
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
            "bacon": {"nombre": "Bacon BBQ", "precio": 12, "desc": "Bacon y salsa BBQ.", "alergenos": ["LACTEOS", "GLUTEN"]}
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
    "horario": {"pregunta": "🕒 Horario", "respuesta": "*VIE-DOM:* Cenas y comidas Sáb/Dom."},
    "zona": {"pregunta": "📍 Zona", "respuesta": "Centro y alrededores."},
    "alergenos": {"pregunta": "⚠️ Alérgenos", "respuesta": "Ver en descripción de cada plato."}
}

# ============ LÓGICA DE TIEMPO ============
TURNOS = {
    "VIERNES": ["20:30", "21:00", "21:30", "22:00", "22:15", "22:30"],
    "SABADO": ["13:30", "14:00", "14:30", "15:00", "20:30", "21:00", "21:30", "22:00", "22:30"],
    "DOMINGO": ["13:30", "14:00", "14:30", "15:00", "20:30", "21:00", "21:30", "22:00", "22:30"]
}

def obtener_dia_actual():
    dias = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]
    ahora = datetime.utcnow() + timedelta(hours=1); return dias[ahora.weekday()]

def obtener_hora_actual():
    ahora = datetime.utcnow() + timedelta(hours=1); return ahora.strftime("%H:%M")

def esta_abierto():
    """IMPORTANTE: Si MODO_PRUEBAS es True, siempre devuelve True"""
    if MODO_PRUEBAS: return True, ""
    dia = obtener_dia_actual(); hora = obtener_hora_actual()
    if dia not in TURNOS: return False, "Estamos cerrados. Te esperamos de viernes a domingo. 🚪"
    futuros = [h for h in TURNOS[dia] if h > hora]
    if not futuros: return False, "Hoy ya hemos cerrado la cocina. ¡Te esperamos el próximo día! 🕗"
    return True, ""

# ============ FUNCIONES ADMIN (RESTAURADAS COMPLETAS) ============
def es_admin(user_id): return user_id in ADMIN_IDS

def obtener_estadisticas():
    conn = get_db(); c = conn.cursor(); hoy = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*), SUM(total) FROM pedidos WHERE DATE(fecha) = ?", (hoy,))
    h = c.fetchone()
    c.execute("SELECT COUNT(*), SUM(total) FROM pedidos")
    t = c.fetchone()
    c.execute("SELECT AVG(valoracion) FROM pedidos WHERE valoracion > 0")
    v = c.fetchone()[0] or 0
    conn.close()
    return {'hoy': h, 'total': t, 'val': round(v, 1)}

def obtener_pedidos_recientes():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id, username, total, fecha FROM pedidos ORDER BY fecha DESC LIMIT 5")
    res = c.fetchall(); conn.close(); return res

# ============ HANDLERS DE MENÚ ============
def start(update: Update, context: CallbackContext, query=None):
    user_id = update.effective_user.id
    if 'carrito' not in context.user_data: context.user_data['carrito'] = []
    
    txt = (f"🚪 **BIENVENIDO A KNOCK TWICE** 🤫\n\n"
           f"¿Qué deseas hacer hoy?")
    
    kb = [[InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal')],
          [InlineKeyboardButton("🛒 MI PEDIDO", callback_data='ver_carrito')],
          [InlineKeyboardButton("❓ FAQ", callback_data='faq_menu')],
          [InlineKeyboardButton("⭐ VALORAR", callback_data='valorar_menu')]]
    
    if es_admin(user_id): kb.append([InlineKeyboardButton("🔧 ADMIN", callback_data='admin_panel')])

    if query: query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else: update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def menu_principal(update: Update, context: CallbackContext, query=None):
    kb = [[InlineKeyboardButton("🍕 PIZZAS", callback_data='cat_pizzas')],
          [InlineKeyboardButton("🍔 BURGERS", callback_data='cat_burgers')],
          [InlineKeyboardButton("🍰 POSTRES", callback_data='cat_postres')],
          [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
    if query: query.edit_message_text("📂 **NUESTRA CARTA**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else: update.message.reply_text("📂 **NUESTRA CARTA**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def añadir_al_carrito(update: Update, context: CallbackContext, cat, pid, cant):
    query = update.callback_query; query.answer()
    
    # --- BLOQUEO POR HORARIO ---
    abierto, msg = esta_abierto()
    if not abierto:
        query.edit_message_text(f"🚫 **LO SENTIMOS**\n\n{msg}", 
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 VOLVER", callback_data='inicio')]]))
        return

    p = MENU[cat]['productos'][pid]
    for _ in range(int(cant)): context.user_data['carrito'].append({'nombre': p['nombre'], 'precio': p['precio']})
    query.edit_message_text(f"✅ {cant}x {p['nombre']} añadido.", 
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 VER PEDIDO", callback_data='ver_carrito')], [InlineKeyboardButton("🍽️ SEGUIR", callback_data='menu_principal')]]))

# ============ BOTÓN HANDLER (RESTAURADO) ============
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query; data = query.data
    if data == 'inicio': query.answer(); start(update, context, query=query)
    elif data == 'menu_principal': menu_principal(update, context, query)
    elif data == 'ver_carrito': 
        car = context.user_data.get('carrito', [])
        if not car: query.edit_message_text("Vacío", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("CARTA", callback_data='menu_principal')]]))
        else:
            total = sum(i['precio'] for i in car)
            query.edit_message_text(f"Pedido: {total}€", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📍 DIRECCIÓN", callback_data='pedir_dir')]]))
    elif data == 'pedir_dir':
        context.user_data['esperando_direccion'] = True
        query.edit_message_text("📍 Escribe tu dirección:")
    elif data.startswith('cat_'):
        cat = data.split('_')[1]; kb = [[InlineKeyboardButton(p['nombre'], callback_data=f"info_{cat}_{pid}")] for pid, p in MENU[cat]['productos'].items()]
        query.edit_message_text("Elige:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('info_'):
        pt = data.split('_'); p = MENU[pt[1]]['productos'][pt[2]]
        kb = [[InlineKeyboardButton(str(i), callback_data=f"add_{pt[1]}_{pt[2]}_{i}") for i in range(1, 4)]]
        query.edit_message_text(f"{p['nombre']}: {p['precio']}€", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('add_'):
        p = data.split('_'); añadir_al_carrito(update, context, p[1], p[2], p[3])
    elif data == 'admin_panel':
        s = obtener_estadisticas()
        txt = f"📊 **STATS**\nHoy: {s['hoy'][1] or 0}€\n⭐ Val: {s['val']}"
        query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠", callback_data='inicio')]]))

# ============ AUTO-RESPUESTA Y MAIN ============
def handle_message(update: Update, context: CallbackContext):
    if context.user_data.get('esperando_direccion'):
        # Lógica de confirmación de pedido...
        pass
    else:
        abierto, msg = esta_abierto()
        if not abierto:
            update.message.reply_text(f"👋 ¡Hola! {msg}", parse_mode='Markdown')
        else:
            update.message.reply_text("Usa el menú para pedir.")

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-type", "text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(HTML_WEB.encode("utf-8"))

def keep_alive():
    while True:
        try: requests.get(URL_PROYECTO, timeout=15)
        except: pass
        time.sleep(840)

def main():
    init_db()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthHandler).serve_forever(), daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    updater = Updater(TOKEN, use_context=True); dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("admin", lambda u, c: start(u, c) if es_admin(u.effective_user.id) else None))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    updater.start_polling(); updater.idle()

if __name__ == "__main__": main()
