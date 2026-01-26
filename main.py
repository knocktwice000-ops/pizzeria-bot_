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
MODO_PRUEBAS = True

# Configuración de administradores
admin_ids_str = os.environ.get("ADMIN_IDS", "")
if admin_ids_str:
    ADMIN_IDS = [int(id.strip()) for id in admin_ids_str.split(",") if id.strip().isdigit()]
else:
    ADMIN_IDS = [123456789]  # Cambia este ID por el tuyo

print(f"🤖 Bot iniciado | Admins: {ADMIN_IDS}")

# ============ BASE DE DATOS ============
def init_db():
    """Inicializa todas las tablas de la base de datos"""
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

def get_db():
    """Obtiene conexión a la base de datos"""
    return sqlite3.connect('knocktwice.db')

# ============ MENÚ CON ALÉRGENOS ============
MENU = {
    "pizzas": {
        "titulo": "🍕 PIZZAS",
        "productos": {
            "margarita": {
                "nombre": "Margarita",
                "precio": 10,
                "desc": "Tomate, mozzarella y albahaca fresca.",
                "alergenos": ["LACTEOS", "GLUTEN"]
            },
            "trufada": {
                "nombre": "Trufada",
                "precio": 14,
                "desc": "Salsa de trufa, mozzarella y champiñones.",
                "alergenos": ["LACTEOS", "GLUTEN", "SETAS"]
            },
            "serranucula": {
                "nombre": "Serranúcula",
                "precio": 13,
                "desc": "Tomate, mozzarella, jamón ibérico y rúcula.",
                "alergenos": ["LACTEOS", "GLUTEN"]
            },
            "amatriciana": {
                "nombre": "Amatriciana",
                "precio": 12,
                "desc": "Tomate, mozzarella y bacon.",
                "alergenos": ["LACTEOS", "GLUTEN"]
            },
            "pepperoni": {
                "nombre": "Pepperoni",
                "precio": 11,
                "desc": "Tomate, mozzarella y pepperoni.",
                "alergenos": ["LACTEOS", "GLUTEN"]
            }
        }
    },
    "burgers": {
        "titulo": "🍔 BURGERS",
        "productos": {
            "classic": {
                "nombre": "Classic Cheese",
                "precio": 11,
                "desc": "Doble carne, queso cheddar, cebolla y salsa especial.",
                "alergenos": ["LACTEOS", "GLUTEN", "HUEVO", "MOSTAZA", "APIO", "SÉSAMO", "SOJA"]
            },
            "capone": {
                "nombre": "Al Capone",
                "precio": 12,
                "desc": "Queso de cabra, cebolla caramelizada y rúcula.",
                "alergenos": ["LACTEOS", "GLUTEN", "FRUTOS_SECOS", "SÉSAMO", "SOJA"]
            },
            "bacon": {
                "nombre": "Bacon BBQ",
                "precio": 12,
                "desc": "Doble bacon crujiente, cheddar y salsa barbacoa.",
                "alergenos": ["LACTEOS", "GLUTEN", "MOSTAZA", "APIO", "SÉSAMO", "SOJA"]
            }
        }
    },
    "postres": {
        "titulo": "🍰 POSTRES",
        "productos": {
            "vinya": {
                "nombre": "Tarta de La Viña",
                "precio": 6,
                "desc": "Nuestra tarta de queso cremosa al horno.",
                "alergenos": ["LACTEOS", "GLUTEN", "HUEVO"]
            }
        }
    }
}

