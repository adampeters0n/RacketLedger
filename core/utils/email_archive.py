# core/utils/email_archive.py
from django.core.mail import EmailMessage
from email.utils import formatdate, make_msgid
import imaplib, datetime, os


def _resolve_from_email():
    """Odesílatel: SystemNastaveni → env → Django settings."""
    try:
        from core.models import SystemNastaveni

        val = SystemNastaveni.load().effective_from_email()
        if val:
            return val
    except Exception:
        pass
    return (
        os.environ.get("EMAIL_FROM")
        or os.environ.get("DEFAULT_FROM_EMAIL")
        or os.environ.get("EMAIL_HOST_USER")
    )


def send_and_append_to_sent(subject, body, to, html_body=None, cc=None, bcc=None, attachments=None):
    from_email = _resolve_from_email()
    if not from_email:
        raise RuntimeError("Chybí odesílatel e-mailu – nastavte ho v Nastavení nebo v prostředí.")

    msg = EmailMessage(
        subject=subject,
        body=html_body or body,
        from_email=from_email,
        to=[to] if isinstance(to, str) else to,
        cc=cc or [],
        bcc=bcc or [],
        headers={"Date": formatdate(localtime=True), "Message-ID": make_msgid()},
    )
    if html_body:
        msg.content_subtype = "html"
    for att in (attachments or []):
        msg.attach(*att)

    msg.send(fail_silently=False)

    raw_bytes = msg.message().as_bytes()
    host = os.environ.get("IMAP_HOST", "").strip()
    port = int(os.environ.get("IMAP_PORT", "993"))
    user = os.environ.get("EMAIL_HOST_USER")
    pwd  = os.environ.get("EMAIL_HOST_PASSWORD")
    preferred = os.environ.get("IMAP_SENT_MAILBOX")

    ok_archive = False
    if not host or not user or not pwd:
        return True, False

    try:
        M = imaplib.IMAP4_SSL(host, port)
        try:
            M.login(user, pwd)

            sent_box = None

            if preferred:
                if M.select(f'"{preferred}"')[0] == "OK":
                    sent_box = preferred

            if not sent_box:
                typ, boxes = M.list()
                if typ == "OK" and boxes:
                    for b in boxes:
                        line = b.decode("utf-8", "ignore")
                        if "\\Sent" in line:
                            name = line.split(' "')[-1].rstrip('"')
                            if M.select(f'"{name}"')[0] == "OK":
                                sent_box = name
                                break

            if not sent_box:
                for name in ["INBOX.Sent", "Sent", "Sent Items", "INBOX.Sent Items", "Sent Messages"]:
                    if M.select(f'"{name}"')[0] == "OK":
                        sent_box = name
                        break

            if not sent_box:
                for name in ["INBOX.Sent Messages", "Sent Messages", "INBOX.Sent", "Sent"]:
                    try:
                        M.create(name)
                    except Exception:
                        pass
                    if M.select(f'"{name}"')[0] == "OK":
                        sent_box = name
                        break

            aware_utc = datetime.datetime.now(datetime.timezone.utc)
            M.append(f'"{sent_box}"', '(\\Seen)', imaplib.Time2Internaldate(aware_utc), raw_bytes)
            ok_archive = True

        finally:
            try:
                M.logout()
            except Exception:
                pass
    except Exception:
        ok_archive = False

    return True, ok_archive
