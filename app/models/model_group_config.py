from django.db import models
from datetime import time


class GroupConfig(models.Model):
    """
    Konfigurasi grup lampu jalan.
    Menyimpan jadwal nyala/mati, pengaturan penjarangan,
    ambang batas sensor per channel, dan tarif listrik.
    """

    name = models.CharField(
        max_length=100,
        verbose_name="Nama Grup",
        help_text="Nama grup lampu jalan, contoh: Jalan Nasional",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Grup Aktif",
        help_text="Apakah grup ini aktif atau tidak",
    )

    # Jadwal nyala/mati
    on_time = models.TimeField(
        default=time(17, 30),
        verbose_name="Jam Nyala",
        help_text="Waktu relay ON semua channel (format HH:MM)",
    )
    off_time = models.TimeField(
        default=time(5, 0),
        verbose_name="Jam Mati",
        help_text="Waktu relay OFF semua channel (format HH:MM)",
    )

    # Penjarangan (half-night dimming)
    dimming_enabled = models.BooleanField(
        default=False,
        verbose_name="Penjarangan Aktif",
        help_text="Aktifkan/nonaktifkan fitur penjarangan Channel 2",
    )
    dimming_start = models.TimeField(
        default=time(1, 0),
        verbose_name="Jam Mulai Penjarangan",
        help_text="Waktu mulai penjarangan (Channel 2 OFF)",
    )
    dimming_end = models.TimeField(
        default=time(4, 0),
        verbose_name="Jam Selesai Penjarangan",
        help_text="Waktu selesai penjarangan (Channel 2 kembali ON)",
    )

    # Ambang batas per channel
    ch1_current_min = models.FloatField(
        default=0.33,
        verbose_name="Current Min Ch1 (A)",
        help_text="Ambang batas arus minimum Channel 1 dalam Ampere",
    )
    ch2_current_min = models.FloatField(
        default=0.33,
        verbose_name="Current Min Ch2 (A)",
        help_text="Ambang batas arus minimum Channel 2 dalam Ampere",
    )

    # Pengaturan Sistem
    data_send_interval = models.IntegerField(
        default=5,
        verbose_name="Jeda Waktu Pengiriman Data (Detik)",
        help_text="Interval jeda untuk ESP32 mengirim data ke server",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Terakhir Diubah",
    )

    class Meta:
        db_table = "group_config"
        verbose_name = "Konfigurasi Grup"
        verbose_name_plural = "Konfigurasi Grup"

    def __str__(self):
        return self.name
