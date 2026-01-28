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
<head><title>Knock Twice</title></head>
<body><h1>Knock Twice Bot - Online</h1></body>
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
        
        conn.commit()
        conn.close()
        print("✅ Base de datos inicializada")
    except Exception as e:
        print(f"❌ Error BD: {e}")

def get_db():
    """Obtiene conexión a la base de datos"""
    return sqlite3.connect('knocktwice.db')

# ============ MENÚ ============
MENU = {
    "pizzas": {
        "titulo": "🍕 PIZZAS",
        "productos": {
            "margarita": {"nombre": "Margarita", "precio": 10, "desc": "Tomate, mozzarella y albahaca fresca.", "alergenos": ["LACTEOS", "GLUTEN"]},
            "pepperoni": {"nombre": "Pepperoni", "precio": 11, "desc": "Tomate, mozzarella y pepperoni.", "alergenos": ["LACTEOS", "GLUTEN"]}
        }
    },
    "burgers": {
        "titulo": "🍔 BURGERS",
        "productos": {
            "classic": {"nombre": "Classic Cheese", "precio": 11, "desc": "Doble carne, queso cheddar, cebolla y salsa especial.", "alergenos": ["LACTEOS", "GLUTEN", "HUEVO"]}
        }
    }
}

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
    """Comando /start"""
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
    
    txt = (f"🚪 **BIENVENIDO A KNOCK TWICE** 🤫\n\n"
           f"🍕 *Pizza & Burgers de autor*\n"
           f"⭐ *Valoración: {valoracion_promedio}/5*\n\n"
           f"*¿Qué deseas hacer?*")
    
    kb = [[InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal')],
          [InlineKeyboardButton("🛒 MI PEDIDO", callback_data='ver_carrito')],
          [InlineKeyboardButton("⭐ VALORAR", callback_data='valorar_menu')]]
    
    if es_admin(user_id):
        kb.append([InlineKeyboardButton("🔧 ADMIN", callback_data='admin_panel')])
    
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
        [InlineKeyboardButton("🛒 MI PEDIDO", callback_data='ver_carrito')],
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
        keyboard = [[InlineKeyboardButton("🍽️ VER CARTA", callback_data='menu_principal')]]
    else:
        total = sum(item['precio'] for item in carrito)
        productos = {}
        for item in carrito:
            nombre = item['nombre']
            productos[nombre] = productos.get(nombre, 0) + 1
        
        mensaje = "📝 **TU PEDIDO:**\n\n"
        for nombre, cantidad in productos.items():
            precio = next(item['precio'] for item in carrito if item['nombre'] == nombre)
            mensaje += f"▪️ {cantidad}x {nombre} ... {precio*cantidad}€\n"
        
        mensaje += f"\n💰 **TOTAL:** {total}€\n\n"
        mensaje += "👇 Para continuar, necesitamos tu dirección."
        
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
        "📍 **DIRECCIÓN DE ENTREGA**\n\n"
        "Escribe tu dirección completa:\n"
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
    horas = ["20:30", "21:00", "21:30", "22:00"]
    for hora in horas:
        keyboard.append([InlineKeyboardButton(f"🕒 {hora}", callback_data=f"hora_{hora}")])
    
    keyboard.append([InlineKeyboardButton("🔙 VOLVER", callback_data='ver_carrito')])
    
    update.message.reply_text(
        f"✅ **Dirección guardada.**\n\n"
        f"⏰ **SELECCIONA HORA DE ENTREGA:**\n"
        f"(Modo pruebas activado)",
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
    total = sum(item['precio'] for item in carrito)
    productos = {}
    for item in carrito:
        nombre = item['nombre']
        productos[nombre] = productos.get(nombre, 0) + 1
    
    productos_str = ", ".join([f"{cant}x {nombre}" for nombre, cant in productos.items()])
    
    # Guardar en BD
    conn = get_db()
    c = conn.cursor()
    c.execute('''INSERT INTO pedidos (user_id, username, productos, total, direccion, hora_entrega, estado, fecha)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
              (usuario.id, usuario.username, productos_str, total, direccion, 
               f"{datetime.now().strftime('%A')} {hora_elegida}", "pendiente", datetime.now().isoformat()))
    
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
        
        texto_pedido = "".join([f"- {cant}x {nombre}\n" for nombre, cant in productos.items()])
        
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
        print(f"✅ Pedido #{pedido_id} enviado al grupo")
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
        f"⭐ *Recuerda:* Valorarás cuando te llegue",
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
        query.answer("❌ Solo admins")
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
        query.answer("❌ Solo admins", show_alert=True)
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

# ============ HANDLER DE BOTONES ============
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data
    query.answer()
    
    print(f"🔘 Botón: {data}")
    
    # Navegación
    if data == 'inicio':
        start(update, context)
        try:
            query.message.delete()
        except:
            pass
    
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
        
        txt = f"🍽️ **{producto['nombre']}**\n\n_{producto['desc']}_\n\n💰 **Precio: {producto['precio']}€**\n\n¿Cuántas quieres?"
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
            f"✅ **{cantidad}x {producto['nombre']}** añadido(s)\n\n"
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
    
    # Admin panel simple
    elif data == 'admin_panel':
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM pedidos WHERE DATE(fecha) = DATE('now')")
        pedidos_hoy = c.fetchone()[0]
        conn.close()
        
        txt = f"🔧 **PANEL ADMIN**\n\nPedidos hoy: {pedidos_hoy}\n\nOpciones:"
        kb = [
            [InlineKeyboardButton("📊 ESTADÍSTICAS", callback_data='admin_stats')],
            [InlineKeyboardButton("🏠 INICIO", callback_data='inicio')]
        ]
        query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == 'admin_stats':
        valoracion = obtener_valoracion_promedio()
        txt = f"📊 **ESTADÍSTICAS**\n\n⭐ Valoración: {valoracion}/5\n\nModo pruebas: ✅ ACTIVADO"
        query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 ATRÁS", callback_data='admin_panel')]
        ]))
    
    else:
        query.answer("Opción no disponible")

# ============ HANDLER MENSAJES ============
def handle_message(update: Update, context: CallbackContext):
    """Maneja mensajes de texto"""
    if context.user_data.get('esperando_direccion'):
        procesar_direccion(update, context)
    else:
        update.message.reply_text(
            "🆘 **AYUDA**\n\nUsa /start para comenzar\n/menu para ver la carta\n/valorar para valorar pedidos",
            parse_mode='Markdown'
        )

# ============ COMANDOS ============
def comando_menu(update: Update, context: CallbackContext):
    menu_principal(update, context)

def comando_pedido(update: Update, context: CallbackContext):
    ver_carrito(update, context)

def comando_valorar(update: Update, context: CallbackContext):
    valorar_menu(update, context)

def comando_admin(update: Update, context: CallbackContext):
    if es_admin(update.effective_user.id):
        update.message.reply_text("🔧 Accediendo al panel admin...",
                                 reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔧 PANEL ADMIN", callback_data='admin_panel')]]))
    else:
        update.message.reply_text("❌ Comando no disponible.")

# ============ SERVIDOR WEB ============
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(HTML_WEB.encode())
    
    def log_message(self, format, *args):
        pass

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
    dp.add_handler(CommandHandler("valorar", comando_valorar))
    dp.add_handler(CommandHandler("admin", comando_admin))
    
    dp.add_handler(CallbackQueryHandler(button_handler))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    
    print("✅ Bot configurado")
    print("🎉 BOT ACTIVO Y LISTO!")
    print("="*50)
    
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
