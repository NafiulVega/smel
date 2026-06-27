from django.core.management.base import BaseCommand
from app.models import Group, Channel
from datetime import time


class Command(BaseCommand):
    help = 'Seed database'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.MIGRATE_HEADING('Memulai seeding data...'))

        self.stdout.write(self.style.SUCCESS('Seeding selesai!'))