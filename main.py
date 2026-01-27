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
MODO_PRUEBAS = True  # Poner en False para que el bloqueo de horario sea real
URL_PROYECTO = "https://pizzeria-bot-l4y4.onrender.com"
NOMBRE_BOT_ALIAS = "pizzaioloo_bot"

# Configuración de administradores desde Render
admin_ids_str = os.environ.get("ADMIN_IDS", "")
if admin_ids_str:
    ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip().isdigit()]
else:
    ADMIN_IDS = [123456789]

# ============ PLANTILLA WEB PROFESIONAL (LANDING PAGE) ============
HTML_WEB = f"""
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Knock Twice | Pizza & Burgers</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;800&display=swap" rel="stylesheet">
    <style>
        :root {{ --primary: #ff4757; --dark: #0f1113; --card: #1e2229; }}
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
    <div class="info"><div class="grid">
        <div class="card"><h3>🕒 Horarios</h3><p><b>Viernes:</b> 20:30-23:00<br><b>Sáb-Dom:</b> 13:30-16:00 / 20:30-23:00</p></div>
        <div class="card"><h3>📍 Zona</h3><p>Centro y alrededores.</p></div>
        <div class="card"><h3>💳 Pago</h3><p>Efectivo al recibir tu pedido.</p></div>
    </div></div>
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

def get_db(): return sqlite3.connect('knocktwice.db')

# ============ MENÚ ORIGINAL CON PRECIOS ============
MENU = {
    "pizzas": {
        "titulo": "🍕 PIZZAS",
        "productos": {
            "margarita": {"nombre": "Margarita", "precio": 10, "desc": "Tomate, mozzarella y albahaca fresca.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "trufada": {"nombre": "Trufada", "precio": 14, "desc": "Salsa de trufa, mozzarella y champiñones.", "alergenos": ["LACTEOS", "GLUTEN", "SETAS"]},
            "serranucula": {"nombre": "Serranúcula", "precio": 13, "desc": "Tomate, mozzarella, jamón ibérico y rúcula.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "amatriciana": {"nombre": "Amatriciana", "precio": 12, "desc": "Tomate, mozzarella y bacon.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "pepperoni": {"nombre": "Pepperoni", "precio": 11, "desc": "Tomate, mozzarella y pepperoni.", "alergenos": ["LACTEOS", "GLUTEN"]}
        }
    },
    "burgers": {
        "titulo": "🍔 BURGERS",
        "productos": {
            "classic": {"nombre": "Classic Cheese", "precio": 11, "desc": "Doble carne, queso cheddar, cebolla y salsa especial.", "alergenos": ["LACTEOS", "GLUTEN", "HUEVO", "MOSTAZA", "APIO", "SÉSAMO", "SOJA"]},
            "capone": {"nombre": "Al Capone", "precio": 12, "desc": "Queso de cabra, cebolla caramelizada y rúcula.", "alergenos": ["LACTEOS", "GLUTEN", "FRUTOS_SECOS", "SÉSAMO", "SOJA"]},
            "bacon": {"nombre": "Bacon BBQ", "precio": 12, "desc": "Doble bacon crujiente, cheddar y salsa barbacoa.", "alergenos": ["LACTEOS", "GLUTEN", "MOSTAZA", "APIO", "SÉSAMO", "SOJA"]}
        }
    },
    "postres": {
        "titulo": "🍰 POSTRES",
        "productos": {
            "vinya": {"nombre": "Tarta de La Viña", "precio": 6, "desc": "Nuestra tarta de queso cremosa al horno.", "alergenos": ["LACTEOS", "GLUTEN", "HUEVO"]}
        }
    }
}

FAQ = {
    "horario": {"pregunta": "🕒 Horario", "respuesta": "*HORARIO:*\n• Viernes: 20:30-23:00\n• Sábado: 13:30-16:00 / 20:30-23:00\n• Domingo: 13:30-16:00 / 20:30-23:00"},
    "zona": {"pregunta": "📍 Zona", "respuesta": "Área del centro y alrededores."},
    "alergenos": {"pregunta": "⚠️ Alérgenos", "respuesta": "Se muestran al añadir el producto."},
    "vegetariano": {"pregunta": "🥬 Opciones vegetarianas", "respuesta": "Pizza Margarita, Al Capone y personalizables."},
    "gluten": {"pregunta": "🌾 Sin gluten", "respuesta": "Actualmente no tenemos base sin gluten."},
    "tiempo": {"pregunta": "⏱️ Tiempo", "respuesta": "30-45 minutos normalmente."},
    "pago": {"pregunta": "💳 Pago", "respuesta": "Efectivo al entregar el pedido."},
    "contacto": {"pregunta": "📞 Contacto", "respuesta": "Usa este mismo bot."}
}

# ============ LÓGICA DE TIEMPO (RESTAURADA) ============
TURNOS = {
    "VIERNES": ["20:30", "21:00", "21:15", "21:30", "22:00", "22:15", "22:30"],
    "SABADO": ["13:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00", "15:15", "15:30", "20:30", "21:00", "21:15", "21:30", "22:00", "22:15", "22:30"],
    "DOMINGO": ["13:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00", "15:15", "15:30", "20:30", "21:00", "21:15", "21:30", "22:00", "22:15", "22:30"]
}

def obtener_dia_actual():
    dias = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]
    ahora = datetime.utcnow() + timedelta(hours=1); return dias[ahora.weekday()]

def obtener_hora_actual():
    ahora = datetime.utcnow() + timedelta(hours=1); return ahora.strftime("%H:%M")

def esta_abierto():
    """Verificación de horario real"""
    if MODO_PRUEBAS: return True, ""
    dia = obtener_dia_actual(); hora = obtener_hora_actual()
    if dia not in TURNOS: return False, "Estamos cerrados. Te esperamos de viernes a domingo. 🚪"
    futuros = [h for h in TURNOS[dia] if h > hora]
    if not futuros: return False, "Cocina cerrada por hoy. Te esperamos de viernes a domingo. 🕗"
    return True, ""

# ============ FUNCIONES DE APOYO (RESTAURADAS AL 100%) ============
def registrar_consulta_faq(pregunta):
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO faq_stats (pregunta, veces_preguntada) VALUES (?, COALESCE((SELECT veces_preguntada FROM faq_stats WHERE pregunta=?),0)+1)", (pregunta, pregunta))
    conn.commit(); conn.close()

def verificar_cooldown(user_id):
    if MODO_PRUEBAS: return True, 0
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT ultimo_pedido FROM usuarios WHERE user_id = ?", (user_id,))
    res = c.fetchone(); conn.close()
    if res and res[0]:
        diff = datetime.now() - datetime.fromisoformat(res[0])
        if diff < timedelta(minutes=30): return False, 30 - int(diff.total_seconds() / 60)
    return True, 0

def actualizar_cooldown(user_id, username):
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO usuarios (user_id, username, ultimo_pedido) VALUES (?, ?, ?)", (user_id, username, datetime.now().isoformat()))
    conn.commit(); conn.close()

def guardar_valoracion(pedido_id, user_id, estrellas):
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT INTO valoraciones (pedido_id, user_id, estrellas, fecha) VALUES (?, ?, ?, ?)", (pedido_id, user_id, estrellas, datetime.now().isoformat()))
    c.execute("UPDATE pedidos SET valoracion = ? WHERE id = ?", (estrellas, pedido_id))
    conn.commit(); conn.close()

def obtener_pedidos_sin_valorar(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id, productos FROM pedidos WHERE user_id = ? AND valoracion = 0 ORDER BY fecha DESC LIMIT 3", (user_id,))
    res = c.fetchall(); conn.close(); return res

def obtener_valoracion_promedio():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT AVG(valoracion) FROM pedidos WHERE valoracion > 0")
    res = c.fetchone()[0]; conn.close()
    return round(res, 1) if res else 0.0

def es_admin(user_id):
    return user_id in ADMIN_IDS

def obtener_estadisticas():
    conn = get_db(); c = conn.cursor()
    hoy = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*), SUM(total) FROM pedidos WHERE DATE(fecha) = ?", (hoy,))
    hoy_data = c.fetchone()
    c.execute("SELECT COUNT(*), SUM(total) FROM pedidos")
    total_data = c.fetchone()
    c.execute("SELECT AVG(valoracion) FROM pedidos WHERE valoracion > 0")
    val_avg = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(DISTINCT user_id) FROM pedidos WHERE DATE(fecha) >= DATE('now', '-7 days')")
    activos = c.fetchone()[0]
    conn.close()
    return {'hoy': {'pedidos': hoy_data[0] or 0, 'ventas': hoy_data[1] or 0.0}, 'historico': {'pedidos': total_data[0] or 0, 'ventas': total_data[1] or 0.0}, 'valoracion_promedio': round(val_avg, 1), 'usuarios_activos': activos}

def obtener_pedidos_recientes():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id, username, productos, total, estado, fecha FROM pedidos ORDER BY fecha DESC LIMIT 10")
    res = c.fetchall(); conn.close()
    return res

# ============ HANDLERS DE MENÚ (BOTÓN INICIO ARREGLADO) ============
def start(update: Update, context: CallbackContext, query=None):
    user_id = update.effective_user.id
    if 'carrito' not in context.user_data: context.user_data['carrito'] = []
    context.user_data['esperando_direccion'] = False
    
    val_avg = obtener_valoracion_promedio()
    estrellas = "⭐" * int(val_avg) if val_avg > 0 else "Sin valoraciones"
    
    welcome_text = (f"🚪 **BIENVENIDO A KNOCK TWICE** 🤫\n\n"
                    f"🍕 *Pizza & Burgers de autor*\n"
                    f"⭐ *Valoración: {val_avg}/5 {estrellas}*\n\n"
                    f"*¿Qué deseas hacer?*")
    
    keyboard = [[InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal')],
                [InlineKeyboardButton("🛒 VER MI PEDIDO", callback_data='ver_carrito')],
                [InlineKeyboardButton("❓ PREGUNTAS FRECUENTES", callback_data='faq_menu')],
                [InlineKeyboardButton("⭐ VALORAR PEDIDO", callback_data='valorar_menu')]]
    
    if es_admin(user_id):
        keyboard.append([InlineKeyboardButton("🔧 PANEL ADMIN", callback_data='admin_panel')])

    if query:
        query.edit_message_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def menu_principal(update: Update, context: CallbackContext, query=None):
    keyboard = [[InlineKeyboardButton("🍕 PIZZAS", callback_data='cat_pizzas')],
                [InlineKeyboardButton("🍔 BURGERS", callback_data='cat_burgers')],
                [InlineKeyboardButton("🍰 POSTRES", callback_data='cat_postres')],
                [InlineKeyboardButton("🛒 VER MI PEDIDO", callback_data='ver_carrito')],
                [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
    
    mensaje = "📂 **SELECCIONA UNA CATEGORÍA:**"
    if query: query.edit_message_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else: update.message.reply_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def añadir_al_carrito(update: Update, context: CallbackContext, categoria, producto_id, cantidad):
    query = update.callback_query; query.answer()
    
    # --- BLOQUEO POR HORARIO (MEJORA SOLICITADA) ---
    abierto, msg = esta_abierto()
    if not abierto:
        query.edit_message_text(f"🚫 **LO SENTIMOS**\n\n{msg}", 
                                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 VOLVER A LA CARTA", callback_data='menu_principal')]]), parse_mode='Markdown')
        return

    producto = MENU[categoria]['productos'][producto_id]
    for _ in range(int(cantidad)):
        context.user_data['carrito'].append({'nombre': producto['nombre'], 'precio': producto['precio'], 'categoria': categoria})
    
    query.edit_message_text(f"✅ **{cantidad}x {producto['nombre']}** añadido al carrito.\n\n💰 **Precio unitario: {producto['precio']}€**",
                            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🍽️ SEGUIR PIDIENDO", callback_data=f"cat_{categoria}")],
                                                               [InlineKeyboardButton("🛒 VER MI PEDIDO", callback_data='ver_carrito')],
                                                               [InlineKeyboardButton("🚀 TRAMITAR PEDIDO", callback_data='pedir_direccion')]]), parse_mode='Markdown')

# ============ AVISO PEDIDO EN CAMINO ============
def pedido_en_camino(update: Update, context: CallbackContext):
    """Comando para admins: /camino ID_PEDIDO"""
    user_id = update.effective_user.id
    if not es_admin(user_id): return
    if not context.args:
        update.message.reply_text("Usa: /camino [ID del pedido]")
        return
    
    pedido_id = context.args[0]
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT user_id FROM pedidos WHERE id = ?", (pedido_id,))
    resultado = c.fetchone(); conn.close()
    
    if resultado:
        cliente_id = resultado[0]
        try:
            context.bot.send_message(chat_id=cliente_id, text=f"🛵 **¡TU PEDIDO #{pedido_id} ESTÁ EN CAMINO!**\n\nNuestro repartidor acaba de salir. ¡Ten el efectivo listo! 🤫")
            update.message.reply_text(f"✅ Aviso enviado al cliente del pedido #{pedido_id}")
        except: update.message.reply_text("❌ No se pudo avisar al cliente.")
    else: update.message.reply_text("❌ Pedido no encontrado.")

# ============ HANDLER DE MENSAJES Y RESPUESTA AUTOMÁTICA ============
def handle_message(update: Update, context: CallbackContext):
    if context.user_data.get('esperando_direccion'):
        # Lógica de procesamiento de dirección (Mantenida de tu código)
        context.user_data['direccion'] = update.message.text
        context.user_data['esperando_direccion'] = False
        dia = obtener_dia_actual(); hora = obtener_hora_actual()
        
        if MODO_PRUEBAS:
            turnos_hoy = TURNOS.get(dia, TURNOS["VIERNES"]) 
        else:
            turnos_hoy = [h for h in TURNOS.get(dia, []) if h > hora]

        if turnos_hoy:
            kb = [[InlineKeyboardButton(f"🕒 {h}", callback_data=f"hora_{h}")] for h in turnos_hoy[:8]]
            update.message.reply_text("✅ Dirección guardada. Ahora selecciona hora de entrega:", reply_markup=InlineKeyboardMarkup(kb))
        else:
            update.message.reply_text("❌ Lo sentimos, no quedan turnos para hoy.")
    else:
        # --- RESPUESTA AUTOMÁTICA SI CERRADO ---
        abierto, msg = esta_abierto()
        if not abierto:
            update.message.reply_text(f"👋 ¡Hola! Actualmente estamos cerrados.\n\n{msg}\n\nPuedes ver nuestra carta usando /menu para ir abriendo boca. 🍕", parse_mode='Markdown')
        else:
            update.message.reply_text("Usa los botones o escribe /menu para empezar tu pedido.")

# ============ BOTÓN HANDLER (DEFINITIVO) ============
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query; data = query.data
    if data == 'inicio': query.answer(); start(update, context, query=query)
    elif data == 'menu_principal': menu_principal(update, context, query)
    elif data == 'ver_carrito':
        car = context.user_data.get('carrito', [])
        if not car: query.edit_message_text("🛒 Carrito vacío", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("CARTA", callback_data='menu_principal')]]))
        else:
            total = sum(i['precio'] for i in car)
            txt = "📝 **TU PEDIDO:**\n\n" + "\n".join([f"• {i['nombre']} ({i['precio']}€)" for i in car]) + f"\n\n💰 **TOTAL: {total}€**"
            kb = [[InlineKeyboardButton("📍 PONER DIRECCIÓN", callback_data='pedir_direccion')], [InlineKeyboardButton("🗑️ VACIAR", callback_data='vaciar_carrito')], [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
            query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    elif data == 'pedir_direccion': query.answer(); context.user_data['esperando_direccion'] = True; query.edit_message_text("📍 Escribe tu dirección:")
    elif data == 'vaciar_carrito': context.user_data['carrito'] = []; start(update, context, query=query)
    elif data.startswith('cat_'):
        cat = data.split('_')[1]; kb = [[InlineKeyboardButton(f"{p['nombre']} - {p['precio']}€", callback_data=f"info_{cat}_{pid}")] for pid, p in MENU[cat]['productos'].items()]
        kb.append([InlineKeyboardButton("🔙 VOLVER", callback_data='menu_principal')]); query.edit_message_text(f"👇 **{MENU[cat]['titulo']}**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    elif data.startswith('info_'):
        pt = data.split('_'); p = MENU[pt[1]]['productos'][pt[2]]; txt = f"🍽️ **{p['nombre']}**\n\n_{p['desc']}_\n\n💰 Precio: {p['precio']}€\n⚠️ {', '.join(p['alergenos'])}"; kb = [[InlineKeyboardButton(str(i), callback_data=f"add_{pt[1]}_{pt[2]}_{i}") for i in range(1, 4)], [InlineKeyboardButton("🔙 VOLVER", callback_data=f"cat_{pt[1]}")]]
        query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    elif data.startswith('add_'): pt = data.split('_'); añadir_al_carrito(update, context, pt[1], pt[2], pt[3])
    elif data.startswith('hora_'):
        hora = data.split('_')[1]; user = query.from_user; car = context.user_data.get('carrito', []); total = sum(i['precio'] for i in car); prods = ", ".join([i['nombre'] for i in car])
        conn = get_db(); c = conn.cursor(); c.execute("INSERT INTO pedidos (user_id, username, productos, total, direccion, hora_entrega, fecha) VALUES (?,?,?,?,?,?,?)", (user.id, user.username, prods, total, context.user_data.get('direccion'), hora, datetime.now().isoformat())); p_id = c.lastrowid; conn.commit(); conn.close()
        actualizar_cooldown(user.id, user.username)
        context.bot.send_message(chat_id=ID_GRUPO_PEDIDOS, text=f"🚪 **PEDIDO #{p_id}**\n👤 @{user.username}\n📍 {context.user_data.get('direccion')}\n⏰ {hora}\n🍽️ {prods}\n💰 {total}€")
        context.user_data['carrito'] = []
        query.edit_message_text(f"✅ **¡PEDIDO #{p_id} CONFIRMADO!**\n\nGracias! 🤫")
    elif data == 'admin_panel':
        s = obtener_estadisticas()
        txt = f"📊 **STATS**\nHoy: {s['hoy']['pedidos']} ped. ({s['hoy']['ventas']}€)\n⭐ Media: {s['valoracion_promedio']}/5"
        kb = [[InlineKeyboardButton("📦 PEDIDOS", callback_data='admin_pedidos')], [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
        query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
    elif data == 'admin_pedidos':
        peds = obtener_pedidos_recientes(); txt = "📦 **ÚLTIMOS PEDIDOS:**\n\n" + "\n".join([f"#{p[0]} - @{p[1]} - {p[3]}€" for p in peds])
        query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data='admin_panel')]]))

# ============ SERVIDOR WEB Y ANTISLEEP ============
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-type", "text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(HTML_WEB.encode("utf-8"))
    def log_message(self, format, *args): pass

def keep_alive():
    time.sleep(20)
    while True:
        try: requests.get(URL_PROYECTO, timeout=15)
        except: pass
        time.sleep(840)

# ============ FUNCIÓN PRINCIPAL ============
def main():
    init_db()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthHandler).serve_forever(), daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    updater = Updater(TOKEN, use_context=True); dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", menu_principal))
    dp.add_handler(CommandHandler("camino", pedido_en_camino)) # COMANDO PARA ADMIN
    dp.add_handler(CommandHandler("admin", lambda u, c: start(u, c) if es_admin(u.effective_user.id) else None))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    updater.start_polling(); updater.idle()

if __name__ == "__main__":
    main()
