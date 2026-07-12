from django.core.management.base import BaseCommand

from core.models import VyuctovaniNastaveni


class Command(BaseCommand):
    help = "Spustí měsíční vyúčtování pro všechny hráče (režim Měsíčně, od zadaného dne v měsíci)."

    def handle(self, *args, **options):
        nast = VyuctovaniNastaveni.load()
        if nast.auto_rezim != VyuctovaniNastaveni.AutoRezim.MESICNE:
            self.stdout.write(self.style.WARNING("Aktivní režim není Měsíčně – nic se nespouští."))
            return

        count = nast.spustit_mesicni_vyuctovani_vsem()
        self.stdout.write(self.style.SUCCESS(f"Měsíční vyúčtování: odesláno {count} hráčům."))
