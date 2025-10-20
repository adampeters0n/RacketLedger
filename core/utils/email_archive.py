# core/utils/email_archive.py
from django.core.mail import EmailMessage
from email.utils import formatdate, make_msgid
import imaplib, datetime, os


def send_and_append_to_sent(subject, body, to, html_body=None, cc=None, bcc=None, attachments=None):
    # 1) Bezpečné FROM: EMAIL_FROM -> DEFAULT_FROM_EMAIL -> EMAIL_HOST_USER
    from_email = (
        os.environ.get("EMAIL_FROM")
        or os.environ.get("DEFAULT_FROM_EMAIL")
        or os.environ.get("EMAIL_HOST_USER")
    )
    if not from_email:
        raise RuntimeError("Chybí EMAIL_FROM/DEFAULT_FROM_EMAIL/EMAIL_HOST_USER v prostředí.")

    # 2) Sestavení a odeslání přes SMTP (Django)
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

    msg.send(fail_silently=False)  # pokud selže, vyhodí výjimku -> 500 dá smysl

    # 3) Uložení kopie do Odeslané přes IMAP (best-effort)
    raw_bytes = msg.message().as_bytes()
    host = os.environ.get("IMAP_HOST", "imap.volny.cz")
    port = int(os.environ.get("IMAP_PORT", "993"))
    user = os.environ.get("EMAIL_HOST_USER")
    pwd  = os.environ.get("EMAIL_HOST_PASSWORD")
    preferred = os.environ.get("IMAP_SENT_MAILBOX")  # <<< ručně zadaná schránka

    ok_archive = False
    try:
        M = imaplib.IMAP4_SSL(host, port)
        try:
            M.login(user, pwd)

            sent_box = None

            # 0) preferuj ručně zadanou schránku (ASCII název)
            if preferred:
                if M.select(f'"{preferred}"')[0] == "OK":
                    sent_box = preferred

            # 1) zkus \Sent z LISTu
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

            # 2) obvyklé ASCII názvy (bez diakritiky)
            if not sent_box:
                for name in ["INBOX.Sent", "Sent", "Sent Items", "INBOX.Sent Items", "Sent Messages"]:
                    if M.select(f'"{name}"')[0] == "OK":
                        sent_box = name
                        break

            # 3) fallback – vytvoř vlastní ASCII složku
            if not sent_box:
                for name in ["INBOX.Sent Messages", "Sent Messages", "INBOX.Sent", "Sent"]:
                    try:
                        M.create(name)
                    except Exception:
                        pass
                    if M.select(f'"{name}"')[0] == "OK":
                        sent_box = name
                        break

            # 4) APPEND – aware UTC čas + správné flagy
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

