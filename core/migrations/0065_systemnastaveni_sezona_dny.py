from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0064_vyuctovani_surplus_ucet3"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemnastaveni",
            name="sezona_venek_od_den",
            field=models.PositiveSmallIntegerField(
                default=1,
                verbose_name="Venkovní sezóna od (den)",
            ),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="sezona_venek_do_den",
            field=models.PositiveSmallIntegerField(
                default=31,
                verbose_name="Venkovní sezóna do (den)",
            ),
        ),
    ]
