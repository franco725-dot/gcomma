import asyncio
import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

from google import genai
from google.genai import types
from groq import AsyncGroq
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ============================================================
# CONFIGURACIÓN — leída desde variables de entorno
# ============================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY   = os.getenv("GROQ_API_KEY")
PORT           = int(os.getenv("PORT", 10000))

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
GROQ_MODEL   = os.getenv("GROQ_MODEL",   "llama-3.3-70b-versatile")

SYSTEM_PROMPT = (
    "Eres un asistente de Telegram directo, inteligente y amigable. "
    "Responde en el idioma del usuario, sé útil y reconoce cuando "
    "no tienes información suficiente. "
    "Bro de verdad sigue humorísticamente "
    "todo lo que te dicen es better manu."
)

TELEGRAM_MESSAGE_LIMIT = 4000

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("FooChatBot")

if not TELEGRAM_TOKEN:
    raise RuntimeError("Falta configurar el TELEGRAM_TOKEN")

# Clientes de IA
gemini_client = (
    genai.Client(api_key=GEMINI_API_KEY)
    if GEMINI_API_KEY
    else None
)

groq_client = (
    AsyncGroq(api_key=GROQ_API_KEY, timeout=15.0, max_retries=1)
    if GROQ_API_KEY
    else None
)

ai_semaphore = asyncio.Semaphore(5)


# ============================================================
# SERVIDOR DE SALUD (para Render — evita que se duerma)
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"FooChat Bot OK")
    def log_message(self, format, *args):
        pass

def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    logger.info(f"Health server en puerto {PORT}")
    server.serve_forever()


# ============================================================
# GENERACIÓN DE RESPUESTAS (FAILOVER ESTRICTO)
# ============================================================

async def generar_con_gemini(prompt: str) -> str:
    if gemini_client is None:
        raise RuntimeError("Gemini no está configurado")

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.7,
        max_output_tokens=2048,
    )

    response = await gemini_client.aio.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=config,
    )

    answer = response.text
    if not answer or not answer.strip():
        raise ValueError("Gemini devolvió una respuesta vacía")

    return answer.strip()


async def generar_con_groq(prompt: str) -> str:
    if groq_client is None:
        raise RuntimeError("Groq no está configurado")

    response = await groq_client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.7,
        max_completion_tokens=2048,
    )

    answer = response.choices[0].message.content
    if not answer or not answer.strip():
        raise ValueError("Groq devolvió una respuesta vacía")

    return answer.strip()


async def obtener_respuesta_ia(prompt_usuario: str) -> str:
    prompt_usuario = prompt_usuario.strip()

    if not prompt_usuario:
        return "Escríbeme una pregunta para poder ayudarte."

    async with ai_semaphore:
        # Intento 1: Gemini (Principal)
        if gemini_client is not None:
            try:
                logger.info("Intentando Gemini...")
                respuesta = await generar_con_gemini(prompt_usuario)
                return f"[Gemini 🤖]\n{respuesta}"
            except Exception as exc:
                logger.warning("Gemini falló (%s). Cambiando a Groq...", type(exc).__name__)

        # Intento 2: Groq (Respaldo)
        if groq_client is not None:
            try:
                logger.info("Intentando Groq como respaldo...")
                respuesta = await generar_con_groq(prompt_usuario)
                return f"[Groq 🦙]\n{respuesta}"
            except Exception as exc:
                logger.warning("Groq también falló (%s)", type(exc).__name__)

    return (
        "🤖 Ambas IAs están ocupadas/caídas ahora mismo. "
        "¡Intenta de nuevo en un momento!"
    )


# ============================================================
# TELEGRAM
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "¡Hola! 🤖 FooChat Bot activo 24/7.\n\n"
            "Pregúntame lo que quieras. ¡Todo lo que digas es *better manu*!"
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "Envíame un mensaje y te responderé con IA.\n"
            "Comandos: /start y /help."
        )


async def enviar_respuesta_larga(message, texto: str) -> None:
    for inicio in range(0, len(texto), TELEGRAM_MESSAGE_LIMIT):
        await message.reply_text(texto[inicio:inicio + TELEGRAM_MESSAGE_LIMIT])


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message

    if message is None or not message.text:
        return

    user_text = message.text.strip()
    if not user_text:
        return

    logger.info("Mensaje recibido (%d chars)", len(user_text))

    try:
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.TYPING,
        )

        respuesta = await obtener_respuesta_ia(user_text)
        await enviar_respuesta_larga(message, respuesta)

    except Exception:
        logger.exception("Error inesperado al manejar el mensaje")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    logger.error("Error Telegram: %s", type(error).__name__ if error else "desconocido")


def main() -> None:
    # Iniciar servidor de salud en hilo aparte
    threading.Thread(target=run_health_server, daemon=True).start()

    app: Application = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    app.add_error_handler(error_handler)

    logger.info("FooChat Bot iniciado. ¡Todo es better manu!")
    app.run_polling()


if __name__ == "__main__":
    main()
