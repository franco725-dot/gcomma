import os
import sys
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from google import genai
from google.genai import types

# Tokens leídos de variables de entorno seguras
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")
PORT = int(os.getenv("PORT", 10000))

if not TELEGRAM_TOKEN or not GEMINI_KEY:
    print("[!] AVISO: TELEGRAM_TOKEN o GEMINI_KEY no están definidos como variables de entorno.")

BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# Inicializar Gemini
gemini_client = genai.Client(api_key=GEMINI_KEY)

SYSTEM_PROMPT = (
    "Eres GComma, el asistente personal inteligente de Franco Pizarro (@franco725-dot) en Telegram. "
    "Estás corriendo 24/7 en la nube para responderle aunque su computadora esté apagada. "
    "Eres cercano, con sentido del humor, hablas en español casual y fresco (estilo chileno/latino), eres rápido e inteligente. "
    "Tienes contexto sobre sus proyectos: sus 38 juegos de Scratch publicados en GitHub, su proyecto 'gcomma', "
    "Geometry Dash, Nintendo 3DS, el cumpleaños de su mejor amigo Joaquín el 18 de noviembre, "
    "y el legendario 'Imperio Antipapa' que combate a la papa mutante de Chernobyl (SCP-725) junto a Tommy Durán. "
    "Responde siempre de forma amigable, directa y natural para mensajes de chat."
)

chat_history = []

def send_message(chat_id, text):
    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[-] Error enviando mensaje: {e}")

def ask_gemini(user_message, user_name="Franco"):
    try:
        chat_history.append(f"{user_name}: {user_message}")
        recent_context = "\n".join(chat_history[-10:])
        prompt = f"Contexto de la conversación:\n{recent_context}\n\nResponde a {user_name}."

        response = gemini_client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.8,
                max_output_tokens=600
            )
        )
        reply = response.text
        chat_history.append(f"GComma: {reply}")
        return reply
    except Exception as e:
        print(f"[-] Error Gemini: {e}")
        return f"Ups, me dio un pequeño mareo pensando: {e}"

# Servidor HTTP para Render/Koyeb (mantiene el bot activo 24/7)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"GComma Bot 24/7 Cloud Service is RUNNING!")

    def log_message(self, format, *args):
        pass

def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthCheckHandler)
    print(f"[*] Servidor de salud activo en puerto {PORT}", flush=True)
    server.serve_forever()

def run_bot_loop():
    print("[*] Iniciando loop de Telegram 24/7...", flush=True)
    last_update_id = 0

    while True:
        try:
            url = f"{BASE_URL}/getUpdates?offset={last_update_id + 1}&timeout=30"
            resp = requests.get(url, timeout=35).json()
            updates = resp.get("result", [])

            for update in updates:
                last_update_id = update["update_id"]
                msg = update.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                user_name = msg.get("from", {}).get("first_name", "Franco")
                text = msg.get("text", "").strip()

                if not chat_id:
                    continue

                print(f"[*] Mensaje de {user_name}: {text}", flush=True)

                if text.startswith("/start"):
                    bienvenida = (
                        f"¡Hola {user_name}! 🚀☁️\n\n"
                        "Soy **GComma 24/7 en la Nube**.\n"
                        "Ahora estoy viviendo en servidores de internet: ¡te puedo responder aunque tu computadora esté 100% apagada o estés de viaje!\n\n"
                        "Escríbeme lo que quieras cuando quieras. 🤖✨"
                    )
                    send_message(chat_id, bienvenida)

                elif text.startswith("/papita"):
                    send_message(chat_id, "🥔 *INFORME ANTIPAPA 24/7:*\n\nSatélites orbitales del Imperio Antipapa reportan: situación bajo control en Chile y el mundo. Tommy Durán sigue en guardia. 🫡⚔️")

                elif text.startswith("/info"):
                    send_message(chat_id, "☁️ *ESTADO DE GCOMMA:*\n\n• Servidor: Nube 24/7\n• Motor IA: Gemini 3.8 Flash\n• Creador: Franco Pizarro (@franco725-dot)\n• Estado PC: No requerida para chatear.")

                else:
                    reply = ask_gemini(text, user_name)
                    send_message(chat_id, reply)

        except Exception as e:
            time.sleep(2)

if __name__ == "__main__":
    # Iniciar servidor web de salud en hilo secundario
    web_thread = threading.Thread(target=run_health_server, daemon=True)
    web_thread.start()

    # Iniciar bot de Telegram en hilo principal
    run_bot_loop()
