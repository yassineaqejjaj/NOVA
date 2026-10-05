"""Transactional e-mail (verification and password-reset codes).

Production sends through SMTP (``NOVA_SMTP_*``). Outside production, without an SMTP server, messages go to an
in-memory outbox (and the log) so sign-up can be developed and tested end to end.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr

from nova.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class OutboxMessage:
    to: str
    subject: str
    text: str
    code: str | None = None
    sent_at: datetime = field(default_factory=lambda: datetime.now(UTC))


OUTBOX: deque[OutboxMessage] = deque(maxlen=200)


class MailerError(Exception):
    pass


def _send_smtp(message: EmailMessage) -> None:
    settings = get_settings()
    context = ssl.create_default_context()
    if settings.smtp_port == 465:
        server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=context, timeout=20)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
    with server:
        if settings.smtp_port != 465 and settings.smtp_starttls:
            server.starttls(context=context)
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)


async def send_email(to: str, subject: str, text: str, html: str, *, code: str | None = None) -> None:
    settings = get_settings()
    if settings.email_outbox:
        OUTBOX.append(OutboxMessage(to=to, subject=subject, text=text, code=code))
        log.warning("E-mail outbox (no SMTP configured): to=%s subject=%s code=%s", to, subject, code)
        return
    if not settings.smtp_configured:
        raise MailerError("E-mail is not configured.")
    name, address = parseaddr(settings.smtp_from)
    message = EmailMessage()
    message["From"] = formataddr((name or "NOVA", address))
    message["To"] = to
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain=address.split("@")[-1] if "@" in address else None)
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    try:
        await asyncio.to_thread(_send_smtp, message)
    except (OSError, smtplib.SMTPException) as exc:
        log.error("SMTP delivery failed: %s", type(exc).__name__)
        raise MailerError("The e-mail could not be sent.") from exc


def last_code(email: str) -> str | None:
    """Latest code sent to ``email`` (development outbox only)."""
    return next((m.code for m in reversed(OUTBOX) if m.to == email.lower() and m.code), None)


# --- Templates ------------------------------------------------------------------------------------

CODE_COPY = {
    "signup": {
        "en": (
            "Your NOVA verification code",
            "Confirm your e-mail address to create your NOVA account.",
            "Enter this code to finish signing up:",
        ),
        "fr": (
            "Votre code de vérification NOVA",
            "Confirmez votre adresse e-mail pour créer votre compte NOVA.",
            "Saisissez ce code pour finaliser votre inscription :",
        ),
    },
    "reset": {
        "en": (
            "Reset your NOVA password",
            "Someone asked to reset the password of your NOVA account.",
            "Enter this code to choose a new password:",
        ),
        "fr": (
            "Réinitialisation de votre mot de passe NOVA",
            "Une réinitialisation du mot de passe de votre compte NOVA a été demandée.",
            "Saisissez ce code pour choisir un nouveau mot de passe :",
        ),
    },
}
FOOTER = {
    "en": "The code expires in {minutes} minutes. If you did not ask for it, you can ignore this e-mail.",
    "fr": "Le code expire dans {minutes} minutes. Si vous n’êtes pas à l’origine de cette demande, ignorez cet e-mail.",
}


def code_email(purpose: str, lang: str, code: str, minutes: int) -> tuple[str, str, str]:
    lang = "fr" if lang == "fr" else "en"
    subject, intro, lead = CODE_COPY[purpose][lang]
    footer = FOOTER[lang].format(minutes=minutes)
    text = f"{intro}\n\n{lead}\n\n    {code}\n\n{footer}\n\n— NOVA · Devoteam"
    spaced = " ".join(code)
    html = f"""<!doctype html><html><body style="margin:0;background:#0b0b10;font-family:Montserrat,Helvetica,Arial,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:40px 16px"><tr><td align="center">
<table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;background:#14141c;border-radius:16px;padding:36px;color:#f4f4f6">
<tr><td style="font-size:22px;letter-spacing:6px;font-weight:600">NOVA</td></tr>
<tr><td style="padding-top:24px;font-size:15px;line-height:1.6;color:#d6d6de">{intro}</td></tr>
<tr><td style="padding-top:12px;font-size:15px;color:#d6d6de">{lead}</td></tr>
<tr><td align="center" style="padding:28px 0"><div style="display:inline-block;padding:16px 28px;border-radius:12px;background:#1f1f2b;border:1px solid #f8485e55;font-size:30px;letter-spacing:10px;font-weight:600;color:#ffffff">{spaced}</div></td></tr>
<tr><td style="font-size:12.5px;line-height:1.6;color:#9a9aa8">{footer}</td></tr>
<tr><td style="padding-top:28px;font-size:12px;color:#6f6f7d">NOVA · Powered by Devoteam</td></tr>
</table></td></tr></table></body></html>"""
    return subject, text, html
