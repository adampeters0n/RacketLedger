from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0036_system_nastaveni_rozsireni"),
    ]

    operations = [
        migrations.AddField(
            model_name="systemnastaveni",
            name="vychozi_jazyk",
            field=models.CharField(
                choices=[
                    ("cs", "Čeština"),
                    ("en", "English"),
                    ("de", "Deutsch"),
                    ("sk", "Slovenčina"),
                    ("pl", "Polski"),
                    ("es", "Español"),
                    ("fr", "Français"),
                    ("it", "Italiano"),
                    ("nl", "Nederlands"),
                    ("pt", "Português"),
                    ("ru", "Русский"),
                    ("uk", "Українська"),
                ],
                default="cs",
                max_length=10,
                verbose_name="Výchozí jazyk systému",
                help_text="Jazyk rozhraní pro všechny uživatele (lze přepsat v hlavičce).",
            ),
        ),
    ]
