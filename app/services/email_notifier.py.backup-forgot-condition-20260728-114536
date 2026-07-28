"""Lightweight SMTP email notifier for sklad marketplace events."""
from __future__ import annotations
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.config import Settings

log = logging.getLogger(__name__)


def _send(settings: "Settings", to_email: str, subject: str, html_body: str) -> None:
    """Send one email. Raises on failure — caller wraps in try/except."""
    if not settings.smtp_host or not settings.smtp_from:
        raise RuntimeError("SMTP not configured (SKLAD_SMTP_HOST or SKLAD_SMTP_FROM missing)")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("Sklad Marketplace", settings.smtp_from))
    msg["To"] = to_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    port = settings.smtp_port or (587 if settings.smtp_tls else 25)
    if settings.smtp_tls:
        with smtplib.SMTP(settings.smtp_host, port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            if settings.smtp_user and settings.smtp_pass:
                smtp.login(settings.smtp_user, settings.smtp_pass)
            smtp.sendmail(settings.smtp_from, [to_email], msg.as_string())
    else:
        with smtplib.SMTP(settings.smtp_host, port, timeout=10) as smtp:
            if settings.smtp_user and settings.smtp_pass:
                smtp.login(settings.smtp_user, settings.smtp_pass)
            smtp.sendmail(settings.smtp_from, [to_email], msg.as_string())


def notify_new_inquiry(
    settings: "Settings",
    supplier_email: str,
    supplier_name: str,
    product_name: str,
    quantity: float,
    unit: str,
    buyer_notes: str | None,
    inquiry_id: int,
    base_url: str = "https://tetis1.kz/sklad",
) -> None:
    """Email supplier when a buyer sends a new inquiry."""
    if not supplier_email:
        return
    notes_block = f"<p><b>Комментарий покупателя:</b> {buyer_notes}</p>" if buyer_notes else ""
    html = f"""
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
  <h2 style="color:#2563eb">📦 Новый запрос на ваш товар</h2>
  <p>Здравствуйте, <b>{supplier_name}</b>!</p>
  <p>Покупатель отправил запрос на ваш каталожный товар:</p>
  <table style="border-collapse:collapse;width:100%;margin:12px 0">
    <tr><td style="padding:6px 12px;background:#f5f7fa;font-weight:600">Товар</td>
        <td style="padding:6px 12px">{product_name}</td></tr>
    <tr><td style="padding:6px 12px;background:#f5f7fa;font-weight:600">Количество</td>
        <td style="padding:6px 12px">{quantity} {unit}</td></tr>
  </table>
  {notes_block}
  <p>
    <a href="{base_url}" style="background:#2563eb;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block;margin-top:8px">
      Открыть склад и ответить →
    </a>
  </p>
  <p style="color:#888;font-size:12px;margin-top:24px">
    Запрос №{inquiry_id} · Sklad Marketplace
  </p>
</div>"""
    try:
        _send(settings, supplier_email, f"Новый запрос на «{product_name}»", html)
        log.info("Email sent to supplier %s for inquiry %d", supplier_email, inquiry_id)
    except Exception as exc:
        log.warning("Failed to send inquiry email to %s: %s", supplier_email, exc)


def notify_inquiry_response(
    settings: "Settings",
    buyer_email: str,
    supplier_name: str,
    product_name: str,
    response_text: str,
    inquiry_id: int,
    base_url: str = "https://tetis1.kz/sklad",
) -> None:
    """Email buyer when supplier responds to their inquiry."""
    if not buyer_email:
        return
    html = f"""
<div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto">
  <h2 style="color:#16a34a">✅ Поставщик ответил на ваш запрос</h2>
  <p>Ваш запрос на <b>«{product_name}»</b> получил ответ от поставщика <b>{supplier_name}</b>:</p>
  <blockquote style="border-left:4px solid #2563eb;margin:12px 0;padding:10px 16px;background:#f0f4ff;border-radius:0 6px 6px 0">
    {response_text}
  </blockquote>
  <p>
    <a href="{base_url}" style="background:#16a34a;color:#fff;padding:10px 20px;border-radius:6px;text-decoration:none;display:inline-block;margin-top:8px">
      Открыть склад →
    </a>
  </p>
  <p style="color:#888;font-size:12px;margin-top:24px">
    Запрос №{inquiry_id} · Sklad Marketplace
  </p>
</div>"""
    try:
        _send(settings, buyer_email, f"Ответ на ваш запрос «{product_name}»", html)
        log.info("Email sent to buyer %s for inquiry %d response", buyer_email, inquiry_id)
    except Exception as exc:
        log.warning("Failed to send response email to %s: %s", buyer_email, exc)
