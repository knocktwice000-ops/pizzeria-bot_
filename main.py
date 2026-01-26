import os
import sqlite3
import threading
import time
import requests
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext

# --- CONFIGURACIÓN ---
ID_GRUPO_PEDIDOS = "-5151917747"
TOKEN = os.environ.get("TELEGRAM_TOKEN")
MODO_PRUEBAS = True

# --- BASE DE DATOS MEJORADA ---
def init_db():
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
    
    # Tabla de FAQ para estadísticas
    c.execute('''CREATE TABLE IF NOT EXISTS faq_stats
                 (pregunta TEXT PRIMARY KEY,
                  veces_preguntada INTEGER DEFAULT 0)''')
    
    conn.commit()
    conn.close()
    print("✅ Base de datos inicializada")

def get_db():
    return sqlite3.connect('knocktwice.db')

# --- SISTEMA DE VALORACIONES ---
def guardar_valoracion(pedido_id, user_id, estrellas, comentario=None):
    """Guarda una valoración en la base de datos"""
    conn = get_db()
    c = conn.cursor()
    
    # Guardar en tabla de valoraciones
    c.execute('''INSERT INTO valoraciones (pedido_id, user_id, estrellas, comentario, fecha)
                 VALUES (?, ?, ?, ?, ?)''',
              (pedido_id, user_id, estrellas, comentario, datetime.now().isoformat()))
    
    # Actualizar valoración en el pedido
    c.execute("UPDATE pedidos SET valoracion = ? WHERE id = ?", (estrellas, pedido_id))
    
    conn.commit()
    conn.close()

def obtener_pedidos_sin_valorar(user_id):
    """Obtiene pedidos del usuario sin valorar"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''SELECT id, productos, fecha FROM pedidos 
                 WHERE user_id = ? AND valoracion = 0
                 ORDER BY fecha DESC LIMIT 5''', (user_id,))
    pedidos = c.fetchall()
    conn.close()
    return pedidos

def obtener_valoracion_promedio():
    """Obtiene la valoración promedio del restaurante"""
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT AVG(valoracion) FROM pedidos WHERE valoracion > 0")
    resultado = c.fetchone()[0]
    conn.close()
    return round(resultado, 1) if resultado else 0.0

# --- PREGUNTAS FRECUENTES (FAQ) COMPLETO ---
FAQ = {
    "horario": {
        "pregunta": "🕒 ¿Cuál es vuestro horario?",
        "respuesta": """*HORARIO DE APERTURA:* 📅

🍽️ *VIERNES:*
• Cena: 20:30 - 23:00

🍽️ *SÁBADO:*
• Comida: 13:30 - 16:00
• Cena: 20:30 - 23:00

🍽️ *DOMINGO:*
• Comida: 13:30 - 16:00  
• Cena: 20:30 - 23:00

*Cerramos de Lunes a Jueves.*"""
    },
    "zona": {
        "pregunta": "📍 ¿Hasta dónde entregáis?",
        "respuesta": """*ZONA DE REPARTO:* 🛵

Entregamos en el **centro histórico de Bilbao** y alrededores:

• **Radio de 3km** desde nuestro local
• **Zonas principales:** Casco Viejo, Indautxu, Deusto, Abando
• **Excluimos:** Zonas periféricas y pueblos

Si vives fuera de nuestra zona, ¡contáctanos por privado! Podemos hacer excepciones."""
    },
    "alergenos": {
        "pregunta": "⚠️ ¿Tenéis información de alérgenos?",
        "respuesta": """*INFORMACIÓN DE ALÉRGENOS:* 🚫

✅ *SÍ INFORMAMOS* de todos los alérgenos en cada producto.
✅ Puedes verlos antes de añadir cualquier producto al carrito.
✅ Si tienes alergias severas, AVÍSANOS en la dirección del pedido.

⚠️ *Importante:* Aunque informamos, compartimos cocina. No podemos garantizar contaminación cero."""
    },
    "vegetariano": {
        "pregunta": "🥬 ¿Tenéis opciones vegetarianas?",
        "respuesta": """*OPCIONES VEGETARIANAS:* 🌱

