"""
WebSocket consumer untuk dashboard monitoring real-time.

Endpoint: ws://server:8000/ws/dashboard/

Event types yang di-handle:
  - dashboard_update    → Data sensor baru dari ESP32 (broadcast)
  - notification_update → Notifikasi baru atau perubahan status
  - config_update       → Pengaturan grup diubah dari halaman settings
"""

import json
from datetime import date, datetime, timedelta

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async

from django.utils import timezone


class DashboardConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer untuk dashboard monitoring real-time.

    Saat klien terhubung, langsung mengirim snapshot data terkini:
    - Status grup (NYALA / MATI / PENJARANGAN)
    - Data sensor terakhir per channel
    - Notifikasi aktif
    - Ringkasan efisiensi energi hari ini

    Setelah itu, data baru di-push setiap kali ESP32 mengirim POST /api/sensor-data.
    """

    async def connect(self):
        await self.channel_layer.group_add("dashboard", self.channel_name)
        await self.accept()
        # Kirim data terkini saat koneksi pertama
        await self.send_current_state()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard("dashboard", self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """Menerima pesan dari klien (jika diperlukan di masa depan)."""
        pass

    # ────────────────────────────────────────────────────────
    #  Channel Layer Event Handlers
    # ────────────────────────────────────────────────────────

    async def dashboard_update(self, event):
        """
        Handler untuk event 'dashboard_update' dari channel layer.
        Dipanggil saat ada data sensor baru dari ESP32.
        Format pesan sesuai PRD § "WebSocket Message dari Server ke Browser".
        """
        await self.send(text_data=json.dumps(event["data"]))

    async def notification_update(self, event):
        """
        Handler untuk event 'notification_update' dari channel layer.
        Dipanggil saat ada notifikasi baru atau perubahan status.
        """
        await self.send(text_data=json.dumps(event["data"]))

    async def config_update(self, event):
        """
        Handler untuk event 'config_update' dari channel layer.
        Dipanggil saat pengaturan grup diubah dari halaman pengaturan.
        """
        await self.send(text_data=json.dumps(event["data"]))

    # ────────────────────────────────────────────────────────
    #  Initial State: kirim data terkini saat koneksi pertama
    # ────────────────────────────────────────────────────────

    async def send_current_state(self):
        """
        Kirim snapshot status terkini ke klien yang baru terhubung.
        Ini memastikan dashboard langsung menampilkan data tanpa
        harus menunggu POST berikutnya dari ESP32.
        """
        state = await self._get_current_state()
        await self.send(text_data=json.dumps(state))

    @database_sync_to_async
    def _get_current_state(self):
        """
        Kumpulkan snapshot status dari database:
        - GroupConfig → group_status, dimming_active
        - SensorLog terakhir per channel → data sensor
        - NotificationLog aktif → active_alerts
        - Efisiensi energi hari ini
        """
        from app.models import GroupConfig, SensorLog, NotificationLog
        from app.views.view_api import _compute_relay_status

        now_local = timezone.localtime()
        now_time = now_local.time()

        # ── GroupConfig ──
        config = GroupConfig.objects.first()

        if config is None:
            return {
                "type": "sensor_update",
                "timestamp": now_local.strftime("%Y-%m-%dT%H:%M:%S"),
                "group_status": "MATI",
                "channels": [
                    self._empty_channel(1),
                    self._empty_channel(2),
                ],
                "active_alerts": [],
            }

        status = _compute_relay_status(config, now_time)

        # ── Data sensor terakhir per channel ──
        channels_data = []
        for ch_num in (1, 2):
            latest = SensorLog.objects.filter(channel=ch_num).first()
            if latest:
                channels_data.append({
                    "channel": ch_num,
                    "relay_on": status[f"ch{ch_num}_on"],
                    "sensor_ok": True,
                    "voltage": latest.voltage,
                    "current": latest.current,
                    "power": latest.power,
                    "energy": latest.energy,
                    "frequency": latest.frequency,
                    "pf": latest.pf,
                    "updated_at": latest.timestamp.strftime("%Y-%m-%dT%H:%M:%S") if latest.timestamp else None,
                })
            else:
                channels_data.append({
                    "channel": ch_num,
                    "relay_on": status[f"ch{ch_num}_on"],
                    "sensor_ok": False,
                    "voltage": None,
                    "current": None,
                    "power": None,
                    "energy": None,
                    "frequency": None,
                    "pf": None,
                    "updated_at": None,
                })

        # ── Notifikasi aktif ──
        active_alerts = list(
            NotificationLog.objects.filter(status="active").values(
                "id", "channel", "type", "message", "created_at"
            )
        )
        # Konversi datetime ke string untuk JSON serialization
        for alert in active_alerts:
            if alert.get("created_at"):
                alert["created_at"] = alert["created_at"].strftime(
                    "%Y-%m-%dT%H:%M:%S"
                )

        return {
            "type": "sensor_update",
            "timestamp": now_local.strftime("%Y-%m-%dT%H:%M:%S"),
            "group_status": status["group_status"],
            "channels": channels_data,
            "active_alerts": active_alerts,
        }


    @staticmethod
    def _empty_channel(ch_num):
        """Channel data kosong saat belum ada data sensor."""
        return {
            "channel": ch_num,
            "relay_on": False,
            "sensor_ok": False,
            "voltage": None,
            "current": None,
            "power": None,
            "energy": None,
            "frequency": None,
            "pf": None,
            "updated_at": None,
        }
