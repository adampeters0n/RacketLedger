from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0063_uzivatelsky_vzhled_auto_castka"),
    ]

    operations = [
        migrations.AddField(
            model_name="vyuctovaninastaveni",
            name="hromadne_surplus",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("5000.00"),
                help_text="Při hromadném odeslání: požadovaná částka = aktuální dluh hráče + tento surplus. Při kladném kreditu se pošle jen surplus. Výchozí hodnota pro výběr v okně hromadného odeslání.",
                max_digits=10,
                verbose_name="Surplus u hromadného vyúčtování",
            ),
        ),
        migrations.AddField(
            model_name="vyuctovaninastaveni",
            name="ucet_nazev_3",
            field=models.CharField(default="Účet 3", max_length=64, verbose_name="Název účtu – varianta 3"),
        ),
        migrations.AddField(
            model_name="vyuctovaninastaveni",
            name="ucet_varianta_3",
            field=models.CharField(blank=True, default="", max_length=32, verbose_name="Číslo účtu – varianta 3"),
        ),
        migrations.AlterField(
            model_name="vyuctovaninastaveni",
            name="email_variant",
            field=models.CharField(
                choices=[("1", "Účet 1"), ("2", "Účet 2"), ("3", "Účet 3")],
                default="1",
                max_length=1,
                verbose_name="Výchozí varianta e-mailu",
            ),
        ),
    ]
