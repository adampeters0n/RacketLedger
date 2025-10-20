# utils/email_archive.py
from django.core.mail import EmailMessage
from email.utils import formatdate, make_msgid
import imaplib, datetime, os

def send_and_append_to_sent(subject, body, to, html_body=None, cc=None, bcc=None, attachments=None):
    # Bezpečné zjištění from adresy: EMAIL_FROM -> DEFAULT_FROM_EMAIL -> EMAIL_HOST_USER
    from_email = (
        os.environ.get("EMAIL_FROM")
        or os.environ.get("DEFAULT_FROM_EMAIL")
        or os.environ.get("EMAIL_HOST_USER")
    )
    if not from_email:
        # Poslední záchrana – raději explicitně vyhoďme srozumitelnou chybu než KeyError
        raise RuntimeError("Chybí EMAIL_FROM/DEFAULT_FROM_EMAIL/EMAIL_HOST_USER v prostředí.")

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

    # 1) Odeslat přes SMTP (Django settings)
    msg.send(fail_silently=False)

    # 2) Uložit kopii do Odeslané přes IMAP
    raw_bytes = msg.message().as_bytes()
    host = os.environ.get("IMAP_HOST", "imap.volny.cz")
    port = int(os.environ.get("IMAP_PORT", "993"))
    user = os.environ.get("EMAIL_HOST_USER")
    pwd  = os.environ.get("EMAIL_HOST_PASSWORD")

    M = imaplib.IMAP4_SSL(host, port)
    try:
        M.login(user, pwd)

        sent_box = None
        typ, boxes = M.list()
        if typ == "OK" and boxes:
            for b in boxes:
                line = b.decode("utf-8", "ignore")
                if "\\Sent" in line:
                    sent_box = line.split(' "')[-1].rstrip('"')
                    break

        if not sent_box:
            for name in ['Sent', 'Odeslaná', 'Odeslaná pošta', 'Odeslané', 'Sent Items']:
                if M.select(f'"{name}"')[0] == "OK":
                    sent_box = name
                    break

        if not sent_box:
            sent_box = "Kopie odeslané"
            M.create(sent_box)
            M.select(f'"{sent_box}"')

        M.append(sent_box, "\\Seen", imaplib.Time2Internaldate(datetime.datetime.utcnow()), raw_bytes)
        return True, True
    finally:
        try:
            M.logout()
        except Exception:
            pass
