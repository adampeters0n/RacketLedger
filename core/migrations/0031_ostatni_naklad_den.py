from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0030_ostatni_naklad_najem"),
    ]

    operations = [
        migrations.AlterField(
            model_name="ostatninaklad",
            name="mesic",
            field=models.DateField(
                help_text="Den, ke kterému se náklad vztahuje",
                verbose_name="Datum",
            ),
        ),
    ]
