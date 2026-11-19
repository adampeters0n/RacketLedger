from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0066_trenerprofil_sazba_za_vyplet'),
    ]

    operations = [
        migrations.AddField(
            model_name="uzivatelskyvzhled",
            name="jazyk",
            field=models.CharField(
                blank=True,
                choices=[
                    ("cs", "Čeština"),
                    ("en", "English"),
                    ("de", "Deutsch"),
                    ("sk", "Slovenčina"),
                    ("pl", "Polski"),
                    ("es", "Español"),
                    ("fr", "Français"),
                    ("it", "Italiano"),
                    ("nl", "Nederlands"),
                    ("pt", "Português"),
                    ("ru", "Русский"),
                    ("uk", "Українська"),
                ],
                default="",
                help_text="Jen pro váš účet. Prázdné = výchozí jazyk klubu.",
                max_length=10,
                verbose_name="Jazyk rozhraní",
            ),
        ),
        migrations.AddField(
            model_name="uzivatelskyvzhled",
            name="radku_na_stranku",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[(10, "10"), (25, "25"), (50, "50"), (100, "100"), (200, "200")],
                help_text="Jen pro váš účet. Prázdné = nastavení klubu.",
                null=True,
                verbose_name="Řádků na stránku v tabulkách",
            ),
        ),
        migrations.AddField(
            model_name="uzivatelskyvzhled",
            name="vychozi_delka_minut",
            field=models.PositiveSmallIntegerField(
                blank=True,
                choices=[
                    (30, "30 min"),
                    (45, "45 min"),
                    (60, "1 h"),
                    (90, "1,5 h"),
                    (120, "2 h"),
                    (150, "2,5 h"),
                    (180, "3 h"),
                ],
                help_text="Předvyplní se při přidání tréninku.",
                null=True,
                verbose_name="Výchozí délka tréninku",
            ),
        ),
        migrations.AddField(
            model_name="uzivatelskyvzhled",
            name="vychozi_kurt",
            field=models.CharField(
                blank=True,
                choices=[
                    ("HALA", "Hala"),
                    ("VENEK", "Venku"),
                    ("SLUZBA", "Služba"),
                ],
                default="",
                help_text="Předvyplní se při přidání tréninku.",
                max_length=8,
                verbose_name="Výchozí kurt",
            ),
        ),
    ]
