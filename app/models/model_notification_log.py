from django.db import models


class NotificationLog(models.Model):
    """
    Log notifikasi sistem monitoring.
    Mencatat peringatan saat arus/daya di bawah ambang batas
    atau sensor gagal merespons.
    Berelasi dengan GroupConfig untuk tracking notifikasi per grup.
    """

    CHANNEL_CHOICES = [
        (1, "Channel 1 (Pin 13)"),
        (2, "Channel 2 (Pin 12)"),
    ]

    TYPE_CHOICES = [
        ("N1", "Arus Terlalu Rendah"),
        ("N2", "Sensor Tidak Merespons"),
    ]

    STATUS_CHOICES = [
        ("active", "Aktif"),
        ("resolved", "Sudah Normal"),
        ("dismissed", "Di-dismiss"),
    ]

    group_config = models.ForeignKey(
        'GroupConfig',
        on_delete=models.CASCADE,
        related_name='notification_logs',
        null=True,
        blank=True,
        verbose_name="Grup",
        help_text="Grup konfigurasi lampu jalan",
    )
    channel = models.IntegerField(
        choices=CHANNEL_CHOICES,
        verbose_name="Channel",
        help_text="Nomor channel: 1 atau 2",
    )
    type = models.CharField(
        max_length=2,
        choices=TYPE_CHOICES,
        verbose_name="Tipe Notifikasi",
        help_text="Kode notifikasi: N1 atau N2",
    )
    message = models.TextField(
        verbose_name="Pesan",
        help_text="Pesan detail notifikasi",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Waktu Notifikasi",
        help_text="Waktu notifikasi pertama kali muncul",
    )
    resolved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Waktu Resolved",
        help_text="Waktu kondisi kembali normal (otomatis)",
    )
    dismissed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Waktu Dismissed",
        help_text="Waktu notifikasi di-dismiss manual oleh user",
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default="active",
        verbose_name="Status",
        help_text="Status notifikasi: active / resolved / dismissed",
        db_index=True,
    )

    class Meta:
        db_table = "notification_log"
        verbose_name = "Log Notifikasi"
        verbose_name_plural = "Log Notifikasi"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["group_config", "channel", "type", "status"], name="idx_notif_grp_ch_type_st"),
        ]

    def __str__(self):
        group_name = self.group_config.name if self.group_config else "N/A"
        return f"[{group_name}] [{self.type}] Ch{self.channel} - {self.get_status_display()}"
