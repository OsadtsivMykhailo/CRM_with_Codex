import time

from django.core.management.base import BaseCommand

from crm.mailing import claim_next_campaign, process_campaign


class Command(BaseCommand):
    help = "Обробляє чергу email-розсилок CRM."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Обробити доступні розсилки й завершити роботу.")
        parser.add_argument("--interval", type=float, default=2.0, help="Інтервал перевірки черги у секундах.")

    def handle(self, *args, **options):
        self.stdout.write("EMAIL_WORKER_STARTING")
        self.stdout.write(self.style.SUCCESS("EMAIL_WORKER_READY"))
        while True:
            campaign = claim_next_campaign()
            if campaign:
                self.stdout.write(f"Обробка розсилки #{campaign.pk}: {campaign.subject}")
                process_campaign(campaign)
                continue
            if options["once"]:
                break
            time.sleep(max(options["interval"], 0.5))