🍕 *PIZZAS VEGETARIANAS:*
• Margarita (sin jamón)
• Personalizada (pídenosla sin carne)

🍔 *BURGER VEGETARIANA:*
• Al Capone (queso de cabra, sin carne)

🍰 *POSTRE:*
• Tarta de La Viña (vegetariana)

*¿Quieres algo especial?* ¡Escríbenos! Hacemos personalizaciones."""
    },
    "gluten": {
        "pregunta": "🌾 ¿Opciones sin gluten?",
        "respuesta": """*OPCIONES SIN GLUTEN:* 🚫🌾

Actualmente **NO tenemos base sin gluten** para nuestras pizzas y burgers.

⚠️ *TODOS nuestros productos contienen GLUTEN.*

*Estamos trabajando* para ofrecer opciones sin gluten pronto. ¡Síguenos para novedades!"""
    },
    "tiempo": {
        "pregunta": "⏱️ ¿Cuánto tarda el pedido?",
        "respuesta": """*TIEMPOS DE ESPERA:* ⌛

⏰ *TIEMPO ESTIMADO DE ENTREGA:*
• Normal: 30-45 minutos
• Horas pico: 45-60 minutos
• Muy ocupados: Hasta 75 minutos

*Factores que afectan:*
• Hora del día (20:30-22:00 es la más ocupada)
• Complejidad del pedido
• Condiciones meteorológicas

*¿Quieres recibirlo rápido?* Pide fuera de horas pico."""
    },
    "pago": {
        "pregunta": "💳 ¿Qué métodos de pago aceptáis?",
        "respuesta": """*MÉTODOS DE PAGO:* 💰

✅ *EFECTIVO:* Al repartidor
✅ *BIZUM:* +34 600 000 000 (Knock Twice)
✅ *TARJETA:* A través de enlace seguro (te lo enviamos)

*Recomendamos:* Efectivo o Bizum para mayor rapidez.

⚠️ *No aceptamos:* Cheques, criptomonedas, pagos aplazados."""
    },
    "contacto": {
        "pregunta": "📞 ¿Cómo os contacto?",
        "respuesta": """*CONTACTO:* 📱

• *POR ESTE BOT:* Para pedidos y consultas
• *TELÉFONO:* +34 600 000 000 (solo en horario)
• *WHATSAPP:* Mismo número de teléfono
• *INSTAGRAM:* @knocktwicebilbao

*Horario de contacto:* Mismo que horario de apertura.

*Fuera de horario:* Deja tu mensaje, te responderemos al abrir."""
    },
    "devoluciones": {
        "pregunta": "🔄 ¿Política de devoluciones?",
        "respuesta": """*POLÍTICA DE DEVOLUCIONES:* 🔄

✅ *ACEPTAMOS DEVOLUCIÓN SI:*
• El pedido llega incorrecto
• Hay un problema de calidad
• Llega fuera del tiempo prometido (+90 min)

❌ *NO ACEPTAMOS DEVOLUCIÓN SI:*
• No te gustó el sabor (subjetivo)
• Cambiaste de opinión
• Problemas logísticos ajenos

*Proceso:* Contacta por este bot en 30 minutos tras recibir."""
    },
    "grupos": {
        "pregunta": "👥 ¿Hacéis pedidos para grupos?",
        "respuesta": """*PEDIDOS PARA GRUPOS:* 🎉

✅ *SÍ ACEPTAMOS* pedidos grandes para:
• Fiestas de cumpleaños
• Reuniones de trabajo
• Eventos especiales
• Cenas familiares

📋 *Requisitos:*
• Mínimo 48 horas de antelación
• Depósito del 50%
• Dirección dentro de nuestra zona

