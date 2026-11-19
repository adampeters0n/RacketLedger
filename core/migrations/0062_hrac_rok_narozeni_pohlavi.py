from django.db import migrations, models


def forwards_datum_to_rok(apps, schema_editor):
    Hrac = apps.get_model("core", "Hrac")
    for h in Hrac.objects.exclude(datum_narozeni__isnull=True).iterator():
        Hrac.objects.filter(pk=h.pk).update(rok_narozeni=h.datum_narozeni.year)
    # staré „Jiné / neuvedeno“ → prázdné
    Hrac.objects.filter(pohlavi="X").update(pohlavi="")


def backwards_rok_to_datum(apps, schema_editor):
    import datetime

    Hrac = apps.get_model("core", "Hrac")
    for h in Hrac.objects.exclude(rok_narozeni__isnull=True).iterator():
        Hrac.objects.filter(pk=h.pk).update(
            datum_narozeni=datetime.date(int(h.rok_narozeni), 1, 1)
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0061_hrac_profil_pole'),
    ]

    operations = [
        migrations.AddField(
            model_name="hrac",
            name="rok_narozeni",
            field=models.PositiveSmallIntegerField(
                blank=True, null=True, verbose_name="Rok narození"
            ),
        ),
        migrations.RunPython(forwards_datum_to_rok, backwards_rok_to_datum),
        migrations.RemoveField(
            model_name="hrac",
            name="datum_narozeni",
        ),
        migrations.AlterField(
            model_name="hrac",
            name="pohlavi",
            field=models.CharField(
                blank=True,
                choices=[("M", "Muž"), ("Z", "Žena")],
                default="",
                max_length=1,
                verbose_name="Pohlaví",
            ),
        ),
    ]
