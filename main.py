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
MODO_PRUEBAS = True  # Poner en False para que el bloqueo de horario funcione
URL_PROYECTO = "https://pizzeria-bot-l4y4.onrender.com"
NOMBRE_BOT_ALIAS = "pizzaioloo_bot"

admin_ids_str = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip().isdigit()] if admin_ids_str else [123456789]

# ============ WEB LANDING PAGE PROFESIONAL ============
HTML_WEB = f"""
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Knock Twice | Pizza & Burgers</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;800&display=swap" rel="stylesheet">
    <style>
        :root {{ --primary: #ff4757; --dark: #0f1113; }}
        body {{ margin: 0; font-family: 'Poppins', sans-serif; background: var(--dark); color: white; text-align: center; }}
        .hero {{ height: 100vh; display: flex; flex-direction: column; justify-content: center; align-items: center; 
                 background: linear-gradient(rgba(0,0,0,0.7), rgba(0,0,0,0.7)), url('https://images.unsplash.com/photo-1513104890138-7c749659a591?q=80&w=2000&auto=format&fit=crop');
                 background-size: cover; background-position: center; }}
        h1 {{ font-size: 4rem; margin: 0; text-transform: uppercase; }}
        .btn {{ background: var(--primary); color: white; text-decoration: none; padding: 20px 50px; border-radius: 100px; font-weight: 600; font-size: 1.2rem; transition: 0.3s; box-shadow: 0 10px 30px rgba(255, 71, 87, 0.4); }}
        .btn:hover {{ transform: scale(1.05); background: #ff6b81; }}
        .info {{ padding: 60px 20px; background: white; color: #1e2229; display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 30px; }}
        .card {{ background: #f1f2f6; padding: 30px; border-radius: 20px; }}
    </style>
</head>
<body>
    <div class="hero">
        <h1>KNOCK TWICE 🤫</h1>
        <p>Pizza & Burger de autor. Haz tu pedido a través de nuestro bot oficial.</p>
        <a href="https://t.me/{NOMBRE_BOT_ALIAS}" class="btn">🚀 EMPEZAR PEDIDO</a>
    </div>
    <div class="info">
        <div class="card"><h3>🕒 Horarios</h3><p>Viernes: 20:30-23:00<br>Sáb-Dom: 13:30-16:00 / 20:30-23:00</p></div>
        <div class="card"><h3>📍 Zona</h3><p>Centro y alrededores</p></div>
        <div class="card"><h3>💳 Pago</h3><p>Efectivo al recibir tu pedido</p></div>
    </div>
</body>
</html>
"""

# ============ MENÚ CON PRECIOS Y DESC. ORIGINALES ============
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
    """IMPORTANTE: Si MODO_PRUEBAS es True, ignorará el reloj"""
    if MODO_PRUEBAS: return True, ""
    dia = obtener_dia_actual(); hora = obtener_hora_actual()
    if dia not in TURNOS: return False, "Estamos cerrados. Te esperamos de viernes a domingo. 🚪"
    futuros = [h for h in TURNOS[dia] if h > hora]
    if not futuros: return False, "Hoy ya hemos cerrado la cocina. Te esperamos de viernes a domingo. 🕗"
    return True, ""

# ============ FUNCIONES ADMIN Y ESTADÍSTICAS (RESTAURADAS) ============
def es_admin(user_id): return user_id in ADMIN_IDS

def obtener_estadisticas():
    conn = sqlite3.connect('knocktwice.db'); c = conn.cursor(); hoy = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*), SUM(total) FROM pedidos WHERE DATE(fecha) = ?", (hoy,))
    h = c.fetchone()
    c.execute("SELECT COUNT(*), SUM(total) FROM pedidos")
    t = c.fetchone()
    c.execute("SELECT AVG(valoracion) FROM pedidos WHERE valoracion > 0")
    v = c.fetchone()[0] or 0; conn.close()
    return {'hoy': {'pedidos': h[0] or 0, 'ventas': h[1] or 0.0}, 'historico': {'pedidos': t[0] or 0, 'ventas': t[1] or 0.0}, 'valoracion_promedio': round(v, 1)}

# ============ HANDLERS DE MENÚ (BOTÓN INICIO ARREGLADO) ============
def mostrar_inicio(update: Update, context: CallbackContext, query=None):
    user_id = update.effective_user.id
    if 'carrito' not in context.user_data: context.user_data['carrito'] = []
    
    val_avg = obtener_valoracion_promedio()
    txt = (f"🚪 **BIENVENIDO A KNOCK TWICE** 🤫\n\n"
           f"🍕 *Pizza & Burgers de autor*\n"
           f"⭐ *Valoración: {val_avg}/5*\n\n"
           f"*¿Qué deseas hacer?*")
    
    kb = [[InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal')],
          [InlineKeyboardButton("🛒 MI PEDIDO", callback_data='ver_carrito')],
          [InlineKeyboardButton("❓ PREGUNTAS FRECUENTES", callback_data='faq_menu')],
          [InlineKeyboardButton("⭐ VALORAR PEDIDO", callback_data='valorar_menu')]]
    
    if es_admin(user_id): kb.append([InlineKeyboardButton("🔧 PANEL ADMIN", callback_data='admin_panel')])

    if query: query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else: update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

# ============ LOGICA DE AVISO "PEDIDO EN CAMINO" (RESTAURADA) ============
def pedido_en_camino(update: Update, context: CallbackContext):
    """Comando para admins: /camino ID_PEDIDO"""
    user_id = update.effective_user.id
    if not es_admin(user_id): return
    if not context.args: update.message.reply_text("Usa: /camino ID"); return
    
    pedido_id = context.args[0]
    conn = sqlite3.connect('knocktwice.db'); c = conn.cursor()
    c.execute("SELECT user_id FROM pedidos WHERE id = ?", (pedido_id,))
    res = c.fetchone(); conn.close()
    
    if res:
        cliente_id = res[0]
        try:
            context.bot.send_message(chat_id=cliente_id, text=f"🛵 **¡TU PEDIDO #{pedido_id} ESTÁ EN CAMINO!**\nPrepárate, nuestro repartidor llegará pronto. ¡Que aproveche! 🤫")
            update.message.reply_text(f"✅ Aviso enviado al cliente del pedido #{pedido_id}")
        except: update.message.reply_text("❌ No pude enviar el mensaje al cliente.")
    else: update.message.reply_text("❌ Pedido no encontrado.")

# ============ HANDLER DE BOTONES (PRECIOS RESTAURADOS) ============
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query; data = query.data; query.answer()
    
    if data == 'inicio': mostrar_inicio(update, context, query=query)
    elif data == 'menu_principal':
        kb = [[InlineKeyboardButton("🍕 PIZZAS", callback_data='cat_pizzas')],
              [InlineKeyboardButton("🍔 BURGERS", callback_data='cat_burgers')],
              [InlineKeyboardButton("🍰 POSTRES", callback_data='cat_postres')],
              [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
        query.edit_message_text("📂 **SELECCIONA UNA CATEGORÍA:**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data.startswith('cat_'):
        cat = data.split('_')[1]
        kb = [[InlineKeyboardButton(f"{p['nombre']} - {p['precio']}€", callback_data=f"info_{cat}_{pid}")] for pid, p in MENU[cat]['productos'].items()]
        kb.append([InlineKeyboardButton("🔙 VOLVER", callback_data='menu_principal')])
        query.edit_message_text(f"👇 **{MENU[cat]['titulo']}**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data.startswith('info_'):
        pt = data.split('_'); p = MENU[pt[1]]['productos'][pt[2]]
        txt = f"🍽️ **{p['nombre']}**\n\n_{p['desc']}_\n\n💰 **Precio: {p['precio']}€**\n⚠️ **ALÉRGENOS:** {', '.join(p['alergenos'])}\n\n¿Cuántas quieres?"
        kb = [[InlineKeyboardButton(str(i), callback_data=f"add_{pt[1]}_{pt[2]}_{i}") for i in range(1, 4)],
              [InlineKeyboardButton(str(i), callback_data=f"add_{pt[1]}_{pt[2]}_{i}") for i in range(4, 6)],
              [InlineKeyboardButton("🔙 VOLVER", callback_data=f"cat_{pt[1]}")]]
        query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data.startswith('add_'):
        # BLOQUEO POR HORARIO (MEJORA)
        abierto, msg = esta_abierto()
        if not abierto:
            query.edit_message_text(f"🚫 **LO SENTIMOS**\n\n{msg}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 VOLVER", callback_data='inicio')]]))
            return
        
        pt = data.split('_'); p = MENU[pt[1]]['productos'][pt[2]]; cant = int(pt[3])
        for _ in range(cant): context.user_data['carrito'].append({'nombre': p['nombre'], 'precio': p['precio']})
        query.edit_message_text(f"✅ {cant}x {p['nombre']} añadido.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛒 VER PEDIDO", callback_data='ver_carrito')], [InlineKeyboardButton("🍽️ SEGUIR", callback_data='menu_principal')]]))

    elif data == 'admin_panel':
        s = obtener_estadisticas()
        txt = f"📊 **ESTADÍSTICAS**\nHoy: {s['hoy']['pedidos']} ped. ({s['hoy']['ventas']}€)\n⭐ Valoración: {s['valoracion_promedio']}/5"
        kb = [[InlineKeyboardButton("📦 PEDIDOS RECIENTES", callback_data='admin_pedidos')], [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
        query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

# ============ AUTO-RESPUESTA HORARIO ============
def handle_message(update: Update, context: CallbackContext):
    if context.user_data.get('esperando_direccion'):
        # (Aquí va tu lógica de dirección original...)
        pass
    else:
        abierto, msg = esta_abierto()
        if not abierto:
            update.message.reply_text(f"👋 ¡Hola! Actualmente estamos cerrados.\n\n{msg}\n\nPuedes ver la carta con /menu pero no aceptamos pedidos ahora. 🍕", parse_mode='Markdown')
        else:
            update.message.reply_text("Usa los botones o /menu para pedir.")

# ============ SERVIDOR WEB Y ANTISLEEP ============
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-type", "text/html; charset=utf-8"); self.end_headers()
        self.wfile.write(HTML_WEB.encode("utf-8"))
    def log_message(self, format, *args): pass

def keep_alive():
    time.sleep(15)
    while True:
        try: requests.get(URL_PROYECTO, timeout=15)
        except: pass
        time.sleep(840)

def main():
    init_db()
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthHandler).serve_forever(), daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    
    updater = Updater(TOKEN, use_context=True); dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", lambda u, c: mostrar_inicio(u, c)))
    dp.add_handler(CommandHandler("menu", menu_principal))
    dp.add_handler(CommandHandler("camino", pedido_en_camino))
    dp.add_handler(CommandHandler("admin", lambda u, c: mostrar_inicio(u, c) if es_admin(u.effective_user.id) else None))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    
    updater.start_polling(); updater.idle()

if __name__ == "__main__":
    main()