*Contacta por privado* para pedidos especiales."""
    }
}

def registrar_consulta_faq(pregunta):
    """Registra una consulta FAQ para estadísticas"""
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO faq_stats (pregunta, veces_preguntada)
                 VALUES (?, COALESCE((SELECT veces_preguntada FROM faq_stats WHERE pregunta = ?), 0) + 1)''',
              (pregunta, pregunta))
    conn.commit()
    conn.close()

# --- SISTEMA DE COOLDOWN ---
def verificar_cooldown(user_id):
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
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT OR REPLACE INTO usuarios (user_id, username, ultimo_pedido)
                 VALUES (?, ?, ?)''',
              (user_id, username, datetime.now().isoformat()))
    conn.commit()
    conn.close()

# --- MENÚ (igual que antes) ---
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

# --- GESTIÓN DE HORARIOS ---
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

# --- HANDLERS PRINCIPALES ---
def start(update: Update, context: CallbackContext):
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
            f"⛔ **CERRADO**\n\nHoy es {dia_actual}. Abrimos:\n"
            f"• Viernes: 20:30-23:00\n"
            f"• Sábado: 13:30-16:00 / 20:30-23:00\n"
            f"• Domingo: 13:30-16:00 / 20:30-23:00",
            parse_mode='Markdown'
        )
        return
    
    # Inicializar carrito si no existe
    if 'carrito' not in context.user_data:
        context.user_data['carrito'] = []
    
    context.user_data['esperando_direccion'] = False
    
    # Mensaje de bienvenida
    valoracion_promedio = obtener_valoracion_promedio()
    estrellas = "⭐" * int(valoracion_promedio) if valoracion_promedio > 0 else "Sin valoraciones aún"
    
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

# --- HANDLERS DE VALORACIONES ---
def valorar_menu(update: Update, context: CallbackContext):
    """Muestra el menú de valoraciones"""
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    pedidos_sin_valorar = obtener_pedidos_sin_valorar(user_id)
    
    if not pedidos_sin_valorar:
        query.edit_message_text(
            "⭐ **NO HAY PEDIDOS PENDIENTES DE VALORAR**\n\n"
            "¡Gracias por tu apoyo! Todos tus pedidos ya han sido valorados.\n\n"
            "¿Quieres hacer un nuevo pedido?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🍽️ HACER PEDIDO", callback_data='menu_principal')],
                [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
            ]),
            parse_mode='Markdown'
        )
        return
    
    # Mostrar pedidos para valorar
    keyboard = []
    for pedido in pedidos_sin_valorar[:3]:  # Mostrar máximo 3 pedidos
        pedido_id = pedido[0]
        productos = pedido[1]
        fecha = datetime.fromisoformat(pedido[2]).strftime("%d/%m %H:%M")
        
        # Acortar texto si es muy largo
        if len(productos) > 30:
            productos = productos[:27] + "..."
        
        keyboard.append([
            InlineKeyboardButton(f"📦 Pedido #{pedido_id} - {fecha}", 
                               callback_data=f"valorar_pedido_{pedido_id}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 VOLVER", callback_data='inicio')])
    
    query.edit_message_text(
        "⭐ **VALORA TUS PEDIDOS**\n\n"
        "Selecciona un pedido para valorar tu experiencia:\n\n"
        "_Tu opinión nos ayuda a mejorar nuestro servicio._",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def mostrar_valoracion_pedido(update: Update, context: CallbackContext, pedido_id):
    """Muestra las opciones de valoración para un pedido específico"""
    query = update.callback_query
    query.answer()
    
    # Obtener información del pedido
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT productos, fecha FROM pedidos WHERE id = ?", (pedido_id,))
    pedido = c.fetchone()
    conn.close()
    
    if not pedido:
        query.edit_message_text("❌ Pedido no encontrado")
        return
    
    productos = pedido[0]
    fecha = datetime.fromisoformat(pedido[1]).strftime("%d/%m/%Y a las %H:%M")
    
    # Acortar productos si es muy largo
    if len(productos) > 40:
        productos_display = productos[:37] + "..."
    else:
        productos_display = productos
    
    mensaje = (
        f"⭐ **VALORAR PEDIDO #{pedido_id}**\n\n"
        f"📅 *Fecha:* {fecha}\n"
        f"🍽️ *Pedido:* {productos_display}\n\n"
        f"*¿Cómo calificarías tu experiencia?*"
    )
    
    # Botones de valoración
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
    
    query.edit_message_text(
        mensaje,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def procesar_valoracion(update: Update, context: CallbackContext, pedido_id, estrellas):
    """Procesa la valoración del usuario"""
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    
    # Guardar valoración
    guardar_valoracion(pedido_id, user_id, estrellas)
    
    # Mensaje de agradecimiento
    mensajes = [
        "🌟 ¡Gracias por tu valoración! Tu opinión es muy importante para nosotros.",
        "⭐ ¡Excelente! Nos alegra que hayas disfrutado de nuestro servicio.",
        "🤫 ¡Shhh...! Gracias por confiar en Knock Twice. Tu valoración nos ayuda a mejorar.",
        "🍕 ¡Perfecto! Esperamos verte pronto de nuevo por aquí."
    ]
    
    import random
    mensaje_agradecimiento = random.choice(mensajes)
    
    # Mostrar valoración promedio actualizada
    valoracion_promedio = obtener_valoracion_promedio()
    
    query.edit_message_text(
        f"✅ **¡VALORACIÓN REGISTRADA!**\n\n"
        f"{mensaje_agradecimiento}\n\n"
        f"⭐ *Has dado {estrellas} estrellas al pedido #{pedido_id}*\n"
        f"📊 *Valoración promedio actual: {valoracion_promedio}/5*\n\n"
        f"¿Qué quieres hacer ahora?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🍽️ HACER OTRO PEDIDO", callback_data='menu_principal')],
            [InlineKeyboardButton("⭐ VALORAR OTRO PEDIDO", callback_data='valorar_menu')],
            [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
        ]),
        parse_mode='Markdown'
    )

# --- HANDLERS DE FAQ ---
def faq_menu(update: Update, context: CallbackContext):
    """Muestra el menú de preguntas frecuentes"""
    if update.callback_query:
        query = update.callback_query
        query.answer()
        mensaje_func = query.edit_message_text
    else:
        mensaje_func = update.message.reply_text
    
    # Crear teclado con todas las preguntas
    keyboard = []
    fila_temp = []
    
    for i, (key, faq) in enumerate(FAQ.items()):
        fila_temp.append(InlineKeyboardButton(faq["pregunta"], callback_data=f"faq_{key}"))
        
        # Agrupar en filas de 2 botones
        if len(fila_temp) == 2 or i == len(FAQ) - 1:
            keyboard.append(fila_temp)
            fila_temp = []
    
    # Botones de navegación
    keyboard.append([InlineKeyboardButton("📊 FAQ MÁS CONSULTADOS", callback_data='faq_populares')])
    keyboard.append([
        InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal'),
        InlineKeyboardButton("🏠 INICIO", callback_data='inicio')
    ])
    
    mensaje_func(
        "❓ **PREGUNTAS FRECUENTES**\n\n"
        "Selecciona una pregunta para ver la respuesta:\n\n"
        "_Tenemos respuestas para las dudas más comunes sobre nuestro servicio._",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def mostrar_faq(update: Update, context: CallbackContext, faq_key):
    """Muestra la respuesta de una FAQ específica"""
    query = update.callback_query
    query.answer()
    
    if faq_key not in FAQ:
        query.edit_message_text("❌ Pregunta no encontrada")
        return
    
    # Registrar la consulta para estadísticas
    registrar_consulta_faq(FAQ[faq_key]["pregunta"])
    
    faq = FAQ[faq_key]
    
    query.edit_message_text(
        f"{faq['respuesta']}\n\n"
        f"_¿Te ha resuelto la duda?_",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ SÍ", callback_data='faq_util_si'),
             InlineKeyboardButton("❌ NO", callback_data='faq_util_no')],
            [InlineKeyboardButton("🔙 VOLVER A FAQ", callback_data='faq_menu')],
            [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
        ]),
        parse_mode='Markdown'
    )

def faq_populares(update: Update, context: CallbackContext):
    """Muestra las FAQ más consultadas"""
    query = update.callback_query
    query.answer()
    
    # Obtener estadísticas de FAQ
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT pregunta, veces_preguntada FROM faq_stats ORDER BY veces_preguntada DESC LIMIT 5")
    populares = c.fetchall()
    conn.close()
    
    if not populares:
        mensaje = "📊 *AÚN NO HAY ESTADÍSTICAS DE FAQ*\n\nTodavía no se han consultado preguntas frecuentes."
    else:
        mensaje = "📊 **FAQ MÁS CONSULTADOS**\n\n"
        for i, (pregunta, veces) in enumerate(populares, 1):
            # Encontrar la clave de la FAQ
            faq_key = None
            for key, faq_info in FAQ.items():
                if faq_info["pregunta"] == pregunta:
                    faq_key = key
                    break
            
            if faq_key:
                icono = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
                mensaje += f"{icono} *{veces} consultas:* {pregunta}\n\n"
    
    query.edit_message_text(
        mensaje,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 VOLVER A FAQ", callback_data='faq_menu')],
            [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
        ]),
        parse_mode='Markdown'
    )

def feedback_faq(update: Update, context: CallbackContext, util):
    """Procesa el feedback de utilidad de una FAQ"""
    query = update.callback_query
    query.answer()
    
    if util == 'si':
        mensaje = "✅ *¡Gracias por tu feedback!*\n\nNos alegra haber resuelto tu duda."
    else:
        mensaje = "❌ *Lamentamos no haberte ayudado.*\n\n¿Podrías escribirnos tu duda por mensaje? ¡Te ayudaremos personalmente!"
    
    query.edit_message_text(
        mensaje,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✍️ ESCRIBIR MENSAJE", callback_data='contactar_soporte')],
            [InlineKeyboardButton("🔙 VOLVER A FAQ", callback_data='faq_menu')],
            [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
        ]),
        parse_mode='Markdown'
    )

# --- HANDLERS DE MENÚ Y PEDIDOS (igual que antes, simplificados) ---
def menu_principal(update: Update, context: CallbackContext, query=None):
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
        f"👇 **{categoria_info['titulo']}**\n\nSelecciona un producto para ver detalles:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def mostrar_info_producto(update: Update, context: CallbackContext, categoria, producto_id):
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
        "Lo sentimos, no quedan horarios disponibles para hoy.\n"
        "Por favor, intenta mañana.",
        parse_mode='Markdown'
    )

def confirmar_hora(update: Update, context: CallbackContext, hora_elegida):
    query = update.callback_query
    query.answer()
    
    user_id = query.from_user.id
    puede_pedir, minutos_restantes = verificar_cooldown(user_id)
    
    if not puede_pedir:
        query.edit_message_text(
            f"⏳ **¡UPS!**\n\n"
            f"Mientras seleccionabas la hora, alguien más ha hecho un pedido.\n"
            f"Debes esperar {minutos_restantes} minutos antes de intentarlo de nuevo.",
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
        f"⭐ *Recuerda:* Puedes valorar tu pedido después de recibirlo.",
        parse_mode='Markdown'
    )

def vaciar_carrito(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    context.user_data['carrito'] = []
    context.user_data['esperando_direccion'] = False
    
    query.edit_message_text(
        "🗑️ **CESTA VACIADA**\n\n"
        "Tu carrito ha sido vaciado. ¿Qué quieres hacer ahora?",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal')],
            [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
        ]),
        parse_mode='Markdown'
    )

# --- COMANDOS DE TEXTO ---
def comando_menu(update: Update, context: CallbackContext):
    menu_principal(update, context)

def comando_pedido(update: Update, context: CallbackContext):
    ver_carrito(update, context)

def comando_faq(update: Update, context: CallbackContext):
    faq_menu(update, context)

def comando_valorar(update: Update, context: CallbackContext):
    valorar_menu(update, context)

def comando_ayuda(update: Update, context: CallbackContext):
    ayuda_text = (
        "🆘 **AYUDA DE KNOCK TWICE**\n\n"
        "*Comandos disponibles:*\n"
        "• /start - Iniciar el bot\n"
        "• /menu - Ver la carta\n"
        "• /pedido - Ver tu carrito\n"
        "• /faq - Preguntas frecuentes\n"
        "• /valorar - Valorar pedidos\n"
        "• /ayuda - Esta información\n\n"
        
        "📍 Entregamos en Bilbao centro\n"
        "⏰ Viernes a Domingo\n"
        "📞 Contacto: +34 600 000 000\n\n"
        "Usa los botones para navegar fácilmente."
    )
    
    update.message.reply_text(ayuda_text, parse_mode='Markdown')

# --- HANDLER DE BOTONES PRINCIPAL ---
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    
    # Navegación principal
    if data == 'menu_principal':
        menu_principal(update, context, query)
    
    elif data == 'inicio':
        start(update, context)
        query.message.delete()
    
    elif data == 'faq_menu':
        faq_menu(update, context)
    
    elif data == 'faq_populares':
        faq_populares(update, context)
    
    elif data.startswith('faq_'):
        if data.startswith('faq_util_'):
            util = data.split('_')[2]
            feedback_faq(update, context, util)
        else:
            faq_key = data.split('_')[1]
            mostrar_faq(update, context, faq_key)
    
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
    
    elif data == 'contactar_soporte':
        query.edit_message_text(
            "✍️ **CONTACTA CON SOPORTE**\n\n"
            "Escribe tu pregunta o problema aquí mismo:\n\n"
            "_Un miembro de nuestro equipo te responderá lo antes posible._",
            parse_mode='Markdown'
        )
    
    # Menú y pedidos (igual que antes)
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
    
    elif data == 'ver_carrito':
        ver_carrito(update, context, query)
    
    elif data == 'tramitar_pedido':
        pedir_direccion(update, context)
    
    elif data == 'pedir_direccion':
        pedir_direccion(update, context)
    
    elif data.startswith('hora_'):
        hora = data.split('_')[1]
        confirmar_hora(update, context, hora)
    
    elif data == 'vaciar_carrito':
        vaciar_carrito(update, context)
    
    else:
        query.answer("Opción no disponible")

# --- MANEJADOR DE MENSAJES DE TEXTO ---
def handle_message(update: Update, context: CallbackContext):
    if context.user_data.get('esperando_direccion', False):
        procesar_direccion(update, context)
    else:
        comando_ayuda(update, context)

# --- SERVIDOR WEB PARA RENDER ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Knock Twice Bot v3 - FAQ y Valoraciones")
    
    def log_message(self, format, *args):
        pass

def start_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"✅ Servidor web en puerto {port}")
    server.serve_forever()

def keep_alive():
    while True:
        try:
            time.sleep(300)
            requests.get("https://knock-twice.onrender.com", timeout=10)
            print("✅ Ping enviado")
        except:
            print("⚠️  Error en ping")
            pass

# --- FUNCIÓN PRINCIPAL ---
def main():
    init_db()
    
    if not TOKEN:
        print("❌ ERROR: No hay token de Telegram")
        print("ℹ️ Configura la variable TELEGRAM_TOKEN en Render")
        return
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    keepalive_thread = threading.Thread(target=keep_alive, daemon=True)
    keepalive_thread.start()
    
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", comando_menu))
    dp.add_handler(CommandHandler("pedido", comando_pedido))
    dp.add_handler(CommandHandler("faq", comando_faq))
    dp.add_handler(CommandHandler("valorar", comando_valorar))
    dp.add_handler(CommandHandler("ayuda", comando_ayuda))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    
    print("🤖 Bot Knock Twice v3 iniciado")
    print("✅ Sistema de FAQ completo (10 preguntas)")
    print("✅ Sistema de valoraciones con estadísticas")
    print("✅ Base de datos mejorada")
    print("✅ Servidor web activo")
    
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
