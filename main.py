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
MODO_PRUEBAS = True  # Cámbialo a False para que los horarios sean REALES
URL_PROYECTO = "https://pizzeria-bot-l4y4.onrender.com"
NOMBRE_BOT_ALIAS = "pizzaioloo_bot" 

# Carga de Admins desde Render
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
        .card h3 {{ color: var(--primary); font-size: 1.8rem; }}
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
            <div class="card">
                <h3>🕒 Horarios</h3>
                <p><b>Viernes:</b> 20:30-23:00<br><b>Sáb-Dom:</b> 13:30-16:00 / 20:30-23:00</p>
            </div>
            <div class="card">
                <h3>📍 Zona Reparto</h3>
                <p>Centro y alrededores. Consulta disponibilidad inmediata en el bot.</p>
            </div>
            <div class="card">
                <h3>💳 Pago</h3>
                <p>Efectivo al recibir tu pedido. ¡Rápido y sin líos!</p>
            </div>
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
    c.execute('''CREATE TABLE IF NOT EXISTS pedidos
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, username TEXT, productos TEXT, 
                  total REAL, direccion TEXT, hora_entrega TEXT, estado TEXT DEFAULT 'pendiente', 
                  valoracion INTEGER DEFAULT 0, fecha TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios
                 (user_id INTEGER PRIMARY KEY, username TEXT, ultimo_pedido TEXT, puntos INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS valoraciones
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, pedido_id INTEGER, user_id INTEGER, 
                  estrellas INTEGER, comentario TEXT, fecha TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS faq_stats
                 (pregunta TEXT PRIMARY KEY, veces_preguntada INTEGER DEFAULT 0)''')
    conn.commit(); conn.close()

def get_db():
    return sqlite3.connect('knocktwice.db')

