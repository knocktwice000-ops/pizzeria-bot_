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
print("="*50)
print("🤖 INICIANDO BOT KNOCK TWICE...")
print("="*50)

ID_GRUPO_PEDIDOS = "-5151917747"
TOKEN = os.environ.get("TELEGRAM_TOKEN")
MODO_PRUEBAS = True  # MODE DEBUG ACTIVADO
URL_PROYECTO = "https://pizzeria-bot-l4y4.onrender.com"
NOMBRE_BOT_ALIAS = "pizzaioloo_bot"

print(f"🔧 TOKEN: {'✅' if TOKEN else '❌ ERROR: No hay token'}")
print(f"🔧 MODO_PRUEBAS: {MODO_PRUEBAS}")

admin_ids_str = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip().isdigit()] if admin_ids_str else [123456789]
print(f"🔧 ADMINS: {ADMIN_IDS}")

# ============ WEB LANDING PAGE ============
HTML_WEB = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Knock Twice | Pizza & Burgers</title>
    <style>
        body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; }}
        h1 {{ color: #ff4757; }}
        .btn {{ display: inline-block; padding: 15px 30px; background: #ff4757; color: white; 
                text-decoration: none; border-radius: 50px; font-weight: bold; margin-top: 20px; }}
    </style>
</head>
<body>
    <h1>🚪 KNOCK TWICE 🤫</h1>
    <p>Pizza & Burger de autor</p>
    <a href="https://t.me/{NOMBRE_BOT_ALIAS}" class="btn">🚀 EMPEZAR PEDIDO</a>
</body>
</html>
"""

# ============ BASE DE DATOS ============
def init_db():
    """Inicializa todas las tablas de la base de datos"""
    try:
        conn = sqlite3.connect('knocktwice.db')
        c = conn.cursor()
        
        # Tabla de pedidos
        c.execute('''CREATE TABLE IF NOT EXISTS pedidos
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_id INTEGER,
                      username TEXT,
                      productos TEXT,
                      total REAL,
                      direccion TEXT,
                      hora_entrega TEXT,
                      estado TEXT DEFAULT 'pendiente',
                      valoracion INTEGER DEFAULT 0,
                      fecha TEXT)''')
        
        # Tabla de usuarios
        c.execute('''CREATE TABLE IF NOT EXISTS usuarios
                     (user_id INTEGER PRIMARY KEY,
                      username TEXT,
                      ultimo_pedido TEXT,
                      puntos INTEGER DEFAULT 0)''')
        
        # Tabla de valoraciones
        c.execute('''CREATE TABLE IF NOT EXISTS valoraciones
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      pedido_id INTEGER,
                      user_id INTEGER,
                      estrellas INTEGER,
                      comentario TEXT,
                      fecha TEXT)''')
        
        # Tabla de FAQ
        c.execute('''CREATE TABLE IF NOT EXISTS faq_stats
                     (pregunta TEXT PRIMARY KEY,
                      veces_preguntada INTEGER DEFAULT 0)''')
        
        conn.commit()
        conn.close()
        print("✅ Base de datos inicializada")
    except Exception as e:
        print(f"❌ Error BD: {e}")

def get_db():
    """Obtiene conexión a la base de datos"""
    return sqlite3.connect('knocktwice.db')

# ============ MENÚ COMPLETO ============
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

# ============ FAQ COMPLETO ============
FAQ = {
    "horario": {
        "pregunta": "🕒 ¿Cuál es vuestro horario?",
        "respuesta": """*HORARIO:*\n• Viernes: 20:30-23:00\n• Sábado: 13:30-16:00 / 20:30-23:00\n• Domingo: 13:30-16:00 / 20:30-23:00"""
    },
    "zona": {
        "pregunta": "📍 ¿Hasta dónde entregáis?",
        "respuesta": "Entregamos en el área del centro y alrededores. Si tienes dudas sobre tu zona, pregunta al hacer el pedido."
    },
    "alergenos": {
        "pregunta": "⚠️ ¿Tenéis información de alérgenos?",
        "respuesta": "Sí, cada producto muestra sus alérgenos antes de añadirlo al carrito. Revisa siempre antes de pedir."
    },
    "vegetariano": {
        "pregunta": "🥬 ¿Opciones vegetarianas?",
        "respuesta": "¡Claro! Pizza Margarita, Al Capone y podemos personalizar cualquier pedido."
    },
    "gluten": {
        "pregunta": "🌾 ¿Opciones sin gluten?",
        "respuesta": "Actualmente no tenemos base sin gluten, pero estamos trabajando en ello."
    },
    "tiempo": {
        "pregunta": "⏱️ ¿Cuánto tarda el pedido?",
        "respuesta": "30-45 minutos normalmente. En horas pico puede tardar un poco más."
    },
    "pago": {
        "pregunta": "💳 ¿Qué métodos de pago aceptáis?",
        "respuesta": "Aceptamos efectivo al entregar el pedido."
    },
    "contacto": {
        "pregunta": "📞 ¿Cómo os contacto?",
        "respuesta": "Por este mismo bot para cualquier consulta sobre pedidos."
    }
}

def registrar_consulta_faq(pregunta):
    """Registra una consulta FAQ"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO faq_stats (pregunta, veces_preguntada)
                 VALUES (?, COALESCE((SELECT veces_preguntada FROM faq_stats WHERE pregunta = ?), 0) + 1)''',
              (pregunta, pregunta))
    conn.commit()
    conn.close()

# ============ SISTEMA SIMPLIFICADO ============
def verificar_cooldown(user_id):
    """Verifica si el usuario puede hacer otro pedido"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT ultimo_pedido FROM usuarios WHERE user_id = ?", (user_id,))
    resultado = c.fetchone()
    conn.close()
    
    if resultado and resultado[0]:
        ultimo_pedido = datetime.fromisoformat(resultado[0])
        if datetime.now() - ultimo_pedido < timedelta(minutes=1):  # 1 minuto en modo pruebas
            return False, 1
    
    return True, 0

def actualizar_cooldown(user_id, username):
    """Actualiza el último pedido del usuario"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO usuarios (user_id, username, ultimo_pedido)
                 VALUES (?, ?, ?)''',
              (user_id, username, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def obtener_valoracion_promedio():
    """Obtiene la valoración promedio"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT AVG(valoracion) FROM pedidos WHERE valoracion > 0")
    resultado = c.fetchone()[0]
    conn.close()
    return round(resultado, 1) if resultado else 0.0

def guardar_valoracion(pedido_id, user_id, estrellas):
    """Guarda una valoración en la base de datos"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO valoraciones (pedido_id, user_id, estrellas, fecha)
                 VALUES (?, ?, ?, ?)''',
              (pedido_id, user_id, estrellas, datetime.now().isoformat()))
    c.execute("UPDATE pedidos SET valoracion = ? WHERE id = ?", (estrellas, pedido_id))
    conn.commit()
    conn.close()

def obtener_pedidos_sin_valorar(user_id):
    """Obtiene pedidos del usuario sin valorar"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT id, productos FROM pedidos 
                 WHERE user_id = ? AND valoracion = 0 AND estado = 'entregado'
                 ORDER BY fecha DESC LIMIT 3''', (user_id,))
    pedidos = c.fetchall()
    conn.close()
    return pedidos

def actualizar_estado_pedido(pedido_id, estado):
    """Actualiza el estado de un pedido"""
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE pedidos SET estado = ? WHERE id = ?", (estado, pedido_id))
    conn.commit()
    conn.close()

def es_admin(user_id):
    return user_id in ADMIN_IDS

# ============ HANDLERS PRINCIPALES ============
def start(update: Update, context: CallbackContext):
    """Comando /start - FUNCIONA CORRECTAMENTE"""
    user = update.effective_user
    user_id = user.id
    
    print(f"🚀 /start de {user.username or user.first_name} (ID: {user_id})")
    
    # Verificar cooldown
    puede_pedir, minutos = verificar_cooldown(user_id)
    if not puede_pedir:
        update.message.reply_text(f"⏳ Espera {minutos} minuto(s) antes de otro pedido.")
        return
    
    # Inicializar carrito
    if 'carrito' not in context.user_data:
        context.user_data['carrito'] = []
    
    valoracion_promedio = obtener_valoracion_promedio()
    estrellas = "⭐" * int(valoracion_promedio) if valoracion_promedio > 0 else "Sin valoraciones"
    
    if MODO_PRUEBAS:
        modo_texto = "\n🔧 *MODO PRUEBAS ACTIVADO* - Sin restricciones\n"
    else:
        modo_texto = ""
    
    txt = (f"🚪 **BIENVENIDO A KNOCK TWICE** 🤫\n\n"
           f"🍕 *Pizza & Burgers de autor*\n"
           f"⭐ *Valoración: {valoracion_promedio}/5 {estrellas}*{modo_texto}\n\n"
           f"*¿Qué deseas hacer?*")
    
    kb = [[InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal')],
          [InlineKeyboardButton("🛒 MI PEDIDO", callback_data='ver_carrito')],
          [InlineKeyboardButton("❓ PREGUNTAS FRECUENTES", callback_data='faq_menu')],
          [InlineKeyboardButton("⭐ VALORAR PEDIDO", callback_data='valorar_menu')]]
    
    if es_admin(user_id):
        kb.append([InlineKeyboardButton("🔧 PANEL ADMIN", callback_data='admin_panel')])
    
    if update.callback_query:
        # Si viene de un botón, editar mensaje
        update.callback_query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    else:
        # Si viene de comando, enviar nuevo mensaje
        update.message.reply_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

def menu_principal(update: Update, context: CallbackContext):
    """Muestra el menú principal"""
    if update.callback_query:
        query = update.callback_query
        query.answer()
        mensaje_func = query.edit_message_text
    else:
        mensaje_func = update.message.reply_text
    
    keyboard = [
        [InlineKeyboardButton("🍕 PIZZAS", callback_data='cat_pizzas')],
        [InlineKeyboardButton("🍔 BURGERS", callback_data='cat_burgers')],
        [InlineKeyboardButton("🍰 POSTRES", callback_data='cat_postres')],
        [InlineKeyboardButton("🛒 VER MI PEDIDO", callback_data='ver_carrito')],
        [InlineKeyboardButton("❓ FAQ", callback_data='faq_menu')],
        [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
    ]
    
    mensaje_func("📂 **SELECCIONA UNA CATEGORÍA:**", 
                reply_markup=InlineKeyboardMarkup(keyboard), 
                parse_mode='Markdown')

def ver_carrito(update: Update, context: CallbackContext):
    """Muestra el carrito"""
    if update.callback_query:
        query = update.callback_query
        query.answer()
        mensaje_func = query.edit_message_text
    else:
        mensaje_func = update.message.reply_text
    
    carrito = context.user_data.get('carrito', [])
    
    if not carrito:
        mensaje = "🛒 **TU CESTA ESTÁ VACÍA**"
        keyboard = [[InlineKeyboardButton("🍽️ IR A LA CARTA", callback_data='menu_principal')]]
    else:
        productos_agrupados = {}
        total = 0
        
        for item in carrito:
            nombre = item['nombre']
            precio = item['precio']
            total += precio
            
            if nombre in productos_agrupados:
                productos_agrupados[nombre]['cantidad'] += 1
                productos_agrupados[nombre]['subtotal'] += precio
            else:
                productos_agrupados[nombre] = {
                    'cantidad': 1,
                    'precio': precio,
                    'subtotal': precio
                }
        
        mensaje = "📝 **TU PEDIDO:**\n\n"
        for nombre, info in productos_agrupados.items():
            mensaje += f"▪️ {info['cantidad']}x {nombre} ... {info['subtotal']}€\n"
        
        mensaje += f"\n💰 **TOTAL:** {total}€\n\n"
        mensaje += "👇 Para continuar, necesitamos tu dirección de entrega."
        
        keyboard = [
            [InlineKeyboardButton("📍 PONER DIRECCIÓN", callback_data='pedir_direccion')],
            [InlineKeyboardButton("🗑️ VACIAR CESTA", callback_data='vaciar_carrito')],
            [InlineKeyboardButton("🍽️ SEGUIR PIDIENDO", callback_data='menu_principal')]
        ]
    
    mensaje_func(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def pedir_direccion(update: Update, context: CallbackContext):
    """Solicita la dirección"""
    query = update.callback_query
    query.answer()
    
    context.user_data['esperando_direccion'] = True
    
    query.edit_message_text(
        "📍 **PASO 1/2: DIRECCIÓN DE ENTREGA**\n\n"
        "Por favor, escribe tu dirección completa para la entrega:\n\n"
        "✍️ _Ejemplo: Calle Principal 123, Piso 2A_",
        parse_mode='Markdown'
    )

def procesar_direccion(update: Update, context: CallbackContext):
    """Procesa la dirección ingresada"""
    if not context.user_data.get('esperando_direccion', False):
        return
    
    direccion = update.message.text
    context.user_data['direccion'] = direccion
    context.user_data['esperando_direccion'] = False
    
    # En modo pruebas, mostrar horarios ficticios
    keyboard = []
    horas = ["20:30", "21:00", "21:15", "21:30", "22:00", "22:15", "22:30"]
    for hora in horas[:8]:
        keyboard.append([InlineKeyboardButton(f"🕒 {hora}", callback_data=f"hora_{hora}")])
    
    keyboard.append([InlineKeyboardButton("🔙 VOLVER", callback_data='ver_carrito')])
    
    update.message.reply_text(
        f"✅ **Dirección guardada.**\n\n"
        f"⏰ **SELECCIONA HORA DE ENTREGA:**\n"
        f"(Modo pruebas - todos horarios disponibles)",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def confirmar_hora(update: Update, context: CallbackContext, hora_elegida):
    """Confirma el pedido con la hora seleccionada"""
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    usuario = query.from_user
    
    # Verificar cooldown
    puede_pedir, minutos = verificar_cooldown(user_id)
    if not puede_pedir:
        query.edit_message_text(f"⏳ Espera {minutos} minuto(s)")
        return
    
    carrito = context.user_data.get('carrito', [])
    direccion = context.user_data.get('direccion', 'No especificada')
    
    if not carrito:
        query.edit_message_text("❌ El carrito está vacío")
        return
    
    # Calcular total y productos
    productos_agrupados = {}
    total = 0
    
    for item in carrito:
        nombre = item['nombre']
        precio = item['precio']
        total += precio
        
        if nombre in productos_agrupados:
            productos_agrupados[nombre] += 1
        else:
            productos_agrupados[nombre] = 1
    
    productos_str = ", ".join([f"{cant}x {nombre}" for nombre, cant in productos_agrupados.items()])
    texto_pedido = "".join([f"- {cant}x {nombre}\n" for nombre, cant in productos_agrupados.items()])
    
    # Guardar en BD
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO pedidos (user_id, username, productos, total, direccion, hora_entrega, estado, fecha)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (usuario.id, usuario.username, productos_str, total, direccion, 
               hora_elegida, "pendiente", datetime.now().isoformat()))
    
    pedido_id = c.lastrowid
    conn.commit()
    conn.close()
    
    # Actualizar cooldown
    actualizar_cooldown(usuario.id, usuario.username)
    
    # Enviar al grupo con ambos botones
    try:
        keyboard = [
            [InlineKeyboardButton("🛵 PEDIDO EN CAMINO", callback_data=f"camino_{pedido_id}")],
            [InlineKeyboardButton("✅ ENTREGADO", callback_data=f"entregado_{pedido_id}")]
        ]
        
        mensaje_grupo = (f"🚪 **NUEVO PEDIDO #{pedido_id}** 🚪\n\n"
                         f"👤 Cliente: @{usuario.username or usuario.first_name}\n"
                         f"⏰ Hora: {hora_elegida}\n"
                         f"📍 Dirección: {direccion}\n"
                         f"🍽️ Comanda:\n{texto_pedido}"
                         f"💰 Total: {total}€\n"
                         f"➖➖➖➖➖➖➖➖➖➖")
        
        context.bot.send_message(
            chat_id=ID_GRUPO_PEDIDOS,
            text=mensaje_grupo,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        print(f"✅ Pedido #{pedido_id} enviado al grupo con ambos botones")
    except Exception as e:
        print(f"❌ Error enviando al grupo: {e}")
    
    # Limpiar carrito y mostrar confirmación
    context.user_data['carrito'] = []
    context.user_data['direccion'] = None
    
    query.edit_message_text(
        f"✅ **¡PEDIDO #{pedido_id} CONFIRMADO!**\n\n"
        f"🕒 *Hora:* {hora_elegida}\n"
        f"💰 *Total:* {total}€\n\n"
        f"¡Gracias por confiar en Knock Twice! 🤫\n\n"
        f"⭐ *Recuerda:* Te pediremos valoración cuando te llegue",
        parse_mode='Markdown'
    )

def vaciar_carrito(update: Update, context: CallbackContext):
    """Vacía el carrito"""
    query = update.callback_query
    query.answer()
    
    context.user_data['carrito'] = []
    context.user_data['esperando_direccion'] = False
    
    query.edit_message_text(
        "🗑️ **CESTA VACIADA**\n\n"
        "Tu carrito ha sido vaciado.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal')],
            [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
        ]),
        parse_mode='Markdown'
    )

# ============ FAQ HANDLERS ============
def faq_menu(update: Update, context: CallbackContext):
    """Menú de FAQ"""
    if update.callback_query:
        query = update.callback_query
        query.answer()
        mensaje_func = query.edit_message_text
    else:
        mensaje_func = update.message.reply_text
    
    keyboard = []
    for key, faq in FAQ.items():
        keyboard.append([InlineKeyboardButton(faq["pregunta"], callback_data=f"faq_{key}")])
    
    keyboard.append([
        InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal'),
        InlineKeyboardButton("🏠 INICIO", callback_data='inicio')
    ])
    
    mensaje_func(
        "❓ **PREGUNTAS FRECUENTES**\n\nSelecciona una pregunta:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def mostrar_faq(update: Update, context: CallbackContext, faq_key):
    """Muestra una FAQ específica"""
    query = update.callback_query
    query.answer()
    
    if faq_key not in FAQ:
        query.edit_message_text("❌ Pregunta no encontrada")
        return
    
    registrar_consulta_faq(FAQ[faq_key]["pregunta"])
    faq = FAQ[faq_key]
    
    query.edit_message_text(
        f"{faq['respuesta']}\n\n"
        f"_¿Te ha resuelto la duda?_",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ SÍ", callback_data='faq_util_si'),
             InlineKeyboardButton("❌ NO", callback_data='faq_util_no')],
            [InlineKeyboardButton("🔙 VOLVER A FAQ", callback_data='faq_menu')]
        ]),
        parse_mode='Markdown'
    )

def feedback_faq(update: Update, context: CallbackContext, util):
    """Procesa feedback de FAQ"""
    query = update.callback_query
    query.answer()
    
    if util == 'si':
        mensaje = "✅ ¡Gracias por tu feedback!"
    else:
        mensaje = "❌ Lamentamos no haberte ayudado."
    
    query.edit_message_text(
        mensaje,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 VOLVER A FAQ", callback_data='faq_menu')],
            [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
        ]),
        parse_mode='Markdown'
    )

# ============ VALORACIONES ============
def valorar_menu(update: Update, context: CallbackContext):
    """Menú de valoraciones"""
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    pedidos_sin_valorar = obtener_pedidos_sin_valorar(user_id)
    
    print(f"📊 Valorar menu - User: {user_id}, Pedidos sin valorar: {len(pedidos_sin_valorar)}")
    
    if not pedidos_sin_valorar:
        query.edit_message_text(
            "⭐ **NO HAY PEDIDOS PENDIENTES DE VALORAR**\n\n"
            "¡Gracias por tu apoyo!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🍽️ HACER PEDIDO", callback_data='menu_principal')],
                [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
            ]),
            parse_mode='Markdown'
        )
        return
    
    keyboard = []
    for pedido in pedidos_sin_valorar:
        pedido_id = pedido[0]
        productos = pedido[1]
        if len(productos) > 30:
            productos = productos[:27] + "..."
        
        keyboard.append([
            InlineKeyboardButton(f"📦 Pedido #{pedido_id}", callback_data=f"valorar_pedido_{pedido_id}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 VOLVER", callback_data='inicio')])
    
    query.edit_message_text(
        "⭐ **VALORA TUS PEDIDOS**\n\n"
        "Selecciona un pedido para valorar:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def mostrar_valoracion_pedido(update: Update, context: CallbackContext, pedido_id):
    """Muestra opciones de valoración"""
    query = update.callback_query
    query.answer()
    
    mensaje = f"⭐ **VALORAR PEDIDO #{pedido_id}**\n\n¿Cómo calificarías tu experiencia?"
    
    keyboard = [
        [
            InlineKeyboardButton("⭐", callback_data=f"puntuar_{pedido_id}_1"),
            InlineKeyboardButton("⭐⭐", callback_data=f"puntuar_{pedido_id}_2"),
            InlineKeyboardButton("⭐⭐⭐", callback_data=f"puntuar_{pedido_id}_3")
        ],
        [
            InlineKeyboardButton("⭐⭐⭐⭐", callback_data=f"puntuar_{pedido_id}_4"),
            InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data=f"puntuar_{pedido_id}_5")
        ],
        [InlineKeyboardButton("🔙 VOLVER", callback_data='valorar_menu')]
    ]
    
    query.edit_message_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard))

