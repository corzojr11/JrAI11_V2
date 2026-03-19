import io
from typing import Optional, Tuple

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def telegram_config_ok() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def _base_url() -> str:
    return f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"


def enviar_mensaje_telegram(
    mensaje: str,
    chat_id: Optional[str] = None,
    parse_mode: str = "",
) -> Tuple[bool, str]:
    destino = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not destino:
        return False, "Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en el .env."

    payload = {
        "chat_id": destino,
        "text": mensaje,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        resp = requests.post(f"{_base_url()}/sendMessage", json=payload, timeout=15)
        if resp.status_code == 200:
            return True, "Mensaje enviado correctamente a Telegram."
        return False, f"Telegram respondio HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, f"No se pudo enviar mensaje a Telegram: {e}"


def enviar_documento_telegram(
    contenido: bytes,
    nombre_archivo: str,
    caption: str = "",
    chat_id: Optional[str] = None,
) -> Tuple[bool, str]:
    destino = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not destino:
        return False, "Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID en el .env."

    try:
        archivo = io.BytesIO(contenido)
        archivo.name = nombre_archivo
        data = {"chat_id": destino}
        if caption:
            data["caption"] = caption[:1024]
        files = {"document": (nombre_archivo, archivo)}
        resp = requests.post(f"{_base_url()}/sendDocument", data=data, files=files, timeout=30)
        if resp.status_code == 200:
            return True, "Documento enviado correctamente a Telegram."
        return False, f"Telegram respondio HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, f"No se pudo enviar documento a Telegram: {e}"


def enviar_paquete_telegram(
    mensaje: str,
    contenido: bytes,
    nombre_archivo: str,
    caption: str = "",
    chat_id: Optional[str] = None,
) -> Tuple[bool, str]:
    ok_msg, detalle_msg = enviar_mensaje_telegram(mensaje, chat_id=chat_id)
    if not ok_msg:
        return False, f"Fallo el mensaje: {detalle_msg}"

    ok_doc, detalle_doc = enviar_documento_telegram(
        contenido,
        nombre_archivo,
        caption=caption,
        chat_id=chat_id,
    )
    if not ok_doc:
        return False, f"Mensaje enviado, pero el documento fallo: {detalle_doc}"

    return True, "Pack social enviado correctamente a Telegram."