# ============ PREGUNTAS FRECUENTES ============
FAQ = {
    "horario": {
        "pregunta": "🕒 ¿Cuál es vuestro horario?",
        "respuesta": """*HORARIO:*\n• Viernes: 20:30-23:00\n• Sábado: 13:30-16:00 / 20:30-23:00\n• Domingo: 13:30-16:00 / 20:30-23:00"""
    },
    "zona": {
        "pregunta": "📍 ¿Hasta dónde entregáis?",
        "respuesta": "Entregamos en el centro histórico de Bilbao (radio 3km)."
    },
    "alergenos": {
        "pregunta": "⚠️ ¿Tenéis información de alérgenos?",
        "respuesta": "Sí, cada producto muestra sus alérgenos antes de añadirlo al carrito."
    },
    "vegetariano": {
        "pregunta": "🥬 ¿Opciones vegetarianas?",
        "respuesta": "¡Claro! Pizza Margarita, Al Capone y personalizaciones."
    },
    "gluten": {
        "pregunta": "🌾 ¿Opciones sin gluten?",
        "respuesta": "Actualmente no tenemos base sin gluten. ¡Pronto!"
    },
    "tiempo": {
        "pregunta": "⏱️ ¿Cuánto tarda el pedido?",
        "respuesta": "30-45 minutos normalmente. En horas pico puede tardar más."
    },
    "pago": {
        "pregunta": "💳 ¿Qué métodos de pago aceptáis?",
        "respuesta": "Efectivo, Bizum (+34 600 000 000) y tarjeta."
    },
    "contacto": {
        "pregunta": "📞 ¿Cómo os contacto?",
        "respuesta": "Por este bot o al +34 600 000 000 en horario."
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

# ============ SISTEMA DE COOLDOWN ============
def verificar_cooldown(user_id):
    """Verifica si el usuario puede hacer otro pedido (30 min cooldown)"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT ultimo_pedido FROM usuarios WHERE user_id = ?", (user_id,))
    resultado = c.fetchone()
    conn.close()
    
    if resultado and resultado[0]:
        ultimo_pedido = datetime.fromisoformat(resultado[0])
        tiempo_transcurrido = datetime.now() - ultimo_pedido
        
        if tiempo_transcurrido < timedelta(minutes=30):
            minutos_restantes = 30 - int(tiempo_transcurrido.total_seconds() / 60)
            return False, minutos_restantes
    
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

# ============ SISTEMA DE VALORACIONES ============
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
                 WHERE user_id = ? AND valoracion = 0
                 ORDER BY fecha DESC LIMIT 3''', (user_id,))
    pedidos = c.fetchall()
    conn.close()
    return pedidos

def obtener_valoracion_promedio():
    """Obtiene la valoración promedio"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT AVG(valoracion) FROM pedidos WHERE valoracion > 0")
    resultado = c.fetchone()[0]
    conn.close()
    return round(resultado, 1) if resultado else 0.0

# ============ FUNCIONES DE ADMINISTRADOR ============
def es_admin(user_id):
    """Verifica si un usuario es administrador"""
    return user_id in ADMIN_IDS

def obtener_estadisticas():
    """Obtiene estadísticas del sistema"""
    conn = get_db()
    c = conn.cursor()
    
    hoy = datetime.now().strftime("%Y-%m-%d")
    
    # Pedidos de hoy
    c.execute("SELECT COUNT(*), SUM(total) FROM pedidos WHERE DATE(fecha) = ?", (hoy,))
    pedidos_hoy = c.fetchone()
    
    # Total histórico
    c.execute("SELECT COUNT(*), SUM(total) FROM pedidos")
    total_historico = c.fetchone()
    
    # Valoración promedio
    c.execute("SELECT AVG(valoracion) FROM pedidos WHERE valoracion > 0")
    valoracion_promedio = c.fetchone()[0] or 0
    
    # Usuarios activos
    c.execute('''SELECT COUNT(DISTINCT user_id) FROM pedidos 
                 WHERE DATE(fecha) >= DATE('now', '-7 days')''')
    usuarios_activos = c.fetchone()[0]
    
    conn.close()
    
    return {
        'hoy': {
            'pedidos': pedidos_hoy[0] or 0,
            'ventas': pedidos_hoy[1] or 0.0
        },
        'historico': {
            'pedidos': total_historico[0] or 0,
            'ventas': total_historico[1] or 0.0
        },
        'valoracion_promedio': round(valoracion_promedio, 1),
        'usuarios_activos': usuarios_activos or 0
    }

def obtener_usuarios_con_cooldown():
    """Obtiene usuarios con cooldown activo"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT user_id, username, ultimo_pedido FROM usuarios 
                 WHERE ultimo_pedido IS NOT NULL''')
    usuarios = c.fetchall()
    conn.close()
    
    resultado = []
    for user_id, username, ultimo_pedido in usuarios:
        if ultimo_pedido:
            fecha_pedido = datetime.fromisoformat(ultimo_pedido)
            tiempo_transcurrido = datetime.now() - fecha_pedido
            
            if tiempo_transcurrido < timedelta(minutes=30):
                minutos_restantes = 30 - int(tiempo_transcurrido.total_seconds() / 60)
                resultado.append({
                    'user_id': user_id,
                    'username': username or f"ID: {user_id}",
                    'minutos_restantes': minutos_restantes
                })
    
    return resultado

def resetear_cooldowns():
    """Resetea todos los cooldowns"""
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE usuarios SET ultimo_pedido = NULL")
    conn.commit()
    conn.close()
    return True

def obtener_pedidos_recientes():
    """Obtiene pedidos recientes"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT id, username, productos, total, estado, fecha 
                 FROM pedidos ORDER BY fecha DESC LIMIT 10''')
    pedidos = c.fetchall()
    conn.close()
    
    resultado = []
    for pedido in pedidos:
        resultado.append({
            'id': pedido[0],
            'username': pedido[1] or "Anónimo",
            'productos': pedido[2],
            'total': pedido[3],
            'estado': pedido[4],
            'fecha': datetime.fromisoformat(pedido[5]).strftime("%H:%M")
        })
    
    return resultado

# ============ GESTIÓN DE HORARIOS ============
TURNOS = {
    "VIERNES": ["20:30", "21:00", "21:15", "21:30", "22:00", "22:15", "22:30"],
    "SABADO": ["13:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00", "15:15", "15:30",
               "20:30", "21:00", "21:15", "21:30", "22:00", "22:15", "22:30"],
    "DOMINGO": ["13:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00", "15:15", "15:30",
                "20:30", "21:00", "21:15", "21:30", "22:00", "22:15", "22:30"]
}

def obtener_dia_actual():
    dias = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]
    ahora = datetime.utcnow() + timedelta(hours=1)
    return dias[ahora.weekday()]

def obtener_hora_actual():
    ahora = datetime.utcnow() + timedelta(hours=1)
    return ahora.strftime("%H:%M")

# ============ HANDLERS PRINCIPALES ============
def start(update: Update, context: CallbackContext):
    """Comando /start"""
    user = update.effective_user
    user_id = user.id
    
    # Verificar cooldown
    puede_pedir, minutos_restantes = verificar_cooldown(user_id)
    
    if not puede_pedir:
        update.message.reply_text(
            f"⏳ **ESPERA REQUERIDA**\n\n"
            f"Debes esperar {minutos_restantes} minutos antes de hacer otro pedido.\n"
            f"¡Gracias por tu comprensión! 🤫",
            parse_mode='Markdown'
        )
        return
    
    dia_actual = obtener_dia_actual()
    
    # Verificar si estamos abiertos
    if dia_actual not in ["VIERNES", "SABADO", "DOMINGO"] and not MODO_PRUEBAS:
        update.message.reply_text(
            f"⛔ **CERRADO**\n\nHoy es {dia_actual}. Abrimos Viernes, Sábado y Domingo.",
            parse_mode='Markdown'
        )
        return
    
    # Inicializar carrito
    if 'carrito' not in context.user_data:
        context.user_data['carrito'] = []
    context.user_data['esperando_direccion'] = False
    
    # Valoración promedio
    valoracion_promedio = obtener_valoracion_promedio()
    estrellas = "⭐" * int(valoracion_promedio) if valoracion_promedio > 0 else "Sin valoraciones"
    
    welcome_text = (
        f"🚪 **BIENVENIDO A KNOCK TWICE** 🤫\n\n"
        f"🍕 *Pizza & Burgers de autor*\n"
        f"📍 *Solo en Bilbao centro*\n"
        f"⭐ *Valoración: {valoracion_promedio}/5 {estrellas}*\n\n"
        f"*¿Qué deseas hacer?*"
    )
    
    keyboard = [
        [InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal')],
        [InlineKeyboardButton("🛒 VER MI PEDIDO", callback_data='ver_carrito')],
        [InlineKeyboardButton("❓ PREGUNTAS FRECUENTES", callback_data='faq_menu')],
        [InlineKeyboardButton("⭐ VALORAR PEDIDO", callback_data='valorar_menu')]
    ]
    
    update.message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def menu_principal(update: Update, context: CallbackContext, query=None):
    """Muestra el menú principal"""
    keyboard = [
        [InlineKeyboardButton("🍕 PIZZAS", callback_data='cat_pizzas')],
        [InlineKeyboardButton("🍔 BURGERS", callback_data='cat_burgers')],
        [InlineKeyboardButton("🍰 POSTRES", callback_data='cat_postres')],
        [InlineKeyboardButton("🛒 VER MI PEDIDO", callback_data='ver_carrito')],
        [InlineKeyboardButton("❓ FAQ", callback_data='faq_menu')],
        [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
    ]
    
    mensaje = "📂 **SELECCIONA UNA CATEGORÍA:**"
    
    if query:
        query.edit_message_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        update.message.reply_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def mostrar_categoria(update: Update, context: CallbackContext, categoria):
    """Muestra productos de una categoría"""
    query = update.callback_query
    query.answer()
    
    categoria_info = MENU[categoria]
    keyboard = []
    
    for producto_id, producto in categoria_info['productos'].items():
        texto_boton = f"{producto['nombre']} - {producto['precio']}€"
        keyboard.append([
            InlineKeyboardButton(texto_boton, callback_data=f"info_{categoria}_{producto_id}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 VOLVER AL MENÚ", callback_data='menu_principal')])
    
    query.edit_message_text(
        f"👇 **{categoria_info['titulo']}**\n\nSelecciona un producto:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def mostrar_info_producto(update: Update, context: CallbackContext, categoria, producto_id):
    """Muestra información del producto con alérgenos"""
    query = update.callback_query
    query.answer()
    
    producto = MENU[categoria]['productos'][producto_id]
    alergenos = producto['alergenos']
    
    mensaje = (
        f"🍽️ **{producto['nombre']}**\n\n"
        f"_{producto['desc']}_\n\n"
        f"💰 **Precio:** {producto['precio']}€\n\n"
    )
    
    if alergenos:
        mensaje += f"⚠️ **ALÉRGENOS:** {', '.join(alergenos)}\n\n"
    
    mensaje += "¿Cuántas unidades quieres añadir?"
    
    keyboard = [
        [
            InlineKeyboardButton("1", callback_data=f"add_{categoria}_{producto_id}_1"),
            InlineKeyboardButton("2", callback_data=f"add_{categoria}_{producto_id}_2"),
            InlineKeyboardButton("3", callback_data=f"add_{categoria}_{producto_id}_3")
        ],
        [
            InlineKeyboardButton("4", callback_data=f"add_{categoria}_{producto_id}_4"),
            InlineKeyboardButton("5", callback_data=f"add_{categoria}_{producto_id}_5")
        ],
        [InlineKeyboardButton("🔙 VOLVER", callback_data=f"cat_{categoria}")]
    ]
    
    query.edit_message_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def añadir_al_carrito(update: Update, context: CallbackContext, categoria, producto_id, cantidad):
    """Añade productos al carrito"""
    query = update.callback_query
    query.answer()
    
    producto = MENU[categoria]['productos'][producto_id]
    
    if 'carrito' not in context.user_data:
        context.user_data['carrito'] = []
    
    for _ in range(int(cantidad)):
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

def ver_carrito(update: Update, context: CallbackContext, query=None):
    """Muestra el carrito"""
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
        mensaje += "👇 Para continuar, necesitamos tu dirección."
        
        keyboard = [
            [InlineKeyboardButton("📍 PONER DIRECCIÓN", callback_data='pedir_direccion')],
            [InlineKeyboardButton("🗑️ VACIAR CESTA", callback_data='vaciar_carrito')],
            [InlineKeyboardButton("🍽️ SEGUIR PIDIENDO", callback_data='menu_principal')]
        ]
    
    if query:
        query.edit_message_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        update.message.reply_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def pedir_direccion(update: Update, context: CallbackContext):
    """Solicita la dirección"""
    query = update.callback_query
    query.answer()
    
    context.user_data['esperando_direccion'] = True
    
    query.edit_message_text(
        "📍 **PASO 1/2: DIRECCIÓN Y TELÉFONO**\n\n"
        "Por favor, escribe tu dirección completa y un número de teléfono:\n\n"
        "✍️ _Ejemplo: Calle Gran Vía 1, 4ºB, Bilbao. Tel: 612345678_",
        parse_mode='Markdown'
    )

def procesar_direccion(update: Update, context: CallbackContext):
    """Procesa la dirección ingresada"""
    if not context.user_data.get('esperando_direccion', False):
        return
    
    direccion = update.message.text
    context.user_data['direccion'] = direccion
    context.user_data['esperando_direccion'] = False
    
    dia_actual = obtener_dia_actual()
    hora_actual = obtener_hora_actual()
    
    if dia_actual in TURNOS:
        horarios_disponibles = [h for h in TURNOS[dia_actual] if h > hora_actual]
        
        if horarios_disponibles:
            keyboard = []
            for hora in horarios_disponibles[:8]:
                keyboard.append([InlineKeyboardButton(f"🕒 {hora}", callback_data=f"hora_{hora}")])
            
            keyboard.append([InlineKeyboardButton("🔙 VOLVER", callback_data='ver_carrito')])
            
            update.message.reply_text(
                f"✅ **Dirección guardada.**\n\n"
                f"📅 **HOY ES: {dia_actual}**\n"
                f"⏰ **SELECCIONA HORA DE ENTREGA:**\n"
                f"(Solo mostramos horas futuras)",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
            return
    
    update.message.reply_text(
        "❌ **NO HAY HORARIOS DISPONIBLES**\n\n"
        "Lo sentimos, no quedan horarios disponibles para hoy.",
        parse_mode='Markdown'
    )

def confirmar_hora(update: Update, context: CallbackContext, hora_elegida):
    """Confirma el pedido con la hora seleccionada"""
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    puede_pedir, minutos_restantes = verificar_cooldown(user_id)
    
    if not puede_pedir:
        query.edit_message_text(
            f"⏳ **¡UPS!**\n\n"
            f"Mientras seleccionabas la hora, alguien más ha hecho un pedido.\n"
            f"Debes esperar {minutos_restantes} minutos.",
            parse_mode='Markdown'
        )
        return
    
    carrito = context.user_data.get('carrito', [])
    direccion = context.user_data.get('direccion', 'No especificada')
    usuario = query.from_user
    
    if not carrito:
        query.edit_message_text("❌ El carrito está vacío")
        return
    
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
    
    texto_pedido = ""
    for nombre, cantidad in productos_agrupados.items():
        texto_pedido += f"- {cantidad}x {nombre}\n"
    
    conn = get_db()
    c = conn.cursor()
    
    productos_str = ", ".join([f"{cant}x {nombre}" for nombre, cant in productos_agrupados.items()])
    dia_actual = obtener_dia_actual()
    
    c.execute('''INSERT INTO pedidos (user_id, username, productos, total, direccion, hora_entrega, estado, fecha)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (usuario.id, usuario.username, productos_str, total, direccion, 
               f"{dia_actual} {hora_elegida}", "pendiente", datetime.now().isoformat()))
    
    pedido_id = c.lastrowid
    conn.commit()
    conn.close()
    
    actualizar_cooldown(usuario.id, usuario.username)
    
    try:
        context.bot.send_message(
            chat_id=ID_GRUPO_PEDIDOS,
            text=f"🚪 **NUEVO PEDIDO #{pedido_id}** 🚪\n\n"
                 f"👤 Cliente: @{usuario.username or usuario.first_name}\n"
                 f"📅 Día: {dia_actual}\n"
                 f"⏰ Hora: {hora_elegida}\n"
                 f"📍 Dirección: {direccion}\n"
                 f"🍽️ Comanda:\n{texto_pedido}"
                 f"💰 Total: {total}€\n"
                 f"➖➖➖➖➖➖➖➖➖➖"
        )
    except Exception as e:
        print(f"Error enviando al grupo: {e}")
    
    context.user_data['carrito'] = []
    context.user_data['direccion'] = None
    
    query.edit_message_text(
        f"✅ **¡PEDIDO #{pedido_id} CONFIRMADO!**\n\n"
        f"📅 *Día:* {dia_actual}\n"
        f"🕒 *Hora:* {hora_elegida}\n"
        f"💰 *Total:* {total}€\n\n"
        f"Cocina ha recibido tu comanda.\n"
        f"¡Gracias por confiar en Knock Twice! 🤫\n\n"
        f"⭐ *Recuerda:* Puedes valorar tu pedido después con /valorar",
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

# ============ HANDLERS DE VALORACIONES ============
def valorar_menu(update: Update, context: CallbackContext):
    """Menú de valoraciones"""
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    pedidos_sin_valorar = obtener_pedidos_sin_valorar(user_id)
    
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

# ============ HANDLERS DE FAQ ============
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

# ============ HANDLERS DE ADMINISTRADOR ============
def admin_panel(update: Update, context: CallbackContext):
    """Panel de administración"""
    user_id = update.effective_user.id
    
    if not es_admin(user_id):
        update.message.reply_text("❌ No tienes permisos de administrador.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 ESTADÍSTICAS", callback_data='admin_stats')],
        [InlineKeyboardButton("📦 PEDIDOS RECIENTES", callback_data='admin_pedidos')],
        [InlineKeyboardButton("👥 USUARIOS CON COOLDOWN", callback_data='admin_cooldown')],
        [InlineKeyboardButton("🔄 RESET COOLDOWNS", callback_data='admin_reset_cooldown')],
        [InlineKeyboardButton("🏠 VOLVER AL INICIO", callback_data='inicio')]
    ]
    
    update.message.reply_text(
        "🔧 **PANEL DE ADMINISTRACIÓN**\n\nSelecciona una opción:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def mostrar_estadisticas(update: Update, context: CallbackContext):
    """Muestra estadísticas"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not es_admin(user_id):
        query.answer("❌ No tienes permisos")
        return
    
    query.answer()
    
    stats = obtener_estadisticas()
    
    mensaje = (
        "📊 **ESTADÍSTICAS DEL SISTEMA**\n\n"
        "📅 *HOY:*\n"
        f"• Pedidos: {stats['hoy']['pedidos']}\n"
        f"• Ventas: {stats['hoy']['ventas']:.2f}€\n\n"
        
        "📈 *TOTAL HISTÓRICO:*\n"
        f"• Pedidos: {stats['historico']['pedidos']}\n"
        f"• Ventas: {stats['historico']['ventas']:.2f}€\n\n"
        
        "👥 *USUARIOS ACTIVOS (7 días):* {}\n".format(stats['usuarios_activos']) +
        f"⭐ *VALORACIÓN PROMEDIO:* {stats['valoracion_promedio']}/5\n\n"
        
        f"⏰ *Hora:* {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔄 ACTUALIZAR", callback_data='admin_stats')],
        [InlineKeyboardButton("🔙 PANEL ADMIN", callback_data='admin_panel')]
    ]
    
    query.edit_message_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def mostrar_pedidos_recientes(update: Update, context: CallbackContext):
    """Muestra pedidos recientes"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not es_admin(user_id):
        query.answer("❌ No tienes permisos")
        return
    
    query.answer()
    
    pedidos = obtener_pedidos_recientes()
    
    if not pedidos:
        mensaje = "📭 No hay pedidos recientes."
    else:
        mensaje = "📦 **PEDIDOS RECIENTES**\n\n"
        
        for i, pedido in enumerate(pedidos, 1):
            estado_icono = "✅" if pedido['estado'] == 'entregado' else "🔄"
            mensaje += (
                f"{i}. *#{pedido['id']}* {estado_icono}\n"
                f"   👤 {pedido['username']}\n"
                f"   🍽️ {pedido['productos'][:30]}...\n"
                f"   💰 {pedido['total']}€ • {pedido['fecha']}\n\n"
            )
    
    keyboard = [
        [InlineKeyboardButton("🔄 ACTUALIZAR", callback_data='admin_pedidos')],
        [InlineKeyboardButton("🔙 PANEL ADMIN", callback_data='admin_panel')]
    ]
    
    query.edit_message_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def mostrar_usuarios_cooldown(update: Update, context: CallbackContext):
    """Muestra usuarios con cooldown"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not es_admin(user_id):
        query.answer("❌ No tienes permisos")
        return
    
    query.answer()
    
    usuarios = obtener_usuarios_con_cooldown()
    
    if not usuarios:
        mensaje = "👥 **NO HAY USUARIOS CON COOLDOWN**"
    else:
        mensaje = f"⏳ **USUARIOS CON COOLDOWN** ({len(usuarios)})\n\n"
        
        for i, usuario in enumerate(usuarios[:10], 1):
            mensaje += (
                f"{i}. 👤 {usuario['username']}\n"
                f"   ⏰ Espera: {usuario['minutos_restantes']} min\n\n"
            )
    
    keyboard = [
        [InlineKeyboardButton("🔄 RESETEAR TODOS", callback_data='admin_reset_cooldown_confirm')],
        [InlineKeyboardButton("🔄 ACTUALIZAR", callback_data='admin_cooldown')],
        [InlineKeyboardButton("🔙 PANEL ADMIN", callback_data='admin_panel')]
    ]
    
    query.edit_message_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def reset_cooldown_handler(update: Update, context: CallbackContext):
    """Maneja reset de cooldowns"""
    query = update.callback_query
    user_id = query.from_user.id
    
    if not es_admin(user_id):
        query.answer("❌ No tienes permisos")
        return
    
    query.answer()
    
    if query.data == 'admin_reset_cooldown_confirm':
        keyboard = [
            [InlineKeyboardButton("✅ SÍ, RESETEAR", callback_data='admin_reset_cooldown_execute')],
            [InlineKeyboardButton("❌ CANCELAR", callback_data='admin_cooldown')]
        ]
        
        query.edit_message_text(
            "⚠️ **CONFIRMAR RESET DE COOLDOWNS**\n\n"
            "¿Estás seguro de resetear TODOS los cooldowns?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif query.data == 'admin_reset_cooldown_execute':
        resetear_cooldowns()
        
        query.edit_message_text(
            "✅ **COOLDOWNS RESETEADOS**\n\n"
            "Todos los usuarios pueden hacer pedidos ahora.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 PANEL ADMIN", callback_data='admin_panel')]
            ]),
            parse_mode='Markdown'
        )

# ============ HANDLER DE BOTONES PRINCIPAL ============
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    
    # Navegación principal
    if data == 'menu_principal':
        menu_principal(update, context, query)
    
    elif data == 'inicio':
        start(update, context)
        query.message.delete()
    
    elif data == 'ver_carrito':
        ver_carrito(update, context, query)
    
    elif data == 'tramitar_pedido':
        pedir_direccion(update, context)
    
    elif data == 'pedir_direccion':
        pedir_direccion(update, context)
    
    elif data == 'vaciar_carrito':
        vaciar_carrito(update, context)
    
    # Categorías y productos
    elif data.startswith('cat_'):
        categoria = data.split('_')[1]
        mostrar_categoria(update, context, categoria)
    
    elif data.startswith('info_'):
        partes = data.split('_')
        categoria = partes[1]
        producto_id = partes[2]
        mostrar_info_producto(update, context, categoria, producto_id)
    
    elif data.startswith('add_'):
        partes = data.split('_')
        categoria = partes[1]
        producto_id = partes[2]
        cantidad = partes[3]
        añadir_al_carrito(update, context, categoria, producto_id, cantidad)
    
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
    
    # Administrador
    elif data == 'admin_panel':
        admin_panel(update, context)
    
    elif data == 'admin_stats':
        mostrar_estadisticas(update, context)
    
    elif data == 'admin_pedidos':
        mostrar_pedidos_recientes(update, context)
    
    elif data == 'admin_cooldown':
        mostrar_usuarios_cooldown(update, context)
    
    elif data in ['admin_reset_cooldown', 'admin_reset_cooldown_confirm', 'admin_reset_cooldown_execute']:
        reset_cooldown_handler(update, context)
    
    else:
        query.answer("Opción no disponible")

# ============ HANDLER DE MENSAJES ============
def handle_message(update: Update, context: CallbackContext):
    """Maneja mensajes de texto"""
    if context.user_data.get('esperando_direccion', False):
        procesar_direccion(update, context)
    else:
        comando_ayuda(update, context)

# ============ COMANDOS DE TEXTO ============
def comando_menu(update: Update, context: CallbackContext):
    """Comando /menu"""
    menu_principal(update, context)

def comando_pedido(update: Update, context: CallbackContext):
    """Comando /pedido"""
    ver_carrito(update, context)

def comando_faq(update: Update, context: CallbackContext):
    """Comando /faq"""
    faq_menu(update, context)

def comando_valorar(update: Update, context: CallbackContext):
    """Comando /valorar"""
    valorar_menu(update, context)

def comando_admin(update: Update, context: CallbackContext):
    """Comando /admin"""
    admin_panel(update, context)

def comando_ayuda(update: Update, context: CallbackContext):
    """Comando /ayuda"""
    ayuda_text = (
        "🆘 **AYUDA DE KNOCK TWICE**\n\n"
        "*Comandos disponibles:*\n"
        "• /start - Iniciar el bot\n"
        "• /menu - Ver la carta\n"
        "• /pedido - Ver tu carrito\n"
        "• /faq - Preguntas frecuentes\n"
        "• /valorar - Valorar pedidos\n"
        "• /admin - Panel administrador\n"
        "• /ayuda - Esta información\n\n"
        
        "📍 Entregamos en Bilbao centro\n"
        "⏰ Viernes a Domingo\n"
        "📞 Contacto: +34 600 000 000\n\n"
        "¡Usa los botones para navegar fácilmente!"
    )
    
    update.message.reply_text(ayuda_text, parse_mode='Markdown')

# ============ SERVIDOR WEB ============
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
    print(f"✅ Servidor web en puerto {port}")
    server.serve_forever()

def keep_alive():
    """Mantiene activo el servicio"""
    while True:
        try:
            time.sleep(300)
            requests.get("https://knock-twice.onrender.com", timeout=10)
            print("✅ Ping enviado")
        except:
            print("⚠️  Error en ping")
            pass

# ============ FUNCIÓN PRINCIPAL ============
def main():
    # Inicializar base de datos
    init_db()
    
    if not TOKEN:
        print("❌ ERROR: No hay token de Telegram")
        print("ℹ️ Configura la variable TELEGRAM_TOKEN en Render")
        return
    
    # Iniciar servidor web
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # Iniciar keep-alive
    keepalive_thread = threading.Thread(target=keep_alive, daemon=True)
    keepalive_thread.start()
    
    # Crear bot
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # Añadir handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", comando_menu))
    dp.add_handler(CommandHandler("pedido", comando_pedido))
    dp.add_handler(CommandHandler("faq", comando_faq))
    dp.add_handler(CommandHandler("valorar", comando_valorar))
    dp.add_handler(CommandHandler("admin", comando_admin))
    dp.add_handler(CommandHandler("ayuda", comando_ayuda))
    
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    
    print("🤖 Bot Knock Twice COMPLETO iniciado")
    print(f"🔧 Admins: {ADMIN_IDS}")
    print("✅ Todas las funcionalidades activas")
    print("✅ Panel de administrador listo")
    print("✅ Sistema de valoraciones activo")
    print("✅ FAQ completo")
    print("✅ Sistema de alérgenos")
    print("✅ Cooldown de 30 minutos")
    print("⏰ Bot listo para recibir pedidos")
    
    # Iniciar polling
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
