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
MODO_PRUEBAS = True  # Cámbialo a False para activar restricciones de horario real

# Configuración de administradores
admin_ids_str = os.environ.get("ADMIN_IDS", "")
if admin_ids_str:
    ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip().isdigit()]
else:
    ADMIN_IDS = [123456789] # Tu ID aquí

# ============ BASE DE DATOS ============
def init_db():
    conn = sqlite3.connect('knocktwice.db')
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

# ============ MENÚ Y DATOS ============
MENU = {
    "pizzas": {
        "titulo": "🍕 PIZZAS",
        "productos": {
            "margarita": {"nombre": "Margarita", "precio": 10, "desc": "Tomate, mozzarella y albahaca.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "trufada": {"nombre": "Trufada", "precio": 14, "desc": "Salsa de trufa y champiñones.", "alergenos": ["LACTEOS", "GLUTEN", "SETAS"]},
            "serranucula": {"nombre": "Serranúcula", "precio": 13, "desc": "Jamón ibérico y rúcula.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "pepperoni": {"nombre": "Pepperoni", "precio": 11, "desc": "Mozzarella y pepperoni.", "alergenos": ["LACTEOS", "GLUTEN"]}
        }
    },
    "burgers": {
        "titulo": "🍔 BURGERS",
        "productos": {
            "classic": {"nombre": "Classic Cheese", "precio": 11, "desc": "Doble carne y cheddar.", "alergenos": ["LACTEOS", "GLUTEN", "HUEVO"]},
            "capone": {"nombre": "Al Capone", "precio": 12, "desc": "Queso de cabra y cebolla caramelizada.", "alergenos": ["LACTEOS", "GLUTEN"]}
        }
    },
    "postres": {
        "titulo": "🍰 POSTRES",
        "productos": {
            "vinya": {"nombre": "Tarta de La Viña", "precio": 6, "desc": "Tarta de queso cremosa.", "alergenos": ["LACTEOS", "GLUTEN", "HUEVO"]}
        }
    }
}

FAQ = {
    "horario": {"pregunta": "🕒 Horario", "respuesta": "*VIERNES:* 20:30-23:00\n*SÁB/DOM:* 13:30-16:00 / 20:30-23:00"},
    "zona": {"pregunta": "📍 Zona de entrega", "respuesta": "Centro y alrededores. Consulta al pedir."},
    "alergenos": {"pregunta": "⚠️ Alérgenos", "respuesta": "Se detallan en cada producto al añadir al carrito."}
}

TURNOS = {
    "VIERNES": ["20:30", "21:00", "21:30", "22:00", "22:30"],
    "SABADO": ["13:30", "14:00", "14:30", "15:00", "20:30", "21:00", "21:30", "22:00", "22:30"],
    "DOMINGO": ["13:30", "14:00", "14:30", "15:00", "20:30", "21:00", "21:30", "22:00", "22:30"]
}

# ============ LÓGICA DE TIEMPO ============
def obtener_dia_actual():
    dias = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]
    ahora = datetime.utcnow() + timedelta(hours=1) # Ajuste España
    return dias[ahora.weekday()]

def obtener_hora_actual():
    ahora = datetime.utcnow() + timedelta(hours=1)
    return ahora.strftime("%H:%M")

def esta_abierto():
    if MODO_PRUEBAS: return True, ""
    dia = obtener_dia_actual()
    hora = obtener_hora_actual()
    if dia == "VIERNES" and ("20:30" <= hora <= "23:00"): return True, ""
    if dia in ["SABADO", "DOMINGO"]:
        if ("13:30" <= hora <= "16:00") or ("20:30" <= hora <= "23:00"): return True, ""
    return False, f"Abrimos de Viernes a Domingo en horario de cenas (y comidas Sáb/Dom). ✨"

# ============ MANEJADORES DE MENÚ ============
def mostrar_inicio(update: Update, context: CallbackContext, query=None):
    """Menú de inicio unificado"""
    user_id = update.effective_user.id
    v_promedio = obtener_valoracion_promedio()
    estrellas = "⭐" * int(v_promedio) if v_promedio > 0 else "Nuevo en la zona"
    
    texto = (f"🚪 **KNOCK TWICE** 🤫\n\n"
             f"🍕 *Pizza & Burgers de autor*\n"
             f"⭐ *Valoración:* {v_promedio}/5\n\n"
             f"¿Qué te apetece hoy?")
    
    keyboard = [
        [InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal')],
        [InlineKeyboardButton("🛒 MI PEDIDO", callback_data='ver_carrito')],
        [InlineKeyboardButton("❓ PREGUNTAS", callback_data='faq_menu')],
        [InlineKeyboardButton("⭐ VALORAR", callback_data='valorar_menu')]
    ]
    
    if query:
        query.edit_message_text(texto, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        update.message.reply_text(texto, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def start(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    puede, mins = verificar_cooldown(user_id)
    if not puede:
        update.message.reply_text(f"⏳ **COOLDOWN**: Espera {mins} min para pedir de nuevo.")
        return
    if 'carrito' not in context.user_data: context.user_data['carrito'] = []
    mostrar_inicio(update, context)

def menu_principal(update: Update, context: CallbackContext, query=None):
    abierto, msg = esta_abierto()
    if not abierto:
        txt = f"🚫 **LOCAL CERRADO**\n\n{msg}"
        kb = [[InlineKeyboardButton("🏠 VOLVER", callback_data='inicio')]]
        if query: query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        else: update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        return

    kb = [[InlineKeyboardButton("🍕 PIZZAS", callback_data='cat_pizzas')],
          [InlineKeyboardButton("🍔 BURGERS", callback_data='cat_burgers')],
          [InlineKeyboardButton("🍰 POSTRES", callback_data='cat_postres')],
          [InlineKeyboardButton("🛒 VER MI PEDIDO", callback_data='ver_carrito')],
          [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
    
    if query: query.edit_message_text("📂 **NUESTRA CARTA**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else: update.message.reply_text("📂 **NUESTRA CARTA**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

# ============ FUNCIONES AUXILIARES (DB Y MÁS) ============
def verificar_cooldown(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT ultimo_pedido FROM usuarios WHERE user_id = ?", (user_id,))
    res = c.fetchone(); conn.close()
    if res and res[0]:
        diff = datetime.now() - datetime.fromisoformat(res[0])
        if diff < timedelta(minutes=30): return False, 30 - int(diff.seconds/60)
    return True, 0

def actualizar_cooldown(user_id, username):
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO usuarios (user_id, username, ultimo_pedido) VALUES (?,?,?)",
              (user_id, username, datetime.now().isoformat()))
    conn.commit(); conn.close()

def obtener_valoracion_promedio():
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT AVG(valoracion) FROM pedidos WHERE valoracion > 0")
    res = c.fetchone()[0]; conn.close()
    return round(res, 1) if res else 0.0

def obtener_pedidos_sin_valorar(user_id):
    conn = get_db(); c = conn.cursor()
    c.execute("SELECT id, productos FROM pedidos WHERE user_id=? AND valoracion=0 ORDER BY fecha DESC LIMIT 3", (user_id,))
    res = c.fetchall(); conn.close()
    return res

def guardar_valoracion(pedido_id, user_id, estrellas):
    conn = get_db(); c = conn.cursor()
    c.execute("UPDATE pedidos SET valoracion = ? WHERE id = ?", (estrellas, pedido_id))
    conn.commit(); conn.close()

# ============ FLUJO DE COMPRA ============
def mostrar_categoria(update: Update, context: CallbackContext, cat):
    query = update.callback_query; query.answer()
    kb = [[InlineKeyboardButton(f"{p['nombre']} - {p['precio']}€", callback_data=f"info_{cat}_{pid}")] 
          for pid, p in MENU[cat]['productos'].items()]
    kb.append([InlineKeyboardButton("🔙 VOLVER", callback_data='menu_principal')])
    query.edit_message_text(f"👇 **{MENU[cat]['titulo']}**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def mostrar_info_producto(update: Update, context: CallbackContext, cat, pid):
    query = update.callback_query; query.answer()
    p = MENU[cat]['productos'][pid]
    txt = f"🍽️ **{p['nombre']}**\n_{p['desc']}_\n\n💰 {p['precio']}€\n⚠️ {', '.join(p['alergenos'])}"
    kb = [[InlineKeyboardButton(str(i), callback_data=f"add_{cat}_{pid}_{i}") for i in range(1, 4)],
          [InlineKeyboardButton("🔙 VOLVER", callback_data=f"cat_{cat}")]]
    query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def añadir_al_carrito(update: Update, context: CallbackContext, cat, pid, cant):
    query = update.callback_query; query.answer()
    p = MENU[cat]['productos'][pid]
    for _ in range(int(cant)): context.user_data['carrito'].append({'nombre': p['nombre'], 'precio': p['precio']})
    kb = [[InlineKeyboardButton("🍽️ SEGUIR", callback_data='menu_principal')],
          [InlineKeyboardButton("🚀 TRAMITAR", callback_data='tramitar_pedido')]]
    query.edit_message_text(f"✅ {cant}x {p['nombre']} añadido.", reply_markup=InlineKeyboardMarkup(kb))

def ver_carrito(update: Update, context: CallbackContext, query=None):
    car = context.user_data.get('carrito', [])
    if not car:
        txt, kb = "🛒 Vacío", [[InlineKeyboardButton("🍽️ CARTA", callback_data='menu_principal')]]
    else:
        total = sum(i['precio'] for i in car)
        txt = "📝 **TU PEDIDO**\n\n" + "\n".join([f"• {i['nombre']}" for i in car]) + f"\n\n💰 TOTAL: {total}€"
        kb = [[InlineKeyboardButton("📍 DIRECCIÓN", callback_data='pedir_direccion')],
              [InlineKeyboardButton("🗑️ VACIAR", callback_data='vaciar_carrito')],
              [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]]
    if query: query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else: update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def pedir_direccion(update: Update, context: CallbackContext):
    query = update.callback_query; query.answer()
    context.user_data['esperando_direccion'] = True
    query.edit_message_text("📍 **PASO 1/2**\nEscribe tu dirección completa:")

def procesar_direccion(update: Update, context: CallbackContext):
    if not context.user_data.get('esperando_direccion'): return
    context.user_data['direccion'] = update.message.text
    context.user_data['esperando_direccion'] = False
    dia, hora = obtener_dia_actual(), obtener_hora_actual()
    horarios = [h for h in TURNOS.get(dia, []) if h > hora]
    if horarios:
        kb = [[InlineKeyboardButton(f"🕒 {h}", callback_data=f"hora_{h}")] for h in horarios[:6]]
        update.message.reply_text("⏰ **PASO 2/2**\nSelecciona hora de entrega:", reply_markup=InlineKeyboardMarkup(kb))
    else:
        update.message.reply_text("❌ No hay más turnos hoy.")

def confirmar_hora(update: Update, context: CallbackContext, hora_e):
    query = update.callback_query; query.answer()
    user = query.from_user
    car = context.user_data.get('carrito', [])
    total = sum(i['precio'] for i in car)
    prods = ", ".join([i['nombre'] for i in car])
    
    conn = get_db(); c = conn.cursor()
    c.execute("INSERT INTO pedidos (user_id, username, productos, total, direccion, hora_entrega, fecha) VALUES (?,?,?,?,?,?,?)",
              (user.id, user.username, prods, total, context.user_data.get('direccion'), hora_e, datetime.now().isoformat()))
    p_id = c.lastrowid; conn.commit(); conn.close()
    
    actualizar_cooldown(user.id, user.username)
    context.bot.send_message(ID_GRUPO_PEDIDOS, f"🚪 **PEDIDO #{p_id}**\n👤 @{user.username}\n📍 {context.user_data.get('direccion')}\n⏰ {hora_e}\n🍽️ {prods}\n💰 {total}€")
    
    context.user_data['carrito'] = []
    query.edit_message_text(f"✅ **¡PEDIDO #{p_id} CONFIRMADO!**\n\nPronto estará en camino. 🤫")

# ============ BOTÓN HANDLER CENTRAL ============
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query; data = query.data
    if data == 'inicio': mostrar_inicio(update, context, query)
    elif data == 'menu_principal': menu_principal(update, context, query)
    elif data == 'ver_carrito': ver_carrito(update, context, query)
    elif data == 'tramitar_pedido': pedir_direccion(update, context)
    elif data == 'pedir_direccion': pedir_direccion(update, context)
    elif data == 'vaciar_carrito': 
        context.user_data['carrito'] = []
        mostrar_inicio(update, context, query)
    elif data.startswith('cat_'): mostrar_categoria(update, context, data.split('_')[1])
    elif data.startswith('info_'): mostrar_info_producto(update, context, data.split('_')[1], data.split('_')[2])
    elif data.startswith('add_'): añadir_al_carrito(update, context, data.split('_')[1], data.split('_')[2], data.split('_')[3])
    elif data.startswith('hora_'): confirmar_hora(update, context, data.split('_')[1])
    elif data == 'faq_menu':
        kb = [[InlineKeyboardButton(f['pregunta'], callback_data=f"faq_{k}")] for k, f in FAQ.items()]
        kb.append([InlineKeyboardButton("🔙 VOLVER", callback_data='inicio')])
        query.edit_message_text("❓ **PREGUNTAS**", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('faq_'):
        f = FAQ[data.split('_')[1]]
        query.edit_message_text(f"{f['respuesta']}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 VOLVER", callback_data='faq_menu')]]), parse_mode='Markdown')
    elif data == 'valorar_menu':
        peds = obtener_pedidos_sin_valorar(query.from_user.id)
        if not peds: query.edit_message_text("No tienes pedidos pendientes.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠", callback_data='inicio')]]))
        else:
            kb = [[InlineKeyboardButton(f"Pedido #{p[0]}", callback_data=f"val_p_{p[0]}")] for p in peds]
            query.edit_message_text("⭐ Selecciona pedido:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('val_p_'):
        pid = data.split('_')[2]
        kb = [[InlineKeyboardButton("⭐"*i, callback_data=f"pnt_{pid}_{i}") for i in range(1, 6)]]
        query.edit_message_text(f"Puntúa el pedido #{pid}:", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith('pnt_'):
        guardar_valoracion(data.split('_')[1], query.from_user.id, data.split('_')[2])
        query.edit_message_text("✅ ¡Gracias!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠", callback_data='inicio')]]))

# ============ SERVIDOR WEB Y ANTISLEEP ============
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Bot Online")
    def log_message(self, format, *args): pass

def start_server():
    port = int(os.environ.get("PORT", 10000))
    HTTPServer(('0.0.0.0', port), HealthHandler).serve_forever()

def keep_alive():
    url = "https://knock-twice.onrender.com" # Cambia por tu URL
    time.sleep(20)
    while True:
        try:
            r = requests.get(url, timeout=10)
            print(f"Ping OK: {r.status_code}")
        except: print("Ping fail")
        time.sleep(840) # 14 minutos

# ============ MAIN ============
def main():
    init_db()
    server_t = threading.Thread(target=start_server, daemon=True); server_t.start()
    keep_t = threading.Thread(target=keep_alive, daemon=True); keep_t.start()
    
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, procesar_direccion))
    
    updater.start_polling()
    print("🤖 Bot iniciado y despierto")
    updater.idle()

if __name__ == "__main__":
    main()
