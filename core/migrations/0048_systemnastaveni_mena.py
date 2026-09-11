# Generated manually for SystemNastaveni.mena

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0047_vychozi_sezona"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemnastaveni",
            name="mena",
            field=models.CharField(
                choices=[
                    ("CZK", "Kč – Česká koruna"),
                    ("EUR", "€ – Euro"),
                    ("USD", "$ – Americký dolar"),
                    ("GBP", "£ – Britská libra"),
                    ("CHF", "CHF – Švýcarský frank"),
                    ("PLN", "zł – Polský zlotý"),
                    ("HUF", "Ft – Maďarský forint"),
                ],
                default="CZK",
                help_text="Zobrazí se u všech cen a částek v systému (Kč, €, $ …).",
                max_length=8,
                verbose_name="Měna",
            ),
        ),
        migrations.AlterField(
            model_name="systemnastaveni",
            name="prah_dluhu_dashboard",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="0 = všichni se záporným kreditem, −1000 = dluh od 1000 jednotek měny.",
                max_digits=10,
                verbose_name="Práh dluhu na dashboardu",
            ),
        ),
    ]
