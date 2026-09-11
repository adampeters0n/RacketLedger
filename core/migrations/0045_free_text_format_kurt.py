from django.db import migrations, models


VYCHOZI_KODY = {
    "SOLO_C": "Solo (1 hráč) - Člen",
    "DVOJICE_C": "Dvojice (2 hráči) - Člen",
    "TROJICE_C": "Trojice (3 hráči) - Člen",
    "CTVRICE_C": "Čtveřice (4 hráči) - Člen",
    "PETICE": "Pětice (5 a více hráčů) - Člen",
    "SOLO_NC": "Solo (1 hráč) - Nečlen",
    "DVOJICE_NC": "Dvojice (2 hráči) - Nečlen",
    "TROJICE_NC": "Trojice (3 hráči) - Nečlen",
    "CTVRICE_NC": "Čtveřice (4 hráči) - Nečlen",
    "SOBOTA_TRE": "Trénink - Sobota",
    "KURT_TRE": "Kurt - Rezervace",
    "V_STAND": "Výplet - Standard",
    "V_EXCEL": "Výplet - Express",
    "V_VLAST": "Výplet - Vlastní",
}

KURT_MAP = {
    "VENEK": "Venku",
    "HALA": "Hala",
    "SLUZBA": "Služba",
}


def forwards_free_text(apps, schema_editor):
    CenikFormat = apps.get_model("core", "CenikFormat")
    Cenik = apps.get_model("core", "Cenik")
    Trening = apps.get_model("core", "Trening")
    SystemNastaveni = apps.get_model("core", "SystemNastaveni")

    kod_to_nazev = dict(VYCHOZI_KODY)
    for fmt in CenikFormat.objects.all():
        kod_to_nazev[fmt.kod] = fmt.nazev

    def map_format(value: str) -> str:
        if not value:
            return value
        return kod_to_nazev.get(value, value)

    def map_kurt(value: str) -> str:
        if not value:
            return value
        return KURT_MAP.get(value, value)

    for row in Cenik.objects.all().iterator():
        new_format = map_format(row.format)
        new_kurt = map_kurt(row.kurt)
        if new_format != row.format or new_kurt != row.kurt:
            Cenik.objects.filter(pk=row.pk).update(format=new_format, kurt=new_kurt)

    for row in Trening.objects.all().iterator():
        new_format = map_format(row.format)
        new_kurt = map_kurt(row.kurt)
        if new_format != row.format or new_kurt != row.kurt:
            Trening.objects.filter(pk=row.pk).update(format=new_format, kurt=new_kurt)

    for row in SystemNastaveni.objects.all().iterator():
        new_kurt = map_kurt(row.vychozi_kurt)
        if new_kurt != row.vychozi_kurt:
            SystemNastaveni.objects.filter(pk=row.pk).update(vychozi_kurt=new_kurt)

    CenikFormat.objects.all().delete()


def noop_reverse(apps, schema_editor):
    # Data conversion is not safely reversible.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0044_scrub_legacy_club_defaults"),
    ]

    operations = [
        migrations.AlterField(
            model_name="cenik",
            name="format",
            field=models.CharField(max_length=120, verbose_name="Typ tréninku"),
        ),
        migrations.AlterField(
            model_name="cenik",
            name="kurt",
            field=models.CharField(max_length=64, verbose_name="Kurt"),
        ),
        migrations.AlterField(
            model_name="trening",
            name="format",
            field=models.CharField(max_length=120, verbose_name="Typ tréninku"),
        ),
        migrations.AlterField(
            model_name="trening",
            name="kurt",
            field=models.CharField(max_length=64, verbose_name="Kurt"),
        ),
        migrations.AlterField(
            model_name="systemnastaveni",
            name="vychozi_kurt",
            field=models.CharField(
                blank=True,
                default="Hala",
                max_length=64,
                verbose_name="Výchozí kurt",
            ),
        ),
        migrations.RunPython(forwards_free_text, noop_reverse),
    ]
