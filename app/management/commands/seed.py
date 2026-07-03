from django.core.management.base import BaseCommand
from app.models import GroupConfig
from datetime import time


class Command(BaseCommand):
    help = 'Seed database dengan konfigurasi awal grup lampu jalan'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.MIGRATE_HEADING('Memulai seeding data...'))

        # Buat GroupConfig default jika belum ada
        config, created = GroupConfig.objects.get_or_create(
            id=1,
            defaults={
                'name': 'Jalan Nasional',
                'is_active': True,
                'on_time': time(17, 30),
                'off_time': time(5, 0),
                'dimming_enabled': False,
                'dimming_start': time(1, 0),
                'dimming_end': time(5, 0),
                'ch1_current_min': 0.33,
                'ch2_current_min': 0.33,
                'data_send_interval': 5,
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(
                f'  [OK] GroupConfig "{config.name}" berhasil dibuat'
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f'  [SKIP] GroupConfig "{config.name}" sudah ada, skip'
            ))

        self.stdout.write(self.style.SUCCESS('Seeding selesai!'))