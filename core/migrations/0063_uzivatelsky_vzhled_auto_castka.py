from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0062_hrac_rok_narozeni_pohlavi"),
    ]

    operations = [
        migrations.AddField(
            model_name="hrac",
            name="auto_castka_ceka_na_obnovu",
            field=models.BooleanField(default=False, editable=False),
        ),
        migrations.CreateModel(
            name="UzivatelskyVzhled",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("barevna_varianta", models.CharField(default="default", help_text="Paleta barev pro váš účet.", max_length=16, verbose_name="Barevná varianta")),
                ("tmavy_rezim", models.BooleanField(default=False, help_text="Tmavé pozadí a světlý text.", verbose_name="Tmavý režim")),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="vzhled", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Uživatelský vzhled",
                "verbose_name_plural": "Uživatelské vzhledy",
            },
        ),
    ]
