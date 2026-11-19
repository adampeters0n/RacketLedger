from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0065_systemnastaveni_sezona_dny'),
    ]

    operations = [
        migrations.AddField(
            model_name="trenerprofil",
            name="sazba_za_vyplet",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("300.00"),
                help_text="Paušální odměna trenérovi za jednu službu výpletu.",
                max_digits=9,
                verbose_name="Sazba za výplet",
            ),
        ),
    ]
