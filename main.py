import logging
import asyncio
import os
import sqlite3
import threading
import time
import requests
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

# --- CONFIGURACIÓN ---
ID_GRUPO_PEDIDOS = "-5151917747"
URL_RENDER = "https://knock-twice.onrender.com" 
ADMIN_IDS = [123456789]  # Reemplaza con tus IDs de administrador

# 🔧 MODO PRUEBAS (True = Abre siempre / False = Respeta horario real)
MODO_PRUEBAS = True 

# --- 1. BASE DE DATOS SQLite ---
def init_database():
    """Inicializa la base de datos SQLite"""
    conn = sqlite3.connect('knocktwice.db', check_same_thread=False)
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
                  fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                  valoracion INTEGER DEFAULT 0)''')
    
    # Tabla de usuarios (para cooldown y puntos)
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  ultimo_pedido TIMESTAMP,
                  puntos INTEGER DEFAULT 0,
                  total_gastado REAL DEFAULT 0)''')
    
    # Tabla de valoraciones
    c.execute('''CREATE TABLE IF NOT EXISTS valoraciones
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  pedido_id INTEGER,
                  user_id INTEGER,
                  estrellas INTEGER,
                  comentario TEXT,
                  fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    conn.commit()
    conn.close()
    print("✅ Base de datos inicializada")

def get_db_connection():
    """Obtiene conexión a la base de datos"""
    conn = sqlite3.connect('knocktwice.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

# --- 2. SISTEMA DE COOLDOWN ---
def verificar_cooldown(user_id):
    """Verifica si el usuario puede hacer otro pedido"""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute("SELECT ultimo_pedido FROM usuarios WHERE user_id = ?", (user_id,))
    resultado = c.fetchone()
    conn.close()
    
    if resultado and resultado['ultimo_pedido']:
        ultimo_pedido = datetime.fromisoformat(resultado['ultimo_pedido'])
        tiempo_transcurrido = datetime.now() - ultimo_pedido
        
        if tiempo_transcurrido < timedelta(minutes=30):
            minutos_restantes = 30 - int(tiempo_transcurrido.total_seconds() / 60)
            return False, minutos_restantes
    
    return True, 0

def actualizar_ultimo_pedido(user_id, username):
    """Actualiza la hora del último pedido del usuario"""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Insertar o actualizar usuario
    c.execute('''INSERT OR REPLACE INTO usuarios (user_id, username, ultimo_pedido) 
                 VALUES (?, ?, ?)''', 
              (user_id, username, datetime.now().isoformat()))
    
    conn.commit()
    conn.close()

# --- 3. ALÉRGENOS ---
ALERGENOS = {
    "margarita": ["LACTEOS", "GLUTEN"],
    "trufada": ["LACTEOS", "GLUTEN", "SETAS"],
    "serranucula": ["LACTEOS", "GLUTEN"],
    "amatriciana": ["LACTEOS", "GLUTEN"],
    "pepperoni": ["LACTEOS", "GLUTEN"],
    "classic": ["LACTEOS", "GLUTEN", "HUEVO", "MOSTAZA", "APIO", "SÉSAMO", "SOJA"],
    "capone": ["LACTEOS", "GLUTEN", "FRUTOS_SECOS", "SÉSAMO", "SOJA"],
    "bacon": ["LACTEOS", "GLUTEN", "MOSTAZA", "APIO", "SÉSAMO", "SOJA"],
    "vinya": ["LACTEOS", "GLUTEN", "HUEVO"]
}

# --- 4. PREGUNTAS FRECUENTES ---
FAQ = {
    "horario": {
        "pregunta": "🕒 ¿Cuál es vuestro horario?",
        "respuesta": "Abrimos:\n• Viernes: 20:30 - 23:00\n• Sábado: 13:30 - 16:00 / 20:30 - 23:00\n• Domingo: 13:30 - 16:00 / 20:30 - 23:00"
    },
    "zona": {
        "pregunta": "📍 ¿Hasta dónde entregáis?",
        "respuesta": "Entregamos en el centro histórico y alrededores (radio de 3km). Si estás más lejos, contáctanos por privado."
    },
    "alergenos": {
        "pregunta": "⚠️ ¿Tenéis información de alérgenos?",
        "respuesta": "Sí, cada producto muestra sus alérgenos. Si tienes alergias severas, avísanos en el pedido. ¡Tu seguridad es lo primero!"
    },
    "vegetariano": {
        "pregunta": "🥬 ¿Tenéis opciones vegetarianas?",
        "respuesta": "¡Claro! Pizza Margarita, Al Capone y podemos personalizar cualquier pedido. Solo avísanos."
    },
    "gluten": {
        "pregunta": "🌾 ¿Opciones sin gluten?",
        "respuesta": "Por ahora no tenemos base sin gluten, pero estamos trabajando en ello. ¡Pronto!"
    },
    "tiempo": {
        "pregunta": "⏱️ ¿Cuánto tarda el pedido?",
        "respuesta": "Entre 30-45 minutos dependiendo de la hora. En horas pico puede tardar un poco más."
    },
    "pago": {
        "pregunta": "💳 ¿Qué métodos de pago aceptáis?",
        "respuesta": "Efectivo, Bizum (+34 600 000 000) y tarjeta a través de enlace seguro."
    },
    "contacto": {
        "pregunta": "📞 ¿Cómo os contacto?",
        "respuesta": "Por este bot o al teléfono +34 600 000 000 en horario de apertura."
    }
}

# --- 5. SISTEMA DE VALORACIONES ---
async def pedir_valoracion(context: ContextTypes.DEFAULT_TYPE, user_id, pedido_id):
    """Envía solicitud de valoración después de la entrega"""
    await asyncio.sleep(1800)  # Esperar 30 minutos
    
    keyboard = [
        [InlineKeyboardButton("⭐", callback_data=f"valorar_{pedido_id}_1"),
         InlineKeyboardButton("⭐⭐", callback_data=f"valorar_{pedido_id}_2"),
         InlineKeyboardButton("⭐⭐⭐", callback_data=f"valorar_{pedido_id}_3"),
         InlineKeyboardButton("⭐⭐⭐⭐", callback_data=f"valorar_{pedido_id}_4"),
         InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data=f"valorar_{pedido_id}_5")]
    ]
    
    try:
        await context.bot.send_message(
            user_id,
            "🙏 **¿CÓMO HA SIDO TU EXPERIENCIA?**\n\n"
            "Valora tu pedido para que podamos mejorar. "
            "¡Gracias por elegir Knock Twice! 🤫",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except:
        pass  # Usuario bloqueó el bot o salió del chat

def guardar_valoracion(pedido_id, user_id, estrellas, comentario=None):
    """Guarda una valoración en la base de datos"""
    conn = get_db_connection()
    c = conn.cursor()
    
    c.execute('''INSERT INTO valoraciones (pedido_id, user_id, estrellas, comentario) 
                 VALUES (?, ?, ?, ?)''', 
              (pedido_id, user_id, estrellas, comentario))
    
    # Actualizar valoración en el pedido
    c.execute("UPDATE pedidos SET valoracion = ? WHERE id = ?", 
              (estrellas, pedido_id))
    
    conn.commit()
    conn.close()

# --- 6. FUNCIONALIDADES DE ADMINISTRADOR ---
async def panel_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Panel de control para administradores"""
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ No tienes permisos de administrador.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 ESTADÍSTICAS HOY", callback_data='admin_stats')],
        [InlineKeyboardButton("📈 VENTAS TOTALES", callback_data='admin_ventas')],
        [InlineKeyboardButton("⭐ VALORACIONES", callback_data='admin_valoraciones')],
        [InlineKeyboardButton("👤 USUARIOS ACTIVOS", callback_data='admin_usuarios')],
        [InlineKeyboardButton("🔄 RESET COOLDOWNS", callback_data='admin_reset_cooldown')],
        [InlineKeyboardButton("📢 ANUNCIO GLOBAL", callback_data='admin_anuncio')]
    ]
    
    await update.message.reply_text(
        "🔧 **PANEL DE ADMINISTRACIÓN**\nSelecciona una opción:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def obtener_estadisticas():
    """Obtiene estadísticas para administradores"""
    conn = get_db_connection()
    c = conn.cursor()
    
    hoy = datetime.now().strftime("%Y-%m-%d")
    
    # Ventas de hoy
    c.execute("SELECT COUNT(*), SUM(total) FROM pedidos WHERE DATE(fecha) = ?", (hoy,))
    ventas_hoy = c.fetchone()
    
    # Total ventas
    c.execute("SELECT COUNT(*), SUM(total) FROM pedidos")
    ventas_totales = c.fetchone()
    
    # Valoración promedio
    c.execute("SELECT AVG(valoracion) FROM pedidos WHERE valoracion > 0")
    valoracion_promedio = c.fetchone()[0] or 0
    
    # Usuarios activos (últimos 7 días)
    c.execute('''SELECT COUNT(DISTINCT user_id) FROM usuarios 
                 WHERE date(ultimo_pedido) >= date('now', '-7 days')''')
    usuarios_activos = c.fetchone()[0]
    
    conn.close()
    
    return {
        'ventas_hoy': ventas_hoy,
        'ventas_totales': ventas_totales,
        'valoracion_promedio': round(valoracion_promedio, 1),
        'usuarios_activos': usuarios_activos
    }

# --- 7. MENÚ (CARTA REAL) ---
MENU_DATA = {
    "pizzas": {
        "titulo": "🍕 KNOCK PIZZAS",
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
        "titulo": "🍰 FINAL FELIZ",
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

# --- 8. GESTIÓN DE HORARIOS ---
STOCK_INICIAL = 4

TURNOS = {
    "VIERNES": {
        "CENA": ["20:30", "21:00", "21:15", "21:30", "22:00", "22:15", "22:30"]
    },
    "SABADO": {
        "COMIDA": ["13:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00", "15:15", "15:30"],
        "CENA":   ["20:30", "21:00", "21:15", "21:30", "22:00", "22:15", "22:30"]
    },
    "DOMINGO": {
        "COMIDA": ["13:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00", "15:15", "15:30"],
        "CENA":   ["20:30", "21:00", "21:15", "21:30", "22:00", "22:15", "22:30"]
    }
}

STOCK_REAL = {}
for dia, turnos in TURNOS.items():
    STOCK_REAL[dia] = {}
    for nombre_turno, horas in turnos.items():
        for h in horas:
            STOCK_REAL[dia][h] = STOCK_INICIAL

def obtener_info_tiempo():
    ahora = datetime.utcnow() + timedelta(hours=1)
    dia_num = ahora.weekday() 
    hora_str = ahora.strftime("%H:%M")
    dias = ["LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO"]
    dia_str = dias[dia_num]

    if dia_str in ["VIERNES", "SABADO", "DOMINGO"]:
        return dia_str, hora_str, False
    else:
        if MODO_PRUEBAS: return "VIERNES", hora_str, False
        else: return dia_str, hora_str, True

# --- 9. MENÚ DE COMANDOS ---
async def set_commands_menu(application):
    """Configura el menú de comandos en Telegram"""
    commands = [
        ("start", "🚪 Iniciar el bot"),
        ("menu", "🍽️ Ver el menú completo"),
        ("pedido", "🛒 Ver mi pedido actual"),
        ("faq", "❓ Preguntas frecuentes"),
        ("valorar", "⭐ Valorar último pedido"),
        ("ayuda", "ℹ️ Ayuda e información"),
        ("admin", "🔧 Panel de administrador")
    ]
    
    await application.bot.set_my_commands([
        (command, description) for command, description in commands
    ])

# --- 10. HANDLERS PRINCIPALES MEJORADOS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando start mejorado con cooldown check"""
    dia, hora, cerrado = obtener_info_tiempo()
    user_id = update.effective_user.id
    
    # Verificar cooldown
    puede_pedir, minutos_restantes = verificar_cooldown(user_id)
    
    if not puede_pedir:
        await update.message.reply_text(
            f"⏳ **ESPERA REQUERIDA**\n\n"
            f"Para garantizar la mejor calidad, debes esperar {minutos_restantes} minutos "
            f"antes de hacer otro pedido.\n\n"
            f"¡Gracias por tu comprensión! 🤫",
            parse_mode='Markdown'
        )
        return
    
    if cerrado:
        await update.message.reply_text(
            f"⛔ **KNOCK TWICE CERRADO**\n\nHOY ES {dia}.\nAbrimos Viernes Noche, Sábado y Domingo.",
            parse_mode='Markdown'
        )
        return

    if 'carrito' not in context.user_data:
        context.user_data['carrito'] = []
    context.user_data['esperando_direccion'] = False

    # Mensaje de bienvenida mejorado
    welcome_text = (
        "🚪 *BIENVENIDO A KNOCK TWICE* 🤫\n\n"
        "🍕 *Pizza & Burgers de autor*\n"
        "📍 *Solo en Bilbao centro*\n\n"
        "*¿Qué deseas hacer?*"
    )
    
    keyboard = [
        [InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_categorias')],
        [InlineKeyboardButton("🛒 MI PEDIDO", callback_data='ver_carrito')],
        [InlineKeyboardButton("❓ FAQ", callback_data='faq_menu')],
        [InlineKeyboardButton("⭐ VALORAR", callback_data='valorar_menu')]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        welcome_text, 
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def comando_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /menu directo"""
    query = update.callback_query if update.callback_query else None
    
    if query:
        await query.answer()
        data = 'menu_categorias'
    else:
        # Crear un objeto query simulado
        class MockQuery:
            def __init__(self, message):
                self.edit_message_text = message.reply_text
                self.from_user = message.from_user
                self.answer = lambda: None
                self.data = 'menu_categorias'
        
        query = MockQuery(update.message)
        data = 'menu_categorias'
    
    # Redirigir al handler de botones
    await button_handler(update, context)

async def comando_faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /faq para preguntas frecuentes"""
    keyboard = []
    for key, faq in FAQ.items():
        keyboard.append([InlineKeyboardButton(faq["pregunta"], callback_data=f"faq_{key}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Menú principal", callback_data='inicio')])
    
    await update.message.reply_text(
        "❓ *PREGUNTAS FRECUENTES*\n\nSelecciona una pregunta:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def comando_pedido(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /pedido para ver el carrito"""
    query = update.callback_query if update.callback_query else None
    
    if query:
        data = 'ver_carrito'
    else:
        class MockQuery:
            def __init__(self, message):
                self.edit_message_text = message.reply_text
                self.from_user = message.from_user
                self.answer = lambda: None
                self.data = 'ver_carrito'
        
        query = MockQuery(update.message)
        update.callback_query = query
        data = 'ver_carrito'
    
    await button_handler(update, context)

async def comando_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /ayuda con información útil"""
    ayuda_text = (
        "🆘 *AYUDA DE KNOCK TWICE*\n\n"
        "*Comandos disponibles:*\n"
        "• /start - Iniciar el bot\n"
        "• /menu - Ver la carta completa\n"
        "• /pedido - Ver tu pedido actual\n"
        "• /faq - Preguntas frecuentes\n"
        "• /valorar - Valorar último pedido\n"
        "• /ayuda - Esta información\n\n"
        
        "*Información importante:*\n"
        "• Tiempo de entrega: 30-45 min\n"
        "• Mínimo de pedido: No hay\n"
        "• Zona de reparto: Centro Bilbao\n"
        "• Contacto: +34 600 000 000\n\n"
        
        "*Cooldown:* 30 min entre pedidos\n\n"
        "¿Necesitas más ayuda? Escríbenos aquí."
    )
    
    await update.message.reply_text(ayuda_text, parse_mode='Markdown')

# --- 11. HANDLER DE BOTONES MEJORADO ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # --- FAQ ---
    if data == 'faq_menu':
        keyboard = []
        for key, faq in FAQ.items():
            keyboard.append([InlineKeyboardButton(faq["pregunta"], callback_data=f"faq_{key}")])
        keyboard.append([InlineKeyboardButton("🔙 Inicio", callback_data='inicio')])
        
        await query.edit_message_text(
            "❓ *PREGUNTAS FRECUENTES*\nSelecciona:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        return
    
    elif data.startswith('faq_'):
        faq_key = data.split('_')[1]
        if faq_key in FAQ:
            respuesta = FAQ[faq_key]["respuesta"]
            keyboard = [[InlineKeyboardButton("🔙 Volver a FAQ", callback_data='faq_menu')]]
            await query.edit_message_text(
                f"*{FAQ[faq_key]['pregunta']}*\n\n{respuesta}",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        return
    
    # --- VALORACIONES ---
    elif data == 'valorar_menu':
        conn = get_db_connection()
        c = conn.cursor()
        
        # Buscar último pedido del usuario sin valorar
        c.execute('''SELECT id FROM pedidos 
                     WHERE user_id = ? AND valoracion = 0 
                     ORDER BY fecha DESC LIMIT 1''',
                  (query.from_user.id,))
        
        pedido = c.fetchone()
        conn.close()
        
        if pedido:
            pedido_id = pedido['id']
            keyboard = [
                [InlineKeyboardButton("⭐", callback_data=f"valorar_{pedido_id}_1"),
                 InlineKeyboardButton("⭐⭐", callback_data=f"valorar_{pedido_id}_2"),
                 InlineKeyboardButton("⭐⭐⭐", callback_data=f"valorar_{pedido_id}_3"),
                 InlineKeyboardButton("⭐⭐⭐⭐", callback_data=f"valorar_{pedido_id}_4"),
                 InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data=f"valorar_{pedido_id}_5)]
            ]
            
            await query.edit_message_text(
                "⭐ *VALORA TU ÚLTIMO PEDIDO*\n\n"
                "¿Cómo calificarías tu experiencia con Knock Twice?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text(
                "ℹ️ No encontramos pedidos pendientes de valorar.\n"
                "¡Gracias por tu apoyo! 🤫",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Inicio", callback_data='inicio')]
                ])
            )
        return
    
    elif data.startswith('valorar_'):
        partes = data.split('_')
        pedido_id = int(partes[1])
        estrellas = int(partes[2])
        
        guardar_valoracion(pedido_id, query.from_user.id, estrellas)
        
        await query.edit_message_text(
            f"✅ ¡Gracias por tu valoración de {estrellas} estrellas!\n\n"
            f"Tu opinión nos ayuda a mejorar. ¡Hasta la próxima! 🤫",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🍽️ Hacer otro pedido", callback_data='inicio')]
            ])
        )
        return
    
    # --- ADMIN PANEL ---
    elif data == 'admin_stats':
        if query.from_user.id not in ADMIN_IDS:
            return
        
        stats = obtener_estadisticas()
        
        mensaje = (
            "📊 *ESTADÍSTICAS DEL DÍA*\n\n"
            f"• Pedidos hoy: {stats['ventas_hoy'][0] or 0}\n"
            f"• Ingresos hoy: {stats['ventas_hoy'][1] or 0:.2f}€\n"
            f"• Pedidos totales: {stats['ventas_totales'][0] or 0}\n"
            f"• Ingresos totales: {stats['ventas_totales'][1] or 0:.2f}€\n"
            f"• Valoración promedio: {stats['valoracion_promedio']} ⭐\n"
            f"• Usuarios activos (7 días): {stats['usuarios_activos']}\n\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )
        
        await query.edit_message_text(
            mensaje,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Actualizar", callback_data='admin_stats')],
                [InlineKeyboardButton("🔙 Panel Admin", callback_data='admin_panel')]
            ]),
            parse_mode='Markdown'
        )
        return
    
    elif data == 'admin_panel':
        keyboard = [
            [InlineKeyboardButton("📊 ESTADÍSTICAS HOY", callback_data='admin_stats')],
            [InlineKeyboardButton("📈 VENTAS TOTALES", callback_data='admin_ventas')],
            [InlineKeyboardButton("⭐ VALORACIONES", callback_data='admin_valoraciones')],
            [InlineKeyboardButton("👤 USUARIOS ACTIVOS", callback_data='admin_usuarios')],
            [InlineKeyboardButton("🔄 RESET COOLDOWNS", callback_data='admin_reset_cooldown')],
            [InlineKeyboardButton("📢 ANUNCIO GLOBAL", callback_data='admin_anuncio')]
        ]
        
        await query.edit_message_text(
            "🔧 **PANEL DE ADMINISTRACIÓN**\nSelecciona una opción:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    elif data == 'admin_reset_cooldown':
        if query.from_user.id not in ADMIN_IDS:
            return
        
        conn = get_db_connection()
        c = conn.cursor()
        c.execute("UPDATE usuarios SET ultimo_pedido = NULL")
        conn.commit()
        conn.close()
        
        await query.answer("✅ Cooldowns reseteados para todos los usuarios", show_alert=True)
        return
    
    # --- PRODUCTOS CON ALÉRGENOS ---
    elif data.startswith('info_alergenos_'):
        producto_id = data.split('_')[2]
        categoria = data.split('_')[3]
        
        producto = MENU_DATA[categoria]['productos'][producto_id]
        alergenos = producto.get('alergenos', [])
        
        if alergenos:
            texto_alergenos = "⚠️ *ALÉRGENOS:* " + ", ".join(alergenos)
            await query.answer(texto_alergenos, show_alert=True)
        else:
            await query.answer("✅ Sin alérgenos comunes", show_alert=True)
        return
    
    # --- SELECTOR DE CANTIDAD CON ALÉRGENOS ---
    elif data.startswith('sel_qty:'):
        _, id_prod, categoria = data.split(':')
        producto = MENU_DATA[categoria]['productos'][id_prod]
        
        descripcion = producto.get("desc", "Delicioso y casero.")
        alergenos = producto.get('alergenos', [])
        
        # Botón de información de alérgenos
        info_button = [InlineKeyboardButton(
            "⚠️ VER ALÉRGENOS", 
            callback_data=f"info_alergenos_{id_prod}_{categoria}"
        )]
        
        keyboard = [
            info_button,
            [InlineKeyboardButton("1", callback_data=f"add_mult:1:{id_prod}:{categoria}"),
             InlineKeyboardButton("2", callback_data=f"add_mult:2:{id_prod}:{categoria}"),
             InlineKeyboardButton("3", callback_data=f"add_mult:3:{id_prod}:{categoria}")],
            [InlineKeyboardButton("4", callback_data=f"add_mult:4:{id_prod}:{categoria}"),
             InlineKeyboardButton("5", callback_data=f"add_mult:5:{id_prod}:{categoria}")],
            [InlineKeyboardButton("🔙 Volver", callback_data=f"cat_{categoria}")]
        ]
        
        mensaje_producto = (
            f"🍽️ **{producto['nombre']}**\n"
            f"_{descripcion}_\n\n"
            f"💰 Precio: {producto['precio']}€\n"
            f"🔢 **¿Cuántas quieres?**"
        )
        
        if alergenos:
            mensaje_producto += f"\n\n⚠️ *Contiene:* {', '.join(alergenos)}"
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(mensaje_producto, reply_markup=reply_markup, parse_mode='Markdown')
        return
    
    # --- NAVEGACIÓN ORIGINAL (modificada) ---
    if data == 'menu_categorias':
        keyboard = [
            [InlineKeyboardButton("🍕 PIZZAS", callback_data='cat_pizzas')],
            [InlineKeyboardButton("🍔 BURGERS", callback_data='cat_burgers')],
            [InlineKeyboardButton("🍰 POSTRES", callback_data='cat_postres')],
            [InlineKeyboardButton("🛒 TRAMITAR PEDIDO", callback_data='ver_carrito')],
            [InlineKeyboardButton("❓ FAQ", callback_data='faq_menu')],
            [InlineKeyboardButton("🔙 Inicio", callback_data='inicio')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📂 *SELECCIONA CATEGORÍA:*", reply_markup=reply_markup, parse_mode='Markdown')

    elif data.startswith('cat_'):
        categoria = data.split('_')[1]
        info_cat = MENU_DATA[categoria]
        keyboard = []
        for id_prod, info in info_cat['productos'].items():
            texto = f"{info['nombre']} ({info['precio']}€)"
            keyboard.append([InlineKeyboardButton(texto, callback_data=f"sel_qty:{id_prod}:{categoria}")])
        keyboard.append([InlineKeyboardButton("🔙 Volver", callback_data='menu_categorias')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"👇 *{info_cat['titulo']}*", reply_markup=reply_markup, parse_mode='Markdown')
    
    # ... (resto del código original del button_handler se mantiene igual)
    # Solo añadir la lógica de guardar pedido en la base de datos al confirmar
    
    elif data.startswith('sethora_'):
        # Verificar cooldown otra vez por seguridad
        puede_pedir, minutos_restantes = verificar_cooldown(query.from_user.id)
        
        if not puede_pedir:
            await query.edit_message_text(
                f"⏳ **ESPERA REQUERIDA**\n\n"
                f"Debes esperar {minutos_restantes} minutos antes de hacer otro pedido.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Inicio", callback_data='inicio')]
                ])
            )
            return
        
        partes = data.split('_')
        dia_elegido = partes[1]
        hora_elegida = partes[2]
        
        if STOCK_REAL[dia_elegido][hora_elegida] > 0:
            STOCK_REAL[dia_elegido][hora_elegida] -= 1
            
            carrito = context.user_data.get('carrito', [])
            direccion = context.user_data.get('direccion', 'Sin dirección')
            usuario = query.from_user.username or query.from_user.first_name
            user_id_cliente = query.from_user.id 
            
            texto_pedido = ""
            total = 0
            
            conteo = {}
            for item in carrito:
                if item['nombre'] in conteo: conteo[item['nombre']] += 1
                else: conteo[item['nombre']] = 1
                total += item['precio']
            
            for nombre, cant in conteo.items():
                texto_pedido += f"- {cant}x {nombre}\n"
            
            # GUARDAR EN BASE DE DATOS
            conn = get_db_connection()
            c = conn.cursor()
            
            productos_str = ", ".join([f"{cant}x {nombre}" for nombre, cant in conteo.items()])
            
            c.execute('''INSERT INTO pedidos 
                         (user_id, username, productos, total, direccion, hora_entrega, estado) 
                         VALUES (?, ?, ?, ?, ?, ?, ?)''',
                     (user_id_cliente, usuario, productos_str, total, direccion, 
                      f"{dia_elegido} {hora_elegida}", "pendiente"))
            
            pedido_id = c.lastrowid
            conn.commit()
            conn.close()
            
            # Actualizar cooldown del usuario
            actualizar_ultimo_pedido(user_id_cliente, usuario)
            
            # Programar solicitud de valoración
            asyncio.create_task(pedir_valoracion(context, user_id_cliente, pedido_id))
            
            # ... resto del código para enviar mensaje al grupo ...
            
            mensaje_grupo = (
                f"🚪 **NUEVO PEDIDO #{pedido_id}** 🚪\n"
                f"➖➖➖➖➖➖➖➖➖➖\n"
                f"👤 Cliente: @{usuario} (ID: {user_id_cliente})\n"
                f"📅 Día: {dia_elegido}\n"
                f"⏰ Hora: {hora_elegida}\n"
                f"📍 Dirección: {direccion}\n"
                f"🍽️ Comanda:\n{texto_pedido}"
                f"💰 Total: {total}€\n"
                f"➖➖➖➖➖➖➖➖➖➖"
            )
            
            keyboard_grupo = [[InlineKeyboardButton("🛵 AVISAR: PEDIDO EN CAMINO", callback_data=f"reparto_{user_id_cliente}")]]
            reply_markup_grupo = InlineKeyboardMarkup(keyboard_grupo)

            try:
                await context.bot.send_message(
                    chat_id=ID_GRUPO_PEDIDOS, 
                    text=mensaje_grupo, 
                    reply_markup=reply_markup_grupo
                )
                
                context.user_data['carrito'] = []
                context.user_data['direccion'] = None
                context.user_data['ultimo_pedido_id'] = pedido_id
                
                await query.edit_message_text(
                    f"✅ ¡PEDIDO #{pedido_id} CONFIRMADO!\n\n"
                    f"*Día:* {dia_elegido}\n"
                    f"*Hora:* {hora_elegida}\n"
                    f"*Total:* {total}€\n\n"
                    f"Cocina ha recibido tu comanda.\n"
                    f"¡Gracias por confiar en Knock Twice! 🤫\n\n"
                    f"📱 *Recuerda:* Puedes usar /pedido para ver estado.",
                    parse_mode='Markdown'
                )
            except Exception as e:
                await query.edit_message_text(f"❌ Error enviando: {e}")
        
        else:
            await query.edit_message_text("❌ Esa hora acaba de ocuparse. Elige otra.", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ver Horas", callback_data='mostrar_horas_flow')]]))

    # ... resto del código original ...

# --- 12. SERVIDOR Y ANTI-SLEEP (igual que antes) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Knock Twice Bot - v14 Mejorado")

def start_fake_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

def mantener_despierto():
    while True:
        try:
            time.sleep(600)
            requests.get(URL_RENDER)
        except Exception:
            pass

# --- 13. FUNCIÓN PRINCIPAL ---
async def main():
    # Inicializar base de datos
    init_database()
    
    # Iniciar bot
    token = os.environ.get("TELEGRAM_TOKEN", "TOKEN_FALSO")
    application = ApplicationBuilder().token(token).build()
    
    # Configurar menú de comandos
    await set_commands_menu(application)
    
    # Añadir handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", comando_menu))
    application.add_handler(CommandHandler("pedido", comando_pedido))
    application.add_handler(CommandHandler("faq", comando_faq))
    application.add_handler(CommandHandler("ayuda", comando_ayuda))
    application.add_handler(CommandHandler("admin", panel_admin))
    application.add_handler(CommandHandler("valorar", comando_pedido))  # Temporal, se maneja en button_handler
    
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("🤖 Bot v14 Mejorado iniciado...")
    print("✅ Características activadas:")
    print("   • Sistema de cooldown (30 min)")
    print("   • Información de alérgenos")
    print("   • FAQ completa")
    print("   • Sistema de valoraciones")
    print("   • Panel de administrador")
    print("   • Base de datos SQLite")
    print("   • Menú de comandos en la app")
    
    # Iniciar polling
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Mantener el bot corriendo
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        print("\n⏹️  Deteniendo bot...")

def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manejador de mensajes de texto"""
    if context.user_data.get('esperando_direccion'):
        context.user_data['direccion'] = update.message.text
        context.user_data['esperando_direccion'] = False 
        # Llamar a mostrar_horas_disponibles (asegúrate de tener esta función)
        asyncio.create_task(mostrar_horas_disponibles(update, context, es_edicion=False))
    else:
        # Si no está esperando dirección, mostrar ayuda
        asyncio.create_task(comando_ayuda(update, context))

async def mostrar_horas_disponibles(update, context, es_edicion=False):
    """Función para mostrar horas disponibles"""
    dia_actual, hora_actual, cerrado = obtener_info_tiempo()
    keyboard = []
    
    if dia_actual in TURNOS:
        turnos_del_dia = TURNOS[dia_actual]
        hay_huecos = False
        for nombre_turno, lista_horas in turnos_del_dia.items():
            horas_validas = [h for h in lista_horas if h > hora_actual]
            if horas_validas:
                hay_huecos = True
                icono = "☀️" if nombre_turno == "COMIDA" else "🌙"
                keyboard.append([InlineKeyboardButton(f"--- {icono} TURNO DE {nombre_turno} ---", callback_data='ignore')])
                for h in horas_validas:
                    huecos = STOCK_REAL[dia_actual][h]
                    if huecos > 0:
                        keyboard.append([InlineKeyboardButton(f"{h} ({huecos} huecos)", callback_data=f'sethora_{dia_actual}_{h}')])
                    else:
                        keyboard.append([InlineKeyboardButton(f"❌ {h} LLENO", callback_data='ignore')])

        if not hay_huecos: 
            keyboard.append([InlineKeyboardButton("❌ YA NO QUEDAN TURNOS HOY", callback_data='ignore')])
    
    msg = f"✅ Dirección guardada.\n\n📅 **HOY ES: {dia_actual}**\n⏰ ELIGE HORA (Solo mostramos horas futuras):"
    
    if es_edicion:
        query = update.callback_query
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

if __name__ == '__main__':
    # Iniciar servidor y anti-sleep
    threading.Thread(target=start_fake_server, daemon=True).start()
    threading.Thread(target=mantener_despierto, daemon=True).start()
    
    # Ejecutar bot
    asyncio.run(main())