def procesar_valoracion(update: Update, context: CallbackContext, pedido_id, estrellas):
    """Procesa la valoración"""
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    guardar_valoracion(pedido_id, user_id, estrellas)
    
    valoracion_promedio = obtener_valoracion_promedio()
    
    query.edit_message_text(
        f"✅ **¡VALORACIÓN REGISTRADA!**\n\n"
        f"⭐ Has dado {estrellas} estrellas\n"
        f"📊 Valoración promedio: {valoracion_promedio}/5\n\n"
        f"¡Gracias por tu opinión!",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🍽️ HACER OTRO PEDIDO", callback_data='menu_principal')],
            [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
        ]),
        parse_mode='Markdown'
    )
    print(f"✅ Valoración guardada: Pedido #{pedido_id}, {estrellas} estrellas")

# ============ BOTONES ADMIN ============
def pedido_en_camino_boton(update: Update, context: CallbackContext, pedido_id):
    """Botón para notificar que el pedido está en camino"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not es_admin(user_id):
        query.answer("❌ Solo para administradores", show_alert=True)
        return
    
    query.answer()
    
    # Buscar el pedido
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM pedidos WHERE id = ?", (pedido_id,))
    res = c.fetchone()
    conn.close()
    
    if res:
        cliente_id = res[0]
        try:
            # Notificar al cliente
            context.bot.send_message(
                chat_id=cliente_id, 
                text=f"🛵 **¡TU PEDIDO #{pedido_id} ESTÁ EN CAMINO!**\n\n"
                     f"Prepárate, nuestro repartidor llegará pronto.\n"
                     f"¡Que aproveche! 🤫"
            )
            
            # Actualizar estado
            actualizar_estado_pedido(pedido_id, "en_camino")
            
            # Actualizar mensaje en grupo
            query.edit_message_text(
                query.message.text + f"\n\n✅ **En camino a las {datetime.now().strftime('%H:%M')}**",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ EN CAMINO", callback_data="ya_camino"),
                    InlineKeyboardButton("✅ ENTREGADO", callback_data=f"entregado_{pedido_id}")
                ]])
            )
            print(f"✅ Pedido #{pedido_id} marcado como 'en camino'")
            
        except Exception as e:
            print(f"❌ Error notificando cliente: {e}")
            query.answer(f"❌ Error: {str(e)[:50]}", show_alert=True)
    else:
        query.answer("❌ Pedido no encontrado", show_alert=True)

def pedido_entregado_boton(update: Update, context: CallbackContext, pedido_id):
    """Botón para notificar que el pedido ha sido entregado"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not es_admin(user_id):
        query.answer("❌ Solo para administradores", show_alert=True)
        return
    
    query.answer()
    
    # Buscar el pedido
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id, productos, total FROM pedidos WHERE id = ?", (pedido_id,))
    res = c.fetchone()
    conn.close()
    
    if res:
        cliente_id = res[0]
        productos = res[1]
        total = res[2]
        
        try:
            # Notificar al cliente que su pedido ha sido entregado
            context.bot.send_message(
                chat_id=cliente_id, 
                text=f"✅ **¡TU PEDIDO #{pedido_id} HA SIDO ENTREGADO!**\n\n"
                     f"🍽️ *Resumen:*\n{productos}\n"
                     f"💰 *Total:* {total}€\n\n"
                     f"⭐ *¿Cómo valorarías tu experiencia?*\n"
                     f"Usa el botón de abajo para valorar ahora mismo:\n\n",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⭐ VALORAR ESTE PEDIDO", callback_data=f"valorar_pedido_{pedido_id}")
                ]]),
                parse_mode='Markdown'
            )
            
            # Actualizar estado
            actualizar_estado_pedido(pedido_id, "entregado")
            
            # Actualizar mensaje en grupo
            query.edit_message_text(
                query.message.text + f"\n\n✅ **Entregado a las {datetime.now().strftime('%H:%M')}**",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ ENTREGADO", callback_data="ya_entregado")
                ]])
            )
            print(f"✅ Pedido #{pedido_id} marcado como 'entregado' y cliente notificado")
            
        except Exception as e:
            print(f"❌ Error notificando entrega: {e}")
            query.answer(f"❌ Error: {str(e)[:50]}", show_alert=True)
    else:
        query.answer("❌ Pedido no encontrado", show_alert=True)