# ============ MENÚ Y FAQ ============
MENU = {
    "pizzas": {
        "titulo": "🍕 PIZZAS",
        "productos": {
            "margarita": {"nombre": "Margarita", "precio": 10, "desc": "Tomate, mozzarella y albahaca.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "trufada": {"nombre": "Trufada", "precio": 14, "desc": "Salsa de trufa y champiñones.", "alergenos": ["LACTEOS", "GLUTEN", "SETAS"]},
            "serranucula": {"nombre": "Serranúcula", "precio": 13, "desc": "Jamón ibérico y rúcula.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "amatriciana": {"nombre": "Amatriciana", "precio": 12, "desc": "Bacon y mozzarella.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "pepperoni": {"nombre": "Pepperoni", "precio": 11, "desc": "Pepperoni y mozzarella.", "alergenos": ["LACTEOS", "GLUTEN"]}
        }
    },
    "burgers": {
        "titulo": "🍔 BURGERS",
        "productos": {
            "classic": {"nombre": "Classic Cheese", "precio": 11, "desc": "Doble carne y cheddar.", "alergenos": ["LACTEOS", "GLUTEN", "HUEVO"]},
            "capone": {"nombre": "Al Capone", "precio": 12, "desc": "Queso de cabra y cebolla.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "bacon": {"nombre": "Bacon BBQ", "precio": 12, "desc": "Bacon crujiente y BBQ.", "alergenos": ["LACTEOS", "GLUTEN"]}
        }
    },
    "postres": {
        "titulo": "🍰 POSTRES",
        "productos": {
            "vinya": {"nombre": "Tarta de La Viña", "precio": 6, "desc": "Tarta de queso cremosa.", "alergenos": ["LACTEOS", "GLUTEN"]}
        }
    }
}

FAQ = {
    "horario": {"pregunta": "🕒 Horario", "respuesta": "*VIERNES:* 20:30-23:00\n*SÁB/DOM:* 13:30-16:00 / 20:30-23:00"},
    "zona": {"pregunta": "📍 Zona", "respuesta": "Centro y alrededores."},
    "alergenos": {"pregunta": "⚠️ Alérgenos", "respuesta": "Consulta cada plato en el menú."}
}

# ============ LÓGICA DE HORARIOS (NUEVA MEJORA) ============
TURNOS = {
    "VIERNES": ["20:30", "21:00", "21:30", "22:00", "22:30"],
    "SABADO": ["13:30", "14:00", "14:30", "15:00", "20:30", "21:00", "21:30", "22:00", "22:30"],
    "DOMINGO": ["13:30", "14:00", "14:30", "15:00", "20:30", "21:00", "21:30", "22:00", "22:30"]
}

def obtener_dia_actual():
    dias = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]
    ahora = datetime.utcnow() + timedelta(hours=1); return dias[ahora.weekday()]

def obtener_hora_actual():
    ahora = datetime.utcnow() + timedelta(hours=1); return ahora.strftime("%H:%M")

def esta_abierto():
    """Check para bloquear pedidos al pulsar unidades"""
    if MODO_PRUEBAS: return True, ""
    dia = obtener_dia_actual(); hora = obtener_hora_actual()
    if dia not in TURNOS: 
        return False, "Estamos cerrados. Te esperamos de viernes a domingo. 🚪"
    futuros = [h for h in TURNOS[dia] if h > hora]
    if not futuros:
        return False, "Hemos cerrado por hoy. Te esperamos de viernes a domingo. 🕗"
    return True, ""

# ============ SISTEMA DE COOLDOWN Y VALORACIONES ============
def verificar_cooldown(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT ultimo_pedido FROM usuarios WHERE user_id = ?", (user_id,))
    res = c.fetchone(); conn.close()
    if res and res[0]:
        diff = datetime.now() - datetime.fromisoformat(res[0])
        if diff < timedelta(minutes=30): return False, 30 - int(diff.total_seconds() / 60)
    return True, 0

def actualizar_cooldown(user_id, username):
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO usuarios (user_id, username, ultimo_pedido) VALUES (?,?,?)",
              (user_id, username, datetime.now().isoformat())); conn.commit(); conn.close()

def obtener_valoracion_promedio():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT AVG(valoracion) FROM pedidos WHERE valoracion > 0")
    res = c.fetchone()[0]; conn.close(); return round(res, 1) if res else 0.0

def obtener_pedidos_sin_valorar(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id, productos FROM pedidos WHERE user_id=? AND valoracion=0 ORDER BY fecha DESC LIMIT 3", (user_id,))
    res = c.fetchall(); conn.close(); return res

def guardar_valoracion(pedido_id, user_id, estrellas):
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE pedidos SET valoracion = ? WHERE id = ?", (estrellas, pedido_id))
    conn.commit(); conn.close()

# ============ HANDLERS DE MENÚ ============
def start(update: Update, context: CallbackContext, query=None):
    """Corregido: Edita si es botón, envía si es comando"""
    user_id = update.effective_user.id
    v_prom = obtener_valoracion_promedio()
    est = "⭐" * int(v_prom) if v_prom > 0 else "Sin valoraciones"
    
    txt = (f"🚪 **BIENVENIDO A KNOCK TWICE** 🤫\n\n"
           f"🍕 *Pizza & Burgers de autor*\n"
           f"⭐ *Valoración: {v_prom}/5 {est}*\n\n"
           f"*¿Qué deseas hacer?*")
    
    kb = [[InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal')],
          [InlineKeyboardButton("🛒 MI PEDIDO", callback_data='ver_carrito')],
          [InlineKeyboardButton("❓ PREGUNTAS FRECUENTES", callback_data='faq_menu')],
          [InlineKeyboardButton("⭐ VALORAR PEDIDO", callback_data='valorar_menu')]]
    
    if user_id in ADMIN_IDS: kb.append([InlineKeyboardButton("🔧 PANEL ADMIN", callback_data='admin_panel')])

    if query: query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else: update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def menu_principal(update: Update, context: CallbackContext, query=None):
    kb = [[InlineKeyboardButton("🍕 PIZZAS", callback_data='cat_pizzas')],
          [InlineKeyboardButton("🍔 BURGERS", callback_data='cat_burgers')],
          [InlineKeyboardButton("🍰 POSTRES", callback_data='cat_postres')],
          [InlineKeyboardButton("🛒 MI PEDIDO", callback_data='ver_carrito')],
          [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
    txt = "📂 **SELECCIONA CATEGORÍA:**"
    if query: query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else: update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def mostrar_categoria(update: Update, context: CallbackContext, cat):
    query = update.callback_query; query.answer()
    kb = [[InlineKeyboardButton(f"{p['nombre']} - {p['precio']}€", callback_data=f"info_{cat}_{pid}")] for pid, p in MENU[cat]['productos'].items()]
    kb.append([InlineKeyboardButton("🔙 VOLVER", callback_data='menu_principal')])
    query.edit_message_text(f"👇 **{MENU[cat]['titulo']}**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def mostrar_info_producto(update: Update, context: CallbackContext, cat, pid):
    query = update.callback_query; query.answer()
    p = MENU[cat]['productos'][pid]
    txt = f"🍽️ **{p['nombre']}**\n\n_{p['desc']}_\n\n💰 {p['precio']}€\n⚠️ {', '.join(p['alergenos'])}\n\n¿Unidades?"
    kb = [[InlineKeyboardButton(str(i), callback_data=f"add_{cat}_{pid}_{i}") for i in range(1, 4)],
          [InlineKeyboardButton(str(i), callback_data=f"add_{cat}_{pid}_{i}") for i in range(4, 6)],
          [InlineKeyboardButton("🔙 VOLVER", callback_data=f"cat_{cat}")]]
    query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def añadir_al_carrito(update: Update, context: CallbackContext, cat, pid, cant):
    query = update.callback_query; query.answer()
    
    # --- BLOQUEO POR HORARIO AL PULSAR UNIDADES ---
    abierto, msg = esta_abierto()
    if not abierto:
        query.edit_message_text(f"🚫 **LO SENTIMOS**\n\n{msg}", 
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 VOLVER A LA CARTA", callback_data='menu_principal')]]), parse_mode='Markdown')
        return

    p = MENU[cat]['productos'][pid]
    for _ in range(int(cant)): context.user_data['carrito'].append({'nombre': p['nombre'], 'precio': p['precio']})
    kb = [[InlineKeyboardButton("🍽️ SEGUIR", callback_data='menu_principal')], [InlineKeyboardButton("🛒 VER PEDIDO", callback_data='ver_carrito')]]
    query.edit_message_text(f"✅ {cant}x {p['nombre']} añadido.", reply_markup=InlineKeyboardMarkup(kb))

# ============ CARRITO Y PEDIDO ============
def ver_carrito(update: Update, context: CallbackContext, query=None):
    car = context.user_data.get('carrito', [])
    if not car:
        txt, kb = "🛒 **VACÍO**", [[InlineKeyboardButton("🍽️ CARTA", callback_data='menu_principal')]]
    else:
        total = sum(i['precio'] for i in car)
        txt = "📝 **PEDIDO:**\n\n" + "\n".join([f"• {i['nombre']}" for i in car]) + f"\n\n💰 **TOTAL: {total}€**"
        kb = [[InlineKeyboardButton("📍 DIRECCIÓN", callback_data='pedir_direccion')], [InlineKeyboardButton("🗑️ VACIAR", callback_data='vaciar_carrito')], [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
    if query: query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else: update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def confirmar_hora(update: Update, context: CallbackContext, hora):
    query = update.callback_query; query.answer(); user = query.from_user
    car = context.user_data.get('carrito', []); total = sum(i['precio'] for i in car); prods = ", ".join([i['nombre'] for i in car])
    dir = context.user_data.get('direccion', 'No especificada')
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT INTO pedidos (user_id, username, productos, total, direccion, hora_entrega, fecha) VALUES (?,?,?,?,?,?,?)",
              (user.id, user.username, prods, total, dir, hora, datetime.now().isoformat()))
    p_id = c.lastrowid; conn.commit(); conn.close()
    actualizar_cooldown(user.id, user.username)
    context.bot.send_message(ID_GRUPO_PEDIDOS, f"🚪 **PEDIDO #{p_id}**\n👤 @{user.username}\n📍 {dir}\n⏰ {hora}\n🍽️ {prods}\n💰 {total}€")
    context.user_data['carrito'] = []
    query.edit_message_text(f"✅ **¡PEDIDO #{p_id} CONFIRMADO!**\n\nPronto estará listo. 🤫")

# ============ AUTO-RESPUESTA Y ADMIN ============
def handle_message(update: Update, context: CallbackContext):
    if context.user_data.get('esperando_direccion'):
        context.user_data['direccion'] = update.message.text
        context.user_data['esperando_direccion'] = False
        dia = obtener_dia_actual(); hora = obtener_hora_actual()
        futuros = [h for h in TURNOS.get(dia, []) if h > hora]
        if futuros:
            kb = [[InlineKeyboardButton(h, callback_data=f"hora_{h}")] for h in futuros[:6]]
            update.message.reply_text("⏰ Selecciona hora:", reply_markup=InlineKeyboardMarkup(kb))
        else: update.message.reply_text("❌ No hay horarios.")
    else:
        abierto, msg = esta_abierto()
        if not abierto:
            update.message.reply_text(f"👋 ¡Hola! {msg}\n\nPuedes ver la carta con /menu pero no aceptamos pedidos ahora.", parse_mode='Markdown')
        else:
            update.message.reply_text("Usa /menu para pedir o los botones.")

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query; data = query.data
    if data == 'inicio': query.answer(); start(update, context, query=query)
    elif data == 'menu_principal': menu_principal(update, context, query)
    elif data == 'ver_carrito': ver_carrito(update, context, query)
    elif data == 'pedir_direccion':
        query.answer(); context.user_data['esperando_direccion'] = True
        query.edit_message_text("📍 Escribe tu dirección por favor:")
    elif data == 'vaciar_carrito': context.user_data['carrito'] = []; ver_carrito(update, context, query)
    elif data.startswith('cat_'): mostrar_categoria(update, context, data.split('_')[1])
    elif data.startswith('info_'): mostrar_info_producto(update, context, data.split('_')[1], data.split('_')[2])
    elif data.startswith('add_'): p = data.split('_'); añadir_al_carrito(update, context, p[1], p[2], p[3])
    elif data.startswith('hora_'): confirmar_hora(update, context, data.split('_')[1])
    elif data == 'faq_menu':
        kb = [[InlineKeyboardButton(f['pregunta'], callback_data=f"faq_{k}")] for k, f in FAQ.items()]
        kb.append([InlineKeyboardButton("🏠 INICIO", callback_data='inicio')])
        query.edit_message_text("❓ **PREGUNTAS**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    elif data.startswith('faq_'):
        f = FAQ[data.split('_')[1]]; query.edit_message_text(f['respuesta'], reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data='faq_menu')]]), parse_mode='Markdown')
    elif data == 'valorar_menu':
        peds = obtener_pedidos_sin_valorar(query.from_user.id)
        if not peds: query.edit_message_text("No hay pedidos para valorar.")
        else:
            kb = [[InlineKeyboardButton(f"#{p[0]}", callback_data=f"val_{p[0]}")] for p in peds]
            query.edit_message_text("⭐ Selecciona pedido:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('val_'):
        pid = data.split('_')[1]; kb = [[InlineKeyboardButton("⭐"*i, callback_data=f"pnt_{pid}_{i}") for i in range(1, 6)]]
        query.edit_message_text("Puntúa el pedido:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('pnt_'):
        guardar_valoracion(data.split('_')[1], query.from_user.id, data.split('_')[2])
        query.edit_message_text("✅ Gracias!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠", callback_data='inicio')]]))

# ============ SERVIDOR WEB Y ANTISLEEP ============
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-type", "text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(HTML_WEB.encode("utf-8"))
    def log_message(self, format, *args): pass

def keep_alive():
    time.sleep(15)
    while True:
        try: requests.get(URL_PROYECTO, timeout=15); print("✅ Ping OK")
        except: pass
        time.sleep(840)

def main():
    init_db()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthHandler).serve_forever(), daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    updater = Updater(TOKEN, use_context=True); dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start)); dp.add_handler(CommandHandler("menu", menu_principal))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    updater.start_polling(); updater.idle()

if __name__ == "__main__": main()
