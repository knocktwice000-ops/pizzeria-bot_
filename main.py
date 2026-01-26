import logging
import asyncio
import os
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

# 🔧 MODO PRUEBAS (True = Abre siempre / False = Respeta horario real)
MODO_PRUEBAS = True 

# --- 1. SERVIDOR MEJORADO ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()
        self.wfile.write(b"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Knock Twice Bot</title>
            <meta http-equiv="refresh" content="300">
            <style>
                body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
                h1 { color: #333; }
                .status { color: green; font-weight: bold; }
            </style>
        </head>
        <body>
            <h1>🚪 Knock Twice Bot</h1>
            <p class="status">✅ Bot activo y funcionando</p>
            <p>v13 Real Menu - "Shhh..."</p>
            <p>Último ping: <span id="time">""" + 
            datetime.now().strftime("%H:%M:%S").encode() + 
            b"""</span></p>
        </body>
        </html>
        """)
    
    def log_message(self, format, *args):
        # Silenciamos logs del servidor HTTP
        pass

def start_health_server():
    """Servidor HTTP mejorado con logging"""
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    
    # Configuración para evitar timeouts
    server.timeout = 30
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    print(f"🖥️  Servidor de salud iniciado en puerto {port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Servidor detenido")
    except Exception as e:
        print(f"Error en servidor: {e}")

# --- 2. ANTI-SUEÑO MEJORADO ---
def mantener_despierto():
    """Sistema anti-sleep mejorado con retry y logging"""
    print("⏰ Anti-sleep activado...")
    
    # URLs adicionales para ping (backup)
    urls_backup = [
        URL_RENDER,
        "https://google.com",
        "https://api.telegram.org"
    ]
    
    while True:
        try:
            # Ping principal a Render
            try:
                response = requests.get(URL_RENDER, timeout=10)
                if response.status_code == 200:
                    print(f"✅ Ping exitoso a Render - {datetime.now().strftime('%H:%M:%S')}")
                else:
                    print(f"⚠️  Ping con código {response.status_code}")
            except requests.exceptions.RequestException as e:
                print(f"❌ Error en ping principal: {e}")
                
                # Intentar con backup
                for url in urls_backup[1:]:
                    try:
                        requests.get(url, timeout=5)
                        print(f"✅ Backup ping a {url}")
                        break
                    except:
                        continue
            
            # Intervalo optimizado: 5 minutos (300 segundos)
            time.sleep(300)
            
        except Exception as e:
            print(f"🔥 Error crítico en anti-sleep: {e}")
            time.sleep(60)  # Esperar 1 minuto antes de reintentar

# --- 3. PING INTEGRADO EN EL BOT ---
async def ping_render_periodico(context: ContextTypes.DEFAULT_TYPE):
    """Tarea periódica asíncrona para mantener activo el bot"""
    while True:
        try:
            # Hacer ping a la propia URL de Render
            response = requests.get(URL_RENDER, timeout=5)
            print(f"🔔 Ping automático desde bot - {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e:
            print(f"⚠️  Ping automático falló: {e}")
        
        # Esperar 4 minutos entre pings
        await asyncio.sleep(240)

# --- 4. MENÚ (CARTA REAL) ---
MENU_DATA = {
    "pizzas": {
        "titulo": "🍕 KNOCK PIZZAS",
        "productos": {
            "margarita": {
                "nombre": "Margarita", 
                "precio": 10,
                "desc": "Tomate, mozzarella y albahaca fresca."
            },
            "trufada": {
                "nombre": "Trufada", 
                "precio": 14,
                "desc": "Salsa de trufa, mozzarella y champiñones."
            },
            "serranucula": {
                "nombre": "Serranúcula", 
                "precio": 13,
                "desc": "Tomate, mozzarella, jamón ibérico y rúcula."
            },
            "amatriciana": {
                "nombre": "Amatriciana", 
                "precio": 12,
                "desc": "Tomate, mozzarella y bacon."
            },
            "pepperoni": {
                "nombre": "Pepperoni", 
                "precio": 11,
                "desc": "Tomate, mozzarella y pepperoni."
            }
        }
    },
    "burgers": {
        "titulo": "🍔 BURGERS",
        "productos": {
            "classic": {
                "nombre": "Classic Cheese", 
                "precio": 11,
                "desc": "Doble carne, queso cheddar, cebolla y salsa especial."
            },
            "capone": {
                "nombre": "Al Capone", 
                "precio": 12,
                "desc": "Queso de cabra, cebolla caramelizada y rúcula."
            },
            "bacon": {
                "nombre": "Bacon BBQ", 
                "precio": 12,
                "desc": "Doble bacon crujiente, cheddar y salsa barbacoa."
            }
        }
    },
    "postres": {
        "titulo": "🍰 FINAL FELIZ",
        "productos": {
            "vinya": {
                "nombre": "Tarta de La Viña", 
                "precio": 6,
                "desc": "Nuestra tarta de queso cremosa al horno."
            }
        }
    }
}

# --- 5. GESTIÓN DE HORARIOS ---
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

# --- 6. LÓGICA DEL BOT (sin cambios) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dia, hora, cerrado = obtener_info_tiempo()
    
    if cerrado:
        await update.message.reply_text(
            f"⛔ **KNOCK TWICE CERRADO**\n\nHOY ES {dia}.\nAbrimos Viernes Noche, Sábado y Domingo.",
            parse_mode='Markdown'
        )
        return

    if 'carrito' not in context.user_data:
        context.user_data['carrito'] = []
    context.user_data['esperando_direccion'] = False 

    keyboard = [
        [InlineKeyboardButton("🍽️ VER CARTA Y PEDIR", callback_data='menu_categorias')],
        [InlineKeyboardButton("🛒 VER MI PEDIDO", callback_data='ver_carrito')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🚪 **KNOCK TWICE**\n\nBienvenido.\n👇 Empieza tu pedido:", 
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    # --- NAVEGACIÓN ---
    if data == 'menu_categorias':
        keyboard = [
            [InlineKeyboardButton("🍕 PIZZAS", callback_data='cat_pizzas')],
            [InlineKeyboardButton("🍔 BURGERS", callback_data='cat_burgers')],
            [InlineKeyboardButton("🍰 POSTRES", callback_data='cat_postres')],
            [InlineKeyboardButton("🛒 TRAMITAR PEDIDO", callback_data='ver_carrito')],
            [InlineKeyboardButton("🔙 Inicio", callback_data='inicio')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("📂 SELECCIONA CATEGORÍA:", reply_markup=reply_markup)

    elif data.startswith('cat_'):
        categoria = data.split('_')[1]
        info_cat = MENU_DATA[categoria]
        keyboard = []
        for id_prod, info in info_cat['productos'].items():
            texto = f"{info['nombre']} ({info['precio']}€)"
            keyboard.append([InlineKeyboardButton(texto, callback_data=f"sel_qty:{id_prod}:{categoria}")])
        keyboard.append([InlineKeyboardButton("🔙 Volver", callback_data='menu_categorias')])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"👇 {info_cat['titulo']}", reply_markup=reply_markup)

    # --- SELECTOR DE CANTIDAD ---
    elif data.startswith('sel_qty:'):
        _, id_prod, categoria = data.split(':')
        producto = MENU_DATA[categoria]['productos'][id_prod]
        
        descripcion = producto.get("desc", "Delicioso y casero.")

        keyboard = [
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
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(mensaje_producto, reply_markup=reply_markup, parse_mode='Markdown')

    # --- AÑADIR MÚLTIPLES ---
    elif data.startswith('add_mult:'):
        partes = data.split(':')
        cantidad = int(partes[1])
        id_prod = partes[2]
        categoria = partes[3]
        
        producto = MENU_DATA[categoria]['productos'][id_prod]
        
        if 'carrito' not in context.user_data: context.user_data['carrito'] = []
        for _ in range(cantidad):
            context.user_data['carrito'].append(producto)
        
        keyboard = [
            [InlineKeyboardButton("🔙 Seguir Pidiendo", callback_data=f'cat_{categoria}')],
            [InlineKeyboardButton("🚀 CONTINUAR (Dirección)", callback_data='pedir_direccion_flow')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"✅ Añadidas **{cantidad} x {producto['nombre']}** a la cesta.", reply_markup=reply_markup, parse_mode='Markdown')

    elif data == 'ver_carrito':
        carrito = context.user_data.get('carrito', [])
        if not carrito:
            texto = "🛒 TU CESTA ESTÁ VACÍA"
            keyboard = [[InlineKeyboardButton("🍽️ Ir a la Carta", callback_data='menu_categorias')]]
            await query.edit_message_text(texto, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            total = sum(p['precio'] for p in carrito)
            texto = "📝 TU PEDIDO:\n\n"
            
            conteo = {}
            for item in carrito:
                nombre = item['nombre']
                precio = item['precio']
                if nombre in conteo: conteo[nombre]['cantidad'] += 1
                else: conteo[nombre] = {'cantidad': 1, 'precio': precio}
            
            for nombre, info in conteo.items():
                subtotal = info['cantidad'] * info['precio']
                texto += f"▪️ {info['cantidad']}x {nombre} ... {subtotal}€\n"
            
            texto += f"\n💰 TOTAL: {total}€\n\n"
            texto += "👇 Para terminar, necesitamos tu dirección."
            keyboard = [
                [InlineKeyboardButton("📍 PONER DIRECCIÓN", callback_data='pedir_direccion_flow')],
                [InlineKeyboardButton("🗑️ Borrar todo", callback_data='borrar_carrito')],
                [InlineKeyboardButton("🔙 Seguir pidiendo", callback_data='menu_categorias')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(texto, reply_markup=reply_markup)

    elif data == 'pedir_direccion_flow':
        context.user_data['esperando_direccion'] = True
        msg = "📍 PASO 1/2: DIRECCIÓN Y TELÉFONO\n\nEscribe aquí abajo tu dirección completa y un teléfono.\n\n✍️ Escribe ahora..."
        keyboard = [[InlineKeyboardButton("🔙 Volver al Carrito", callback_data='ver_carrito_cancelar_dir')]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

    elif data == 'ver_carrito_cancelar_dir':
        context.user_data['esperando_direccion'] = False
        query.data = 'ver_carrito'
        await button_handler(update, context)

    elif data == 'mostrar_horas_flow':
        await mostrar_horas_disponibles(update, context, es_edicion=True)

    # --- CONFIRMAR PEDIDO ---
    elif data.startswith('sethora_'):
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

            mensaje_grupo = (
                f"🚪 **NUEVO PEDIDO KNOCK TWICE** 🚪\n"
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
                await context.bot.send_message(chat_id=ID_GRUPO_PEDIDOS, text=mensaje_grupo, reply_markup=reply_markup_grupo)
                
                context.user_data['carrito'] = []
                context.user_data['direccion'] = None
                
                await query.edit_message_text(
                    f"✅ ¡PEDIDO CONFIRMADO PARA EL {dia_elegido} A LAS {hora_elegida}!\n\nCocina ha recibido tu comanda.\nGracias por confiar en Knock Twice.\n\n🤫 Shhh..."
                )
            except Exception as e:
                await query.edit_message_text(f"❌ Error enviando: {e}")

        else:
            await query.edit_message_text("❌ Esa hora acaba de ocuparse. Elige otra.", 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Ver Horas", callback_data='mostrar_horas_flow')]]))

    elif data.startswith('reparto_'):
        cliente_id_destino = data.split('_')[1]
        try:
            await context.bot.send_message(
                chat_id=cliente_id_destino,
                text="🛵 **¡KNOCK TWICE INFORMA!**\n\nTu pedido ha salido de cocina y está en camino.\nPrepárate, estamos llegando. 🔥"
            )
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ CLIENTE AVISADO", callback_data="ignore")]])
            )
        except Exception as e:
            await query.answer(f"Error al avisar: {e}", show_alert=True)

    elif data == 'borrar_carrito':
        context.user_data['carrito'] = []
        context.user_data['esperando_direccion'] = False
        await query.edit_message_text("🗑️ Cesta vaciada.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Inicio", callback_data='inicio')]]))

    elif data == 'inicio':
        await start(update, context)
    elif data == 'ignore':
        await query.answer("Acción no disponible")

# --- FUNCIONES AUXILIARES ---
async def mostrar_horas_disponibles(update, context, es_edicion=False):
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

        if not hay_huecos: keyboard.append([InlineKeyboardButton("❌ YA NO QUEDAN TURNOS HOY", callback_data='ignore')])

    msg = f"✅ Dirección guardada.\n\n📅 **HOY ES: {dia_actual}**\n⏰ ELIGE HORA (Solo mostramos horas futuras):"
    
    if es_edicion:
        query = update.callback_query
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('esperando_direccion'):
        context.user_data['direccion'] = update.message.text
        context.user_data['esperando_direccion'] = False 
        await mostrar_horas_disponibles(update, context, es_edicion=False)
    else:
        dia, hora, cerrado = obtener_info_tiempo()
        if not cerrado: await update.message.reply_text("ℹ️ Usa el menú para pedir.")

# --- FUNCIÓN PRINCIPAL MEJORADA ---
async def main():
    """Función principal asíncrona"""
    # Iniciar el bot
    token = os.environ.get("TELEGRAM_TOKEN", "TOKEN_FALSO")
    application = ApplicationBuilder().token(token).build()
    
    # Añadir handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("🚀 Bot v13 Real Menu iniciado...")
    print(f"📅 Hora actual: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Iniciar el bot en modo polling
    await application.initialize()
    await application.start()
    
    # Crear tarea de ping periódico
    ping_task = asyncio.create_task(ping_render_periodico(application))
    
    try:
        # Ejecutar polling
        await application.updater.start_polling()
        print("✅ Bot completamente operativo")
        
        # Mantener el bot corriendo
        while True:
            await asyncio.sleep(3600)  # Esperar 1 hora
    except KeyboardInterrupt:
        print("\n⚠️  Deteniendo bot...")
    finally:
        # Limpieza
        ping_task.cancel()
        await application.stop()
        await application.shutdown()

if __name__ == '__main__':
    # Importar socket para el servidor
    import socket
    
    # Iniciar servidor HTTP en un hilo separado
    server_thread = threading.Thread(target=start_health_server, daemon=True)
    server_thread.start()
    
    # Iniciar anti-sleep en un hilo separado (backup)
    antisleep_thread = threading.Thread(target=mantener_despierto, daemon=True)
    antisleep_thread.start()
    
    # Ejecutar el bot principal
    asyncio.run(main())
