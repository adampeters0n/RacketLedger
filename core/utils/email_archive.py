# core/utils/email_archive.py
from django.core.mail import EmailMessage
from email.utils import formatdate, make_msgid
import imaplib, datetime, os, logging

log = logging.getLogger(__name__)

def _find_sent_mailbox(imap):
    typ, boxes = imap.list()
    if typ == "OK" and boxes:
        # 1) hledej \Sent
        for b in boxes:
            line = b.decode("utf-8", "ignore")
            if "\\Sent" in line:
                # vezmi přesný název z LISTu (poslední quoted string)
                name = line.split(' "/" ')[-1].strip()
                return name.strip('"')
        # 2) fallback: common názvy (case-insensitive; řeší i diakritiku částečně)
        prefer = ["sent", "odeslan", "sent items"]
        for b in boxes:
            line = b.decode("utf-8", "ignore")
            name = line.split(' "/" ')[-1].strip().strip('"')
            low = name.lower()
            if any(p in low for p in prefer):
                return name
    # 3) vytvoř vlastní schránku
    alt = "Kopie odeslané"
    imap.create(alt)
    return alt

def send_and_append_to_sent(subject, body, to, html_body=None, cc=None, bcc=None, attachments=None):
    from_email = os.environ["EMAIL_FROM"]  # např. "Tenis Čimice <kptenis@volny.cz>"
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

    # 1) odeslat
    msg.send(fail_silently=False)
    sent_ok = True

    # 2) připojit do Odeslané (nezastaví běh, když se nepovede)
    archived_ok = False
    try:
        raw_bytes = msg.message().as_bytes()
        host = os.environ.get("IMAP_HOST", "imap.volny.cz")
        port = int(os.environ.get("IMAP_PORT", "993"))
        user = os.environ["EMAIL_HOST_USER"]
        pwd  = os.environ["EMAIL_HOST_PASSWORD"]

        M = imaplib.IMAP4_SSL(host, port)
        try:
            M.login(user, pwd)
            mailbox = _find_sent_mailbox(M)
            # IMAP vyžaduje přesný název tak, jak ho vrací LIST
            M.select(f'"{mailbox}"')
            M.append(mailbox, "\\Seen", imaplib.Time2Internaldate(datetime.datetime.utcnow()), raw_bytes)
            archived_ok = True
        finally:
            try: M.logout()
            except Exception: pass
    except Exception as e:
        log.warning("IMAP append do Odeslané selhal: %s", e)

    return sent_ok, archived_ok
