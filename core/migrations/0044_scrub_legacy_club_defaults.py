# Generated manually for white-label scrub of legacy club defaults

from django.db import migrations

from core.club_seed import PRODUCT_DEFAULTS

_LEGACY_NAZEV = {
    "tenis systém čimice",
    "tenis system čimice",
    "tenissystém čimice",
}

_LEGACY_EMAIL_MARKERS = (
    "čimice",
    "kptenis@",
    "kateřina peterková",
    "katerina peterkova",
)

_LEGACY_UCET_1 = {"účet 1 aj sport", "ucet 1 aj sport", "aj sport"}
_LEGACY_UCET_2 = {"účet 2 káťa", "ucet 2 kata", "káťa", "kata"}


def _scrub(apps, schema_editor):
    SystemNastaveni = apps.get_model("core", "SystemNastaveni")
    VyuctovaniNastaveni = apps.get_model("core", "VyuctovaniNastaveni")

    for nast in SystemNastaveni.objects.all():
        changed = False
        nazev = (nast.nazev_klubu or "").strip()
        if nazev.casefold() in _LEGACY_NAZEV or "čimice" in nazev.casefold():
            nast.nazev_klubu = PRODUCT_DEFAULTS["nazev_klubu"]
            changed = True

        for field, default in (
            ("email_odesilatel", PRODUCT_DEFAULTS["email_odesilatel"]),
            ("email_predmet_prefix", PRODUCT_DEFAULTS["email_predmet_prefix"]),
            ("email_podpis", PRODUCT_DEFAULTS["email_podpis"]),
        ):
            val = (getattr(nast, field) or "").casefold()
            if any(m in val for m in _LEGACY_EMAIL_MARKERS):
                setattr(nast, field, default)
                changed = True

        if changed:
            nast.save()

    for vyuct in VyuctovaniNastaveni.objects.all():
        changed = False
        u1 = (vyuct.ucet_nazev_1 or "").strip().casefold()
        u2 = (vyuct.ucet_nazev_2 or "").strip().casefold()
        if u1 in _LEGACY_UCET_1 or "aj sport" in u1:
            vyuct.ucet_nazev_1 = PRODUCT_DEFAULTS["ucet_nazev_1"]
            changed = True
        if u2 in _LEGACY_UCET_2 or "káťa" in u2 or "kata" in u2:
            vyuct.ucet_nazev_2 = PRODUCT_DEFAULTS["ucet_nazev_2"]
            changed = True
        if changed:
            vyuct.save()


def _noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0043_user_preference_theme"),
    ]

    operations = [
        migrations.RunPython(_scrub, _noop),
    ]