# ============ PANEL ADMIN ============
def admin_panel(update: Update, context: CallbackContext):
    """Panel de administración"""
    if update.callback_query:
        query = update.callback_query
        query.answer()
        mensaje_func = query.edit_message_text
    else:
        mensaje_func = update.message.reply_text
    
    conn = get_db()
    c = conn.cursor()
    
    # Pedidos de hoy
    hoy = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*), SUM(total) FROM pedidos WHERE DATE(fecha) = ?", (hoy,))
    pedidos_hoy = c.fetchone()
    
    # Total histórico
    c.execute("SELECT COUNT(*), SUM(total) FROM pedidos")
    total_historico = c.fetchone()
    
    # Valoración promedio
    c.execute("SELECT AVG(valoracion) FROM pedidos WHERE valoracion > 0")
    valoracion_promedio = c.fetchone()[0] or 0
    
    conn.close()
    
    mensaje = (
        "🔧 **PANEL DE ADMINISTRACIÓN**\n\n"
        "📅 *HOY:*\n"
        f"• Pedidos: {pedidos_hoy[0] or 0}\n"
        f"• Ventas: {pedidos_hoy[1] or 0:.2f}€\n\n"
        
        "📈 *TOTAL HISTÓRICO:*\n"
        f"• Pedidos: {total_historico[0] or 0}\n"
        f"• Ventas: {total_historico[1] or 0:.2f}€\n\n"
        
        f"⭐ *VALORACIÓN PROMEDIO:* {round(valoracion_promedio, 1) or 0.0}/5\n"
        f"🔧 *Modo pruebas:* {'✅ ACTIVADO' if MODO_PRUEBAS else '❌ DESACTIVADO'}\n\n"
        
        f"⏰ *Hora:* {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    )
    
    keyboard = [
        [InlineKeyboardButton("📦 PEDIDOS RECIENTES", callback_data='admin_pedidos')],
        [InlineKeyboardButton("🔄 ACTUALIZAR", callback_data='admin_panel')],
        [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
    ]
    
    mensaje_func(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def mostrar_pedidos_recientes(update: Update, context: CallbackContext):
    """Muestra pedidos recientes"""
    query = update.callback_query
    query.answer()
    
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT id, username, productos, total, estado, fecha 
                 FROM pedidos ORDER BY fecha DESC LIMIT 10''')
    pedidos = c.fetchall()
    conn.close()
    
    if not pedidos:
        mensaje = "📭 No hay pedidos recientes."
    else:
        mensaje = "📦 **PEDIDOS RECIENTES**\n\n"
        
        for i, pedido in enumerate(pedidos, 1):
            estado_icono = "✅" if pedido[4] == 'entregado' else "🛵" if pedido[4] == 'en_camino' else "🔄"
            fecha = datetime.fromisoformat(pedido[5]).strftime("%H:%M")
            
            mensaje += (
                f"{i}. *#{pedido[0]}* {estado_icono}\n"
                f"   👤 {pedido[1] or 'Anónimo'}\n"
                f"   🍽️ {pedido[2][:30]}...\n"
                f"   💰 {pedido[3]}€ • {fecha}\n\n"
            )
    
    keyboard = [
        [InlineKeyboardButton("🔙 PANEL ADMIN", callback_data='admin_panel')],
        [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
    ]
    
    query.edit_message_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# ============ HANDLER DE BOTONES COMPLETO ============
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    query.answer()
    
    print(f"🔘 Botón: {data}")
    
    # Navegación principal - BOTÓN INICIO CORREGIDO
    if data == 'inicio':
        print("🔄 Botón INICIO pulsado")
        try:
            start(update, context)
        except Exception as e:
            print(f"❌ Error en inicio: {e}")
            query.answer("⏳ Cargando...")
    
    elif data == 'menu_principal':
        menu_principal(update, context)
    
    elif data == 'ver_carrito':
        ver_carrito(update, context)
    
    elif data == 'tramitar_pedido':
        pedir_direccion(update, context)
    
    elif data == 'pedir_direccion':
        pedir_direccion(update, context)
    
    elif data == 'vaciar_carrito':
        vaciar_carrito(update, context)
    
    # Categorías
    elif data.startswith('cat_'):
        categoria = data.split('_')[1]
        kb = [[InlineKeyboardButton(f"{p['nombre']} - {p['precio']}€", callback_data=f"info_{categoria}_{pid}")] 
              for pid, p in MENU[categoria]['productos'].items()]
        kb.append([InlineKeyboardButton("🔙 VOLVER", callback_data='menu_principal')])
        query.edit_message_text(f"👇 **{MENU[categoria]['titulo']}**", 
                              reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    # Info producto
    elif data.startswith('info_'):
        partes = data.split('_')
        categoria = partes[1]
        producto_id = partes[2]
        producto = MENU[categoria]['productos'][producto_id]
        
        txt = f"🍽️ **{producto['nombre']}**\n\n_{producto['desc']}_\n\n💰 **Precio: {producto['precio']}€**\n⚠️ **ALÉRGENOS:** {', '.join(producto['alergenos'])}\n\n¿Cuántas quieres?"
        kb = [[InlineKeyboardButton(str(i), callback_data=f"add_{categoria}_{producto_id}_{i}") for i in range(1, 4)],
              [InlineKeyboardButton(str(i), callback_data=f"add_{categoria}_{producto_id}_{i}") for i in range(4, 6)],
              [InlineKeyboardButton("🔙 VOLVER", callback_data=f"cat_{categoria}")]]
        query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    # Añadir al carrito
    elif data.startswith('add_'):
        partes = data.split('_')
        categoria = partes[1]
        producto_id = partes[2]
        cantidad = int(partes[3])
        producto = MENU[categoria]['productos'][producto_id]
        
        if 'carrito' not in context.user_data:
            context.user_data['carrito'] = []
        
        for _ in range(cantidad):
            context.user_data['carrito'].append({
                'nombre': producto['nombre'],
                'precio': producto['precio'],
                'categoria': categoria
            })
        
        query.edit_message_text(
            f"✅ **{cantidad}x {producto['nombre']}** añadido(s) al carrito.\n\n"
            f"¿Qué quieres hacer ahora?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🍽️ SEGUIR PIDIENDO", callback_data=f"cat_{categoria}")],
                [InlineKeyboardButton("🛒 VER MI PEDIDO", callback_data='ver_carrito')],
                [InlineKeyboardButton("🚀 TRAMITAR PEDIDO", callback_data='tramitar_pedido')]
            ]),
            parse_mode='Markdown'
        )
    
    # Hora
    elif data.startswith('hora_'):
        hora = data.split('_')[1]
        confirmar_hora(update, context, hora)
    
    # FAQ
    elif data == 'faq_menu':
        faq_menu(update, context)
    
    elif data.startswith('faq_'):
        if data.startswith('faq_util_'):
            util = data.split('_')[2]
            feedback_faq(update, context, util)
        else:
            faq_key = data.split('_')[1]
            mostrar_faq(update, context, faq_key)
    
    # Valoraciones
    elif data == 'valorar_menu':
        valorar_menu(update, context)
    
    elif data.startswith('valorar_pedido_'):
        pedido_id = int(data.split('_')[2])
        mostrar_valoracion_pedido(update, context, pedido_id)
    
    elif data.startswith('puntuar_'):
        partes = data.split('_')
        pedido_id = int(partes[1])
        estrellas = int(partes[2])
        procesar_valoracion(update, context, pedido_id, estrellas)
    
    # Botones admin
    elif data.startswith('camino_'):
        pedido_id = int(data.split('_')[1])
        pedido_en_camino_boton(update, context, pedido_id)
    
    elif data.startswith('entregado_'):
        pedido_id = int(data.split('_')[1])
        pedido_entregado_boton(update, context, pedido_id)
    
    elif data in ['ya_camino', 'ya_entregado']:
        query.answer("✓")
    
    # Admin panel
    elif data == 'admin_panel':
        admin_panel(update, context)
    
    elif data == 'admin_pedidos':
        mostrar_pedidos_recientes(update, context)
    
    else:
        query.answer("Opción no disponible")

# ============ HANDLER MENSAJES ============
def handle_message(update: Update, context: CallbackContext):
    """Maneja mensajes de texto"""
    if context.user_data.get('esperando_direccion'):
        procesar_direccion(update, context)
    else:
        ayuda_text = (
            "🆘 **AYUDA DE KNOCK TWICE**\n\n"
            "*Para navegar usa los botones o estos comandos:*\n\n"
            "• /start - Iniciar el bot\n"
            "• /menu - Ver la carta completa\n"
            "• /pedido - Ver tu carrito actual\n"
            "• /faq - Preguntas frecuentes\n"
            "• /valorar - Valorar tus pedidos\n"
            "• /ayuda - Esta información\n\n"
            "¡Usa los botones para una navegación más fácil!"
        )
        
        update.message.reply_text(ayuda_text, parse_mode='Markdown')

# ============ COMANDOS ============
def comando_menu(update: Update, context: CallbackContext):
    menu_principal(update, context)

def comando_pedido(update: Update, context: CallbackContext):
    ver_carrito(update, context)

def comando_faq(update: Update, context: CallbackContext):
    faq_menu(update, context)

def comando_valorar(update: Update, context: CallbackContext):
    valorar_menu(update, context)

def comando_admin(update: Update, context: CallbackContext):
    if es_admin(update.effective_user.id):
        admin_panel(update, context)
    else:
        update.message.reply_text("❌ Comando no disponible.")

def comando_ayuda(update: Update, context: CallbackContext):
    handle_message(update, context)

# ============ SERVIDOR WEB ============
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML_WEB.encode("utf-8"))
    
    def log_message(self, format, *args):
        print(f"🌐 Web: {args[0]} {args[1]}")

def keep_alive():
    time.sleep(10)
    while True:
        try:
            requests.get(URL_PROYECTO, timeout=10)
            print("✅ Ping enviado")
        except:
            print("⚠️ Error ping")
        time.sleep(300)

def main():
    print("🚀 Iniciando bot...")
    init_db()
    
    if not TOKEN:
        print("❌ ERROR: No hay TELEGRAM_TOKEN")
        return
    
    # Servidor web
    threading.Thread(target=lambda: HTTPServer(('0.0.0.0', int(os.environ.get("PORT", 10000))), HealthHandler).serve_forever(), daemon=True).start()
    print("✅ Servidor web iniciado")
    
    # Keep-alive
    threading.Thread(target=keep_alive, daemon=True).start()
    
    # Bot
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # Handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", comando_menu))
    dp.add_handler(CommandHandler("pedido", comando_pedido))
    dp.add_handler(CommandHandler("faq", comando_faq))
    dp.add_handler(CommandHandler("valorar", comando_valorar))
    dp.add_handler(CommandHandler("admin", comando_admin))
    dp.add_handler(CommandHandler("ayuda", comando_ayuda))
    
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    
    print("="*50)
    print("🎉 BOT KNOCK TWICE ACTIVO!")
    print(f"🔧 Modo pruebas: {'✅ ACTIVADO' if MODO_PRUEBAS else '❌ DESACTIVADO'}")
    print(f"📊 Todas las pizzas restauradas: {len(MENU['pizzas']['productos'])}")
    print(f"📚 FAQ completo: {len(FAQ)} preguntas")
    print(f"🛵✅ Botones: PEDIDO EN CAMINO y ENTREGADO activos")
    print(f"🏠 Botón INICIO funcionando correctamente")
    print("="*50)
    
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
