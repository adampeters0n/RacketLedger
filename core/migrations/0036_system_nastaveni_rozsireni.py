from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0035_system_nastaveni_provoz"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemnastaveni",
            name="slogan",
            field=models.CharField(
                blank=True,
                default="",
                max_length=160,
                verbose_name="Slogan",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="logo",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="club/",
                verbose_name="Logo klubu",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="favicon",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="club/",
                verbose_name="Favicon",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="email_odesilatel",
            field=models.CharField(
                blank=True,
                default="Tenis Čimice <kptenis@volny.cz>",
                help_text="Formát: Jméno <email@domena.cz>",
                max_length=120,
                verbose_name="Odesílatel e-mailů",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="email_predmet_prefix",
            field=models.CharField(
                blank=True,
                default="[Tenis Čimice] ",
                max_length=60,
                verbose_name="Prefix předmětu e-mailu",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="email_podpis",
            field=models.TextField(
                blank=True,
                default="S pozdravem,\n\nKateřina Peterková\nTenis Čimice",
                verbose_name="Podpis e-mailů",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="sezona_venek_od",
            field=models.PositiveSmallIntegerField(
                default=4,
                verbose_name="Venkovní sezóna od (měsíc)",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="sezona_venek_do",
            field=models.PositiveSmallIntegerField(
                default=10,
                verbose_name="Venkovní sezóna do (měsíc)",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="sezona_automaticky_kurt",
            field=models.BooleanField(
                default=True,
                verbose_name="Automaticky volit kurt dle sezóny",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="prah_dluhu_dashboard",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                help_text="0 = všichni se záporným kreditem, −1000 = dluh od 1000 Kč",
                max_digits=10,
                verbose_name="Práh dluhu na dashboardu (Kč)",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="zvyraznit_zaporny_kredit",
            field=models.BooleanField(
                default=True,
                verbose_name="Zvýraznit záporný kredit v seznamu hráčů",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="radku_na_stranku",
            field=models.PositiveSmallIntegerField(
                choices=[(25, "25"), (50, "50"), (100, "100")],
                default=50,
                verbose_name="Řádků na stránku v tabulkách",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="vlastni_barvy",
            field=models.BooleanField(
                default=False,
                verbose_name="Vlastní barvy (místo palety)",
            ),
        ),
    ]
