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
    
    # Tabla de pedidos mejorada
    c.execute('''CREATE TABLE IF NOT EXISTS pedidos
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  username TEXT,
                  productos TEXT,
                  total REAL,
                  direccion TEXT,
                  hora_entrega TEXT,
                  estado TEXT DEFAULT 'pendiente',
                  fecha TEXT)''')
    
    # Tabla de usuarios para cooldown
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  ultimo_pedido TEXT)''')
    
    conn.commit()
    conn.close()
    print("✅ Base de datos inicializada")

def get_db():
    return sqlite3.connect('knocktwice.db')

# --- SISTEMA DE COOLDOWN SIMPLE ---
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

# --- MENÚ CON ALÉRGENOS ---
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
    ahora = datetime.utcnow() + timedelta(hours=1)  # Hora española
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
    hora_actual = obtener_hora_actual()
    
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
    welcome_text = (
        "🚪 **BIENVENIDO A KNOCK TWICE** 🤫\n\n"
        "🍕 *Pizza & Burgers de autor*\n"
        "📍 *Solo en Bilbao centro*\n\n"
        "*¿Qué deseas hacer?*"
    )
    
    keyboard = [
        [InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal')],
        [InlineKeyboardButton("🛒 VER MI PEDIDO", callback_data='ver_carrito')],
        [InlineKeyboardButton("❓ AYUDA / FAQ", callback_data='ayuda_menu')]
    ]
    
    update.message.reply_text(
        welcome_text,
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def menu_principal(update: Update, context: CallbackContext, query=None):
    """Muestra el menú principal de categorías"""
    keyboard = [
        [InlineKeyboardButton("🍕 PIZZAS", callback_data='cat_pizzas')],
        [InlineKeyboardButton("🍔 BURGERS", callback_data='cat_burgers')],
        [InlineKeyboardButton("🍰 POSTRES", callback_data='cat_postres')],
        [InlineKeyboardButton("🛒 VER MI PEDIDO", callback_data='ver_carrito')],
        [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
    ]
    
    mensaje = "📂 **SELECCIONA UNA CATEGORÍA:**"
    
    if query:
        query.edit_message_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        update.message.reply_text(mensaje, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def mostrar_categoria(update: Update, context: CallbackContext, categoria):
    """Muestra productos de una categoría específica"""
    query = update.callback_query
    query.answer()
    
    categoria_info = MENU[categoria]
    keyboard = []
    
    for producto_id, producto in categoria_info['productos'].items():
        # Botón con información de alérgenos
        texto_boton = f"{producto['nombre']} - {producto['precio']}€"
        keyboard.append([
            InlineKeyboardButton(texto_boton, callback_data=f"info_{categoria}_{producto_id}")
        ])
    
    keyboard.append([InlineKeyboardButton("🔙 VOLVER AL MENÚ", callback_data='menu_principal')])
    
    query.edit_message_text(
        f"👇 **{categoria_info['titulo']}**\n\n"
        f"Selecciona un producto para ver detalles:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

def mostrar_info_producto(update: Update, context: CallbackContext, categoria, producto_id):
    """Muestra información detallada del producto con alérgenos"""
    query = update.callback_query
    query.answer()
    
    producto = MENU[categoria]['productos'][producto_id]
    alergenos = producto['alergenos']
    
    # Crear mensaje con información del producto
    mensaje = (
        f"🍽️ **{producto['nombre']}**\n\n"
        f"_{producto['desc']}_\n\n"
        f"💰 **Precio:** {producto['precio']}€\n\n"
    )
    
    if alergenos:
        mensaje += f"⚠️ **ALÉRGENOS:** {', '.join(alergenos)}\n\n"
    
    mensaje += "¿Cuántas unidades quieres añadir?"
    
    # Botones para cantidad
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
    
    # Inicializar carrito si no existe
    if 'carrito' not in context.user_data:
        context.user_data['carrito'] = []
    
    # Añadir la cantidad especificada
    for _ in range(int(cantidad)):
        context.user_data['carrito'].append({
            'nombre': producto['nombre'],
            'precio': producto['precio'],
            'categoria': categoria
        })
    
    # Mensaje de confirmación
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
    """Muestra el contenido del carrito"""
    carrito = context.user_data.get('carrito', [])
    
    if not carrito:
        mensaje = "🛒 **TU CESTA ESTÁ VACÍA**"
        keyboard = [[InlineKeyboardButton("🍽️ IR A LA CARTA", callback_data='menu_principal')]]
    else:
        # Calcular total y agrupar productos
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
        
        # Construir mensaje
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
    """Solicita la dirección del usuario"""
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
    """Procesa la dirección ingresada y muestra horarios"""
    if not context.user_data.get('esperando_direccion', False):
        return
    
    direccion = update.message.text
    context.user_data['direccion'] = direccion
    context.user_data['esperando_direccion'] = False
    
    # Mostrar horarios disponibles
    dia_actual = obtener_dia_actual()
    hora_actual = obtener_hora_actual()
    
    # Verificar si hay horarios disponibles para hoy
    if dia_actual in TURNOS:
        horarios_disponibles = [h for h in TURNOS[dia_actual] if h > hora_actual]
        
        if horarios_disponibles:
            keyboard = []
            for hora in horarios_disponibles[:8]:  # Mostrar máximo 8 horas
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
    
    # Si no hay horarios disponibles
    update.message.reply_text(
        "❌ **NO HAY HORARIOS DISPONIBLES**\n\n"
        "Lo sentimos, no quedan horarios disponibles para hoy.\n"
        "Por favor, intenta mañana.",
        parse_mode='Markdown'
    )

def confirmar_hora(update: Update, context: CallbackContext, hora_elegida):
    """Confirma el pedido con la hora seleccionada"""
    query = update.callback_query
    query.answer()
    
    # Verificar cooldown una última vez
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
    
    # Procesar carrito
    carrito = context.user_data.get('carrito', [])
    direccion = context.user_data.get('direccion', 'No especificada')
    usuario = query.from_user
    
    if not carrito:
        query.edit_message_text("❌ El carrito está vacío")
        return
    
    # Calcular total y agrupar productos
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
    
    # Crear texto del pedido
    texto_pedido = ""
    for nombre, cantidad in productos_agrupados.items():
        texto_pedido += f"- {cantidad}x {nombre}\n"
    
    # Guardar en base de datos
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
    
    # Actualizar cooldown
    actualizar_cooldown(usuario.id, usuario.username)
    
    # Enviar al grupo de pedidos
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
    
    # Limpiar carrito
    context.user_data['carrito'] = []
    context.user_data['direccion'] = None
    
    # Confirmar al usuario
    query.edit_message_text(
        f"✅ **¡PEDIDO #{pedido_id} CONFIRMADO!**\n\n"
        f"📅 *Día:* {dia_actual}\n"
        f"🕒 *Hora:* {hora_elegida}\n"
        f"💰 *Total:* {total}€\n\n"
        f"Cocina ha recibido tu comanda.\n"
        f"¡Gracias por confiar en Knock Twice! 🤫",
        parse_mode='Markdown'
    )

def vaciar_carrito(update: Update, context: CallbackContext):
    """Vacía el carrito del usuario"""
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

def ayuda_menu(update: Update, context: CallbackContext):
    """Muestra el menú de ayuda/FAQ"""
    query = update.callback_query
    query.answer()
    
    ayuda_text = (
        "🆘 **AYUDA / PREGUNTAS FRECUENTES**\n\n"
        "*Comandos disponibles:*\n"
        "• /start - Iniciar el bot\n"
        "• /menu - Ver la carta\n"
        "• /pedido - Ver tu carrito\n"
        "• /ayuda - Esta información\n\n"
        
        "*Horario:*\n"
        "• Viernes: 20:30-23:00\n"
        "• Sábado: 13:30-16:00 / 20:30-23:00\n"
        "• Domingo: 13:30-16:00 / 20:30-23:00\n\n"
        
        "*Información importante:*\n"
        "• Cooldown: 30 min entre pedidos\n"
        "• Zona de reparto: Centro Bilbao\n"
        "• Contacto: +34 600 000 000\n\n"
        "⚠️ *Cada producto muestra sus alérgenos*"
    )
    
    keyboard = [
        [InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal')],
        [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
    ]
    
    query.edit_message_text(ayuda_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

def comando_menu(update: Update, context: CallbackContext):
    """Comando /menu"""
    menu_principal(update, context)

def comando_pedido(update: Update, context: CallbackContext):
    """Comando /pedido"""
    ver_carrito(update, context)

def comando_ayuda(update: Update, context: CallbackContext):
    """Comando /ayuda"""
    ayuda_text = (
        "🆘 **AYUDA DE KNOCK TWICE**\n\n"
        "*Comandos disponibles:*\n"
        "• /start - Iniciar el bot\n"
        "• /menu - Ver la carta\n"
        "• /pedido - Ver tu carrito\n"
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
    
    elif data == 'ayuda_menu':
        ayuda_menu(update, context)
    
    else:
        query.answer("Opción no disponible")

# --- MANEJADOR DE MENSAJES DE TEXTO ---
def handle_message(update: Update, context: CallbackContext):
    """Maneja mensajes de texto"""
    if context.user_data.get('esperando_direccion', False):
        procesar_direccion(update, context)
    else:
        comando_ayuda(update, context)

# --- SERVIDOR WEB PARA RENDER ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Knock Twice Bot v2 - Online")
    
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
            time.sleep(300)  # 5 minutos
            requests.get("https://knock-twice.onrender.com", timeout=10)
            print("✅ Ping enviado")
        except:
            print("⚠️  Error en ping")
            pass

# --- FUNCIÓN PRINCIPAL ---
def main():
    # Inicializar base de datos
    init_db()
    
    if not TOKEN:
        print("❌ ERROR: No hay token de Telegram")
        print("ℹ️ Configura la variable TELEGRAM_TOKEN en Render")
        return
    
    # Iniciar servidor web en hilo separado
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    # Iniciar keep-alive en hilo separado
    keepalive_thread = threading.Thread(target=keep_alive, daemon=True)
    keepalive_thread.start()
    
    # Crear y configurar el bot
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # Añadir handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("menu", comando_menu))
    dp.add_handler(CommandHandler("pedido", comando_pedido))
    dp.add_handler(CommandHandler("ayuda", comando_ayuda))
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    
    print("🤖 Bot Knock Twice v2 iniciado")
    print("✅ Sistema de alérgenos activado")
    print("✅ Sistema de cooldown (30 min)")
    print("✅ Base de datos lista")
    print("✅ Servidor web activo")
    
    # Iniciar el bot
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
