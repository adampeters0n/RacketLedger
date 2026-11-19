import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0052_stripe_checkout_url_text"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StalyRozvrhSlot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "den",
                    models.PositiveSmallIntegerField(
                        choices=[
                            (0, "Pondělí"),
                            (1, "Úterý"),
                            (2, "Středa"),
                            (3, "Čtvrtek"),
                            (4, "Pátek"),
                            (5, "Sobota"),
                            (6, "Neděle"),
                        ],
                        verbose_name="Den v týdnu",
                    ),
                ),
                ("cas_od", models.TimeField(verbose_name="Začátek")),
                ("delka_minut", models.PositiveIntegerField(default=60, verbose_name="Délka (min)")),
                ("format", models.CharField(max_length=120, verbose_name="Formát")),
                ("kurt", models.CharField(max_length=64, verbose_name="Kurt")),
                ("poznamka", models.CharField(blank=True, max_length=240, verbose_name="Poznámka")),
                (
                    "hraci",
                    models.ManyToManyField(
                        blank=True,
                        related_name="staly_rozvrh_sloty",
                        to="core.hrac",
                        verbose_name="Hráči",
                    ),
                ),
                (
                    "trener",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="staly_rozvrh_sloty",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Trenér",
                    ),
                ),
            ],
            options={
                "verbose_name": "Stálý rozvrh – slot",
                "verbose_name_plural": "Stálý rozvrh – sloty",
                "ordering": ("den", "cas_od", "id"),
            },
        ),
        migrations.CreateModel(
            name="PredpokladanySkip",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("datum", models.DateField(verbose_name="Datum")),
                (
                    "staly_slot",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="predpokladane_skip",
                        to="core.stalyrozvrhslot",
                        verbose_name="Stálý slot",
                    ),
                ),
            ],
            options={
                "verbose_name": "Předpokládaný rozvrh – přeskočení",
                "verbose_name_plural": "Předpokládaný rozvrh – přeskočení",
                "ordering": ("datum", "staly_slot_id"),
                "unique_together": {("datum", "staly_slot")},
            },
        ),
        migrations.CreateModel(
            name="PredpokladanySlot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("datum", models.DateField(verbose_name="Datum")),
                ("cas_od", models.TimeField(verbose_name="Začátek")),
                ("delka_minut", models.PositiveIntegerField(default=60, verbose_name="Délka (min)")),
                ("format", models.CharField(max_length=120, verbose_name="Formát")),
                ("kurt", models.CharField(max_length=64, verbose_name="Kurt")),
                ("poznamka", models.CharField(blank=True, max_length=240, verbose_name="Poznámka")),
                (
                    "hraci",
                    models.ManyToManyField(
                        blank=True,
                        related_name="predpokladane_sloty",
                        to="core.hrac",
                        verbose_name="Hráči",
                    ),
                ),
                (
                    "trener",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="predpokladane_sloty",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Trenér",
                    ),
                ),
                (
                    "zdroj_staly",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="predpokladane_override",
                        to="core.stalyrozvrhslot",
                        verbose_name="Zdrojový stálý slot",
                    ),
                ),
            ],
            options={
                "verbose_name": "Předpokládaný rozvrh – slot",
                "verbose_name_plural": "Předpokládaný rozvrh – sloty",
                "ordering": ("datum", "cas_od", "id"),
            },
        ),
    ]
