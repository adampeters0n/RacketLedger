from django.db import migrations, models


def fill_sezona_from_kurt(apps, schema_editor):
    Cenik = apps.get_model("core", "Cenik")
    Trening = apps.get_model("core", "Trening")

    kurt_to_sezona = {
        "Venku": "Léto",
        "VENEK": "Léto",
        "Venek": "Léto",
        "Hala": "Zima",
        "HALA": "Zima",
    }

    for Model in (Cenik, Trening):
        for row in Model.objects.all().iterator():
            if (getattr(row, "sezona", None) or "").strip():
                continue
            sezona = kurt_to_sezona.get((row.kurt or "").strip(), "")
            if sezona:
                Model.objects.filter(pk=row.pk).update(sezona=sezona)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0045_free_text_format_kurt"),
    ]

    operations = [
        migrations.AddField(
            model_name="cenik",
            name="sezona",
            field=models.CharField(blank=True, default="", max_length=64, verbose_name="Sezóna"),
        ),
        migrations.AddField(
            model_name="trening",
            name="sezona",
            field=models.CharField(blank=True, default="", max_length=64, verbose_name="Sezóna"),
        ),
        migrations.RunPython(fill_sezona_from_kurt, migrations.RunPython.noop),
        migrations.RemoveIndex(
            model_name="cenik",
            name="core_cenik_format_7d5e8a_idx",
        ),
        migrations.AddIndex(
            model_name="cenik",
            index=models.Index(
                fields=["format", "sezona", "kurt", "platnost_od", "platnost_do"],
                name="core_cenik_format_sezona_idx",
            ),
        ),
    ]
