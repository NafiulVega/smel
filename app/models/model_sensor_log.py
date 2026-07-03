from django.db import models


class SensorLog(models.Model):
    """
    Log pembacaan sensor PZEM-004T per channel.
    Data hanya disimpan saat relay ON dan sensor berhasil dibaca.
    """

    CHANNEL_CHOICES = [
        (1, "Channel 1 (Pin 13)"),
        (2, "Channel 2 (Pin 12)"),
    ]

    channel = models.IntegerField(
        choices=CHANNEL_CHOICES,
        verbose_name="Channel",
        help_text="Nomor channel: 1 atau 2",
    )
    timestamp = models.DateTimeField(
        verbose_name="Waktu Pembacaan",
        help_text="Waktu pembacaan sensor (WIB)",
        db_index=True,
    )
    voltage = models.FloatField(
        verbose_name="Tegangan (V)",
        help_text="Tegangan dalam Volt",
    )
    current = models.FloatField(
        verbose_name="Arus (A)",
        help_text="Arus dalam Ampere",
    )
    power = models.FloatField(
        verbose_name="Daya (W)",
        help_text="Daya dalam Watt",
    )
    energy = models.FloatField(
        verbose_name="Energi (kWh)",
        help_text="Energi kumulatif dalam kilowatt-hour",
    )
    frequency = models.FloatField(
        verbose_name="Frekuensi (Hz)",
        help_text="Frekuensi dalam Hertz",
    )
    pf = models.FloatField(
        verbose_name="Power Factor",
        help_text="Faktor daya (0-1)",
    )

    class Meta:
        db_table = "sensor_log"
        verbose_name = "Log Sensor"
        verbose_name_plural = "Log Sensor"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["channel", "timestamp"], name="idx_sensor_ch_ts"),
        ]

    def __str__(self):
        return f"Ch{self.channel} | {self.timestamp:%d/%m/%Y %H:%M:%S}"
