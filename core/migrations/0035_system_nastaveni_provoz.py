from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0034_theme_seda"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemnastaveni",
            name="kontakt_adresa",
            field=models.CharField(
                blank=True,
                default="",
                max_length=200,
                verbose_name="Adresa klubu",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="kontakt_email",
            field=models.EmailField(
                blank=True,
                default="",
                help_text="Zobrazí se na veřejné stránce a v patičce e-mailů.",
                max_length=254,
                verbose_name="Kontaktní e-mail",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="kontakt_telefon",
            field=models.CharField(
                blank=True,
                default="",
                max_length=32,
                verbose_name="Telefon",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="rozvrh_do_hodina",
            field=models.PositiveSmallIntegerField(
                default=22,
                verbose_name="Rozvrh do (hodina)",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="rozvrh_od_hodina",
            field=models.PositiveSmallIntegerField(
                default=6,
                verbose_name="Rozvrh od (hodina)",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="vychozi_delka_minut",
            field=models.PositiveSmallIntegerField(
                default=60,
                verbose_name="Výchozí délka tréninku (min)",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="vychozi_kurt",
            field=models.CharField(
                choices=[("VENEK", "Venku"), ("HALA", "Hala"), ("SLUZBA", "Služba (neplatí pro kurt)")],
                default="HALA",
                max_length=8,
                verbose_name="Výchozí kurt",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="vychozi_zobrazeni_rozvrhu",
            field=models.CharField(
                choices=[("week", "Týden"), ("day", "Den")],
                default="week",
                max_length=8,
                verbose_name="Výchozí zobrazení rozvrhu",
            ),
        ),
    ]
