#!/usr/bin/env python3
"""
Envia el recordatorio diario de "descarga y actualizacion del acta" a la persona
a la que le toca el turno (rotando la lista de personas.json) y publica
el mismo mensaje en un espacio de Google Chat.

Variables de entorno requeridas (se configuran como Secrets de GitHub):
  SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, MAIL_FROM
  GOOGLE_CHAT_WEBHOOK_URL

Variables opcionales (para editar el contenido del recordatorio sin tocar el codigo):
  PERIODO            (ej: "2026C (Presencial)")
  CORTE               (ej: "Primer Corte")
  FECHA_LIMITE         (ej: "20/09/2026")
  FECHA_INICIO_ROTACION (ej: "2026-01-01") fecha de referencia para calcular el turno
"""

import json
import os
import smtplib
import sys
import urllib.request
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PERSONAS_PATH = BASE_DIR / "personas.json"
FESTIVOS_PATH = BASE_DIR / "festivos.json"


def cargar_festivos():
    """
    festivos.json es una lista de fechas "YYYY-MM-DD" que se tratan
    como no habiles (igual que sabado/domingo): no se envia nada ese
    dia y no cuenta para la rotacion. Si el archivo no existe, se
    asume que no hay festivos configurados.
    """
    if not FESTIVOS_PATH.exists():
        return set()
    with open(FESTIVOS_PATH, "r", encoding="utf-8") as f:
        fechas = json.load(f)
    return {datetime.strptime(f, "%Y-%m-%d").date() for f in fechas}


def es_dia_habil(fecha, festivos):
    return fecha.weekday() < 5 and fecha not in festivos


def cargar_personas():
    """
    personas.json es una lista de objetos {"nombre": ..., "correo": ...}
    en el orden exacto en que deben rotar.
    """
    with open(PERSONAS_PATH, "r", encoding="utf-8") as f:
        personas = json.load(f)
    if not personas:
        raise ValueError("personas.json esta vacio")
    return personas


def calcular_turno(personas, festivos):
    """
    Calcula a quien le toca hoy contando solo DIAS HABILES (lunes a
    viernes, sin festivos) transcurridos desde FECHA_INICIO_ROTACION,
    en modulo la cantidad de personas. Se excluyen fines de semana y
    festivos porque esos dias no se envia nada; si se contaran, la
    rotacion se saltaria personas cada vez que hay un dia no habil.
    Cuando llega al final de la lista, vuelve a empezar por el primero.
    """
    fecha_inicio_str = os.environ.get("FECHA_INICIO_ROTACION", "2026-01-01")
    fecha_inicio = datetime.strptime(fecha_inicio_str, "%Y-%m-%d").date()
    hoy = date.today()

    dias_habiles = 0
    fecha = fecha_inicio
    while fecha < hoy:
        fecha += timedelta(days=1)
        if es_dia_habil(fecha, festivos):
            dias_habiles += 1

    indice = dias_habiles % len(personas)
    return personas[indice]


def construir_mensaje(persona):
    asunto = "Recordatorio: descarga y actualizacion del ACA"

    cuerpo = (
        f"Hola {persona['nombre']},\n\n"
        "hoy te corresponde realizar la descarga y actualizacion del ACA.\n\n"
        "Muchas gracias por tu colaboracion 😀\n"
        "PD:No olvidar periodo Q 🤔\n"
    )
    return asunto, cuerpo


def enviar_correo(destinatario, asunto, cuerpo):
    servidor = os.environ["SMTP_SERVER"]
    puerto = int(os.environ.get("SMTP_PORT", "587"))
    usuario = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    remitente = os.environ.get("MAIL_FROM", usuario)

    msg = MIMEText(cuerpo, "plain", "utf-8")
    msg["Subject"] = asunto
    msg["From"] = remitente
    msg["To"] = destinatario

    # timeout=20: si el servidor SMTP no responde en 20s, lanza error
    # en vez de dejar el job colgado indefinidamente.
    if puerto == 465:
        # 465 es SSL directo (no usa starttls)
        with smtplib.SMTP_SSL(servidor, puerto, timeout=20) as server:
            server.login(usuario, password)
            server.sendmail(remitente, [destinatario], msg.as_string())
    else:
        with smtplib.SMTP(servidor, puerto, timeout=20) as server:
            server.starttls()
            server.login(usuario, password)
            server.sendmail(remitente, [destinatario], msg.as_string())

    print(f"Correo enviado a {destinatario}")


def enviar_google_chat(asunto, cuerpo):
    webhook_url = os.environ["GOOGLE_CHAT_WEBHOOK_URL"]
    texto = f"{asunto}\n\n{cuerpo}"
    data = json.dumps({"text": texto}).encode("utf-8")

    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json; charset=UTF-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        print(f"Mensaje enviado a Google Chat, status {resp.status}")


def enviar_a_persona(persona):
    asunto, cuerpo = construir_mensaje(persona)
    print(f"Procesando: {persona['nombre']} <{persona['correo']}>")

    try:
        enviar_correo(persona["correo"], asunto, cuerpo)
    except Exception as e:
        print(f"ERROR enviando correo a {persona['correo']}: {e}", file=sys.stderr)
        raise

    try:
        enviar_google_chat(asunto, cuerpo)
    except Exception as e:
        print(f"ERROR enviando a Google Chat: {e}", file=sys.stderr)
        raise


def main():
    personas = cargar_personas()
    festivos = cargar_festivos()
    modo = os.environ.get("MODO", "rotacion").strip().lower()

    if modo == "todos":
        # Modo de prueba: envia el recordatorio a TODAS las personas de la lista,
        # sin importar si hoy es festivo (para poder probar cualquier dia).
        print(f"MODO=todos -> enviando a las {len(personas)} personas de la lista")
        for persona in personas:
            enviar_a_persona(persona)
    else:
        hoy = date.today()
        if hoy in festivos:
            print(f"{hoy} esta marcado como festivo en festivos.json -> no se envia nada hoy")
            return
        # Modo normal: solo a la persona a la que le toca el turno de hoy.
        persona = calcular_turno(personas, festivos)
        print(f"Turno de hoy: {persona['nombre']} <{persona['correo']}>")
        enviar_a_persona(persona)


if __name__ == "__main__":
    main()
