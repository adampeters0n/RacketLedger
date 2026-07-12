"""Obnoví poškozené hodnoty pole format (literál „format“) v ceníku a trénincích."""
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Cenik, CenikFormat, Dochazka, Transakce, Trening

CORRUPTED = "format"

# Venkovní ceník dle ceny za hodinu (typické pořadí solo → čtveřice)
CENIK_VENEK_BY_PRICE = {
    "200.00": Cenik.Format.SOLO_C,
    "350.00": Cenik.Format.DVOJICE_C,
    "500.00": Cenik.Format.TROJICE_C,
    "650.00": Cenik.Format.CTVRICE_C,
}

PLAYERS_TO_FORMAT = {
    1: Cenik.Format.SOLO_C,
    2: Cenik.Format.DVOJICE_C,
    3: Cenik.Format.TROJICE_C,
    4: Cenik.Format.CTVRICE_C,
}


def _display_to_code():
    return {label.lower(): code for code, label in CenikFormat.VYCHOZI_KODY.items()}


def _format_from_transakce_popis(popis: str, display_map: dict[str, str]) -> str | None:
    if not popis or not popis.startswith("Trénink "):
        return None
    label = popis.split("•", 1)[0].removeprefix("Trénink ").strip().lower()
    return display_map.get(label)


def _format_from_player_count(trening: Trening) -> str:
    pocet = Dochazka.objects.filter(trening=trening, prisel=True).count()
    if not pocet:
        pocet = Dochazka.objects.filter(trening=trening).count()
    if pocet >= 5:
        return Cenik.Format.PETICE
    return PLAYERS_TO_FORMAT.get(pocet, Cenik.Format.SOLO_C)


class Command(BaseCommand):
    help = "Obnoví formáty po chybné migraci/správě (hodnota „format“)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Jen vypíše plánované změny, nic neuloží.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        display_map = _display_to_code()
        stats = Counter()

        with transaction.atomic():
            for cenik in Cenik.objects.filter(format=CORRUPTED):
                key = f"{cenik.cena_za_hodinu:.2f}"
                novy = CENIK_VENEK_BY_PRICE.get(key)
                if not novy:
                    self.stderr.write(
                        self.style.ERROR(
                            f"Ceník #{cenik.pk}: neznámá cena {key} Kč/h ({cenik.kurt}) – přeskočeno"
                        )
                    )
                    stats["cenik_skipped"] += 1
                    continue
                self.stdout.write(
                    f"Ceník #{cenik.pk}: {CORRUPTED!r} → {novy} ({cenik.get_kurt_display()}, {key} Kč/h)"
                )
                if not dry_run:
                    Cenik.objects.filter(pk=cenik.pk).update(format=novy)
                stats["cenik_fixed"] += 1

            for trening in Trening.objects.filter(format=CORRUPTED).prefetch_related("transakce_set"):
                tx = trening.transakce_set.first()
                novy = _format_from_transakce_popis(tx.popis, display_map) if tx else None
                zdroj = "transakce"
                if not novy:
                    novy = _format_from_player_count(trening)
                    zdroj = "počet hráčů"
                self.stdout.write(
                    f"Trénink #{trening.pk} ({trening.datum:%Y-%m-%d}): "
                    f"{CORRUPTED!r} → {novy} [{zdroj}]"
                )
                if not dry_run:
                    Trening.objects.filter(pk=trening.pk).update(format=novy)
                stats["trening_fixed"] += 1

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Hotovo ({'dry-run' if dry_run else 'uloženo'}): "
                f"ceník {stats['cenik_fixed']} opraveno, "
                f"{stats['cenik_skipped']} přeskočeno; "
                f"tréninků {stats['trening_fixed']} opraveno."
            )
        )
