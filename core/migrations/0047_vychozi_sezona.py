from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0046_cenik_trening_sezona"),
    ]

    operations = [
        migrations.AlterField(
            model_name="systemnastaveni",
            name="vychozi_kurt",
            field=models.CharField(blank=True, default="", max_length=64, verbose_name="Výchozí kurt"),
        ),
        migrations.AddField(
            model_name="systemnastaveni",
            name="vychozi_sezona",
            field=models.CharField(blank=True, default="", max_length=64, verbose_name="Výchozí sezóna"),
        ),
    ]
