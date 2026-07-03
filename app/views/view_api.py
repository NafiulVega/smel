"""
REST API endpoints untuk komunikasi ESP32 ↔ Django.

Endpoint:
  GET  /api/relay-status  → Status relay berdasarkan jadwal & logika penjarangan
  POST /api/sensor-data   → Terima data sensor, simpan log, cek ambang batas
"""

import json
from datetime import datetime, time, timedelta

from django.http import JsonResponse
from django.utils import timezone
from django.core.cache import cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from app.models import GroupConfig, SensorLog, NotificationLog


# ============================================================
#  Helper: Logika waktu dengan crossing midnight
# ============================================================

def _is_time_in_range(current: time, start: time, end: time) -> bool:
    """
    Cek apakah `current` berada dalam rentang [start, end).
    Mendukung crossing midnight, contoh: 17:30 → 05:00.

    Kasus normal  (start < end):   start <= current < end
    Kasus crossing (start > end):  current >= start OR current < end
    Kasus start == end:            selalu True (24 jam)
    """
    if start < end:
        # Rentang normal, misal 08:00 → 17:00
        return start <= current < end
    elif start > end:
        # Crossing midnight, misal 17:30 → 05:00
        # Berarti nyala dari 17:30 sampai 23:59:59 ATAU dari 00:00 sampai 04:59:59
        return current >= start or current < end
    else:
        # start == end → selalu dalam rentang (24 jam penuh)
        return True


def _get_night_range(config: GroupConfig, target_date):
    """
    Hitung datetime range untuk "malam" berdasarkan target_date.
    Jadwal crossing midnight: on_time (kemarin) → off_time (target_date).
    Contoh: on=17:30, off=05:00 → target_date=hari ini, mulai dari kemarin sore sampai hari ini pagi.
    """
    tz = timezone.get_current_timezone()
    if config.on_time > config.off_time:
        start = timezone.make_aware(
            datetime.combine(target_date - timedelta(days=1), config.on_time), tz
        )
        end = timezone.make_aware(
            datetime.combine(target_date, config.off_time), tz
        )
    else:
        start = timezone.make_aware(
            datetime.combine(target_date, config.on_time), tz
        )
        end = timezone.make_aware(
            datetime.combine(target_date, config.off_time), tz
        )
    return start, end


def _compute_relay_status(config: GroupConfig, now_time: time) -> dict:
    """
    Hitung status relay Channel 1 & Channel 2 berdasarkan:
    1. Apakah grup aktif
    2. Apakah sekarang dalam jam nyala (on_time → off_time)
    3. Apakah penjarangan aktif dan sekarang dalam jam penjarangan

    Prioritas logika (dari PRD):
    | Prioritas | Kondisi                                                     | Ch1 | Ch2 |
    |-----------|-------------------------------------------------------------|-----|-----|
    | 1         | Grup tidak aktif ATAU di luar jam nyala                      | OFF | OFF |
    | 2         | Dalam jam nyala + penjarangan AKTIF + dalam jam penjarangan  | ON  | OFF |
    | 3         | Dalam jam nyala + penjarangan OFF atau di luar jam dimming   | ON  | ON  |

    Returns dict dengan keys: ch1_on, ch2_on, group_status
    """
    # Grup tidak aktif → semua OFF
    if not config.is_active:
        return {"ch1_on": False, "ch2_on": False, "group_status": "MATI"}

    # Cek apakah sekarang dalam jam nyala
    in_operating_hours = _is_time_in_range(now_time, config.on_time, config.off_time)

    if not in_operating_hours:
        # Di luar jam nyala → semua OFF
        return {"ch1_on": False, "ch2_on": False, "group_status": "MATI"}

    # Dalam jam nyala — Channel 1 selalu ON
    # Channel 2 tergantung penjarangan
    if config.dimming_enabled:
        in_dimming_hours = _is_time_in_range(
            now_time, config.dimming_start, config.dimming_end
        )
        if in_dimming_hours:
            # Penjarangan aktif dan dalam jam penjarangan → Ch2 OFF
            return {"ch1_on": True, "ch2_on": False, "group_status": "PENJARANGAN"}

    # Penjarangan nonaktif atau di luar jam penjarangan → semua ON
    return {"ch1_on": True, "ch2_on": True, "group_status": "NYALA"}


# ============================================================
#  GET /api/relay-status
# ============================================================

@require_GET
def relay_status(request):
    """
    Endpoint yang dipanggil ESP32 untuk mengetahui status relay.
    Dipanggil setiap ~10 siklus (~30-50 detik).

    Response JSON:
    {
        "timestamp": "2024-01-15T18:30:00",
        "channels": [
            {"channel": 1, "address": "0x10", "uart": "UART2", "pin": 13, "relay_on": true},
            {"channel": 2, "address": "0x10", "uart": "UART1", "pin": 12, "relay_on": false}
        ]
    }
    """
    # Ambil konfigurasi grup pertama (prototipe: 1 grup saja)
    config = GroupConfig.objects.first()

    if config is None:
        # Belum ada konfigurasi → semua relay OFF (aman)
        return JsonResponse({
            "timestamp": timezone.localtime().strftime("%Y-%m-%dT%H:%M:%S"),
            "channels": [
                {"channel": 1, "address": "0x10", "uart": "UART2", "pin": 13, "relay_on": False},
                {"channel": 2, "address": "0x10", "uart": "UART1", "pin": 12, "relay_on": False},
            ],
            "interval_sec": 5,
        })

    now_local = timezone.localtime()
    now_time = now_local.time()
    status = _compute_relay_status(config, now_time)

    return JsonResponse({
        "timestamp": now_local.strftime("%Y-%m-%dT%H:%M:%S"),
        "channels": [
            {
                "channel": 1,
                "address": "0x10",
                "uart": "UART2",
                "pin": 13,
                "relay_on": status["ch1_on"],
            },
            {
                "channel": 2,
                "address": "0x10",
                "uart": "UART1",
                "pin": 12,
                "relay_on": status["ch2_on"],
            },
        ],
        "interval_sec": config.data_send_interval,
    })


# ============================================================
#  POST /api/sensor-data
# ============================================================

def _check_thresholds_and_notify(channel: int, reading: dict, config: GroupConfig):
    """
    Cek ambang batas sensor dan buat/update NotificationLog.

    Kondisi pemicu notifikasi:
      N1 — Current < ambang batas (relay ON, sensor OK)
      N2 — Sensor gagal baca      (relay ON, sensor_ok=false)

    Jika kondisi kembali normal → auto-resolve notifikasi aktif.
    """
    relay_on = reading.get("relay_on", False)
    sensor_ok = reading.get("sensor_ok", False)
    now = timezone.now()

    # Ambang batas sesuai channel
    if channel == 1:
        current_min = config.ch1_current_min
    else:
        current_min = config.ch2_current_min

    alerts = []

    # Lacak jeda pengiriman data untuk mendeteksi ESP32 restart atau saat semua relay OFF
    cache_key_last_update = f"last_update_time_{channel}"
    last_update_time = cache.get(cache_key_last_update)
    
    # Jika jeda melebihi interval pengiriman ditambah toleransi 10 detik, anggap status sebelumnya OFF agar tidak memicu false alarm
    max_gap_seconds = config.data_send_interval + 10
    if last_update_time and (now - last_update_time).total_seconds() > max_gap_seconds:
        cache.set(f"last_relay_state_{channel}", False, 86400)
        
    cache.set(cache_key_last_update, now, 86400)

    if not relay_on:
        # Relay OFF → tidak perlu cek apapun, dan auto-resolve semua notifikasi aktif
        cache.set(f"last_relay_state_{channel}", False, 86400)
        _auto_resolve_all(channel, now)
        cache.delete(f"sensor_fail_start_{channel}")
        return alerts

    # --- N2: Sensor gagal baca (relay ON tapi sensor_ok = false) ---
    if not sensor_ok:
        # Grace period: gunakan cache untuk melacak berapa lama sensor gagal
        cache_key = f"sensor_fail_start_{channel}"
        fail_start = cache.get(cache_key)
        
        if not fail_start:
            cache.set(cache_key, now, 86400)  # Simpan waktu pertama kali gagal
            fail_start = now

        last_relay_state = cache.get(f"last_relay_state_{channel}")
        is_sudden_break = (last_relay_state is True)

        if is_sudden_break or (now - fail_start).total_seconds() >= 15:
            # Sudah gagal lebih dari 15 detik ATAU putus mendadak → buat N2
            alert = _create_or_keep_notification(
                channel=channel,
                notif_type="N2",
                message=f"🔴 Channel {channel}: Sensor PZEM tidak merespons. Cek koneksi kabel.",
                now=now,
            )
            if alert:
                alerts.append(alert)
                
        return alerts  # Tidak bisa cek N1 tanpa data sensor

    # Sensor OK → hapus status gagal di cache, cek N1, dan auto-resolve N2 jika sebelumnya ada
    cache.set(f"last_relay_state_{channel}", True, 86400)
    cache.delete(f"sensor_fail_start_{channel}")
    _auto_resolve(channel, "N2", now)

    current_val = reading.get("current")


    # --- N1: Arus terlalu rendah ---
    if current_val is not None and current_val < current_min:
        alert = _create_or_keep_notification(
            channel=channel,
            notif_type="N1",
            message=(
                f"⚠️ Channel {channel}: Arus terlalu rendah ({current_val:.3f} A). "
                f"Kemungkinan ada lampu mati atau kabel putus."
            ),
            now=now,
        )
        if alert:
            alerts.append(alert)
    else:
        _auto_resolve(channel, "N1", now)



    return alerts


def _create_or_keep_notification(channel, notif_type, message, now):
    """
    Buat notifikasi baru jika belum ada yang aktif untuk channel+type ini.
    Jika sudah ada notifikasi aktif → biarkan (tidak duplikat).
    Returns dict alert info jika notifikasi baru dibuat, else None.
    """
    existing = NotificationLog.objects.filter(
        channel=channel,
        type=notif_type,
        status="active",
    ).exists()

    if existing:
        return None  # Sudah ada notifikasi aktif, tidak buat duplikat

    notif = NotificationLog.objects.create(
        channel=channel,
        type=notif_type,
        message=message,
        status="active",
    )
    return {
        "id": notif.id,
        "channel": channel,
        "type": notif_type,
        "message": message,
    }


def _auto_resolve(channel, notif_type, now):
    """Auto-resolve notifikasi aktif untuk channel+type tertentu."""
    NotificationLog.objects.filter(
        channel=channel,
        type=notif_type,
        status="active",
    ).update(
        status="resolved",
        resolved_at=now,
    )


def _auto_resolve_all(channel, now):
    """Auto-resolve semua notifikasi aktif untuk channel tertentu."""
    NotificationLog.objects.filter(
        channel=channel,
        status="active",
    ).update(
        status="resolved",
        resolved_at=now,
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def sensor_data(request):
    """
    Endpoint menerima data sensor dari ESP32 (POST) atau mengambil riwayat data (GET).
    Dipanggil setiap siklus (~3-5 detik).

    Request JSON:
    {
        "timestamp": "2024-01-15T18:30:05",
        "readings": [
            {
                "channel": 1, "address": "0x10", "uart": "UART2",
                "relay_on": true, "sensor_ok": true,
                "voltage": 220.5, "current": 2.34, "power": 515.7,
                "energy": 1.234, "frequency": 50.0, "pf": 0.98
            },
            ...
        ]
    }

    Response JSON:
    {
        "received": true,
        "saved_channels": [1],
        "skipped_channels": [2],
        "alerts": [...]
    }
    """
    if request.method == "GET":
        recent_str = request.GET.get("recent")
        if recent_str:
            try:
                limit = int(recent_str)
            except ValueError:
                limit = 30
            # Ambil {limit} timestamp terakhir (x2 karena ada 2 channel)
            logs = list(SensorLog.objects.order_by("-timestamp")[:limit * 2])
            logs.reverse() # Urutkan kembali dari yang terlama ke terbaru
        else:
            date_str = request.GET.get("date")
            try:
                target_date = (
                    datetime.strptime(date_str, "%Y-%m-%d").date()
                    if date_str else timezone.localtime().date()
                )
            except ValueError:
                return JsonResponse({"error": "Format tanggal harus YYYY-MM-DD"}, status=400)
                
            config = GroupConfig.objects.first()
            if not config:
                return JsonResponse({"error": "Belum ada konfigurasi grup"}, status=404)
                
            night_start, night_end = _get_night_range(config, target_date)
            
            logs = SensorLog.objects.filter(
                timestamp__gte=night_start, timestamp__lte=night_end
            ).order_by("timestamp")
        
        # Return format expected by the prompt
        # {"timestamp": "2024-01-15 17:30:12", "voltage": 220.5, "current": 1.2}
        result = []
        for log in logs:
            local_ts = timezone.localtime(log.timestamp)
            result.append({
                "timestamp": local_ts.strftime("%Y-%m-%d %H:%M:%S"),
                "voltage": float(log.voltage) if log.voltage else 0.0,
                "current": float(log.current) if log.current else 0.0,
                "power": float(log.power) if log.power else 0.0,
                "channel": log.channel
            })
            
        return JsonResponse(result, safe=False)

    # Parse JSON body (POST)
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse(
            {"received": False, "error": "Invalid JSON"},
            status=400,
        )

    readings = body.get("readings", [])
    esp_timestamp_str = body.get("timestamp")

    if isinstance(readings, str):
        if readings.strip() == "[]":
            readings = []
        else:
            try:
                readings = json.loads(readings)
            except json.JSONDecodeError:
                readings = []

    # Tampilkan delay jaringan jika ESP32 mengirimkannya (untuk dicetak di terminal)
    delay_ms = body.get("delay_ms")
    if delay_ms is not None:
        print(f"[INFO] Delay pengiriman data dari ESP32: {delay_ms} ms")

    if not readings:
        pass # Akan diproses di bawah untuk meng-handle status OFF

    # Parse timestamp dari ESP32 (format: "2024-01-15T18:30:05")
    # Jika gagal parse, gunakan waktu server
    try:
        esp_timestamp = datetime.strptime(esp_timestamp_str, "%Y-%m-%dT%H:%M:%S")
        esp_timestamp = timezone.make_aware(
            esp_timestamp, timezone.get_current_timezone()
        )
    except (ValueError, TypeError):
        esp_timestamp = timezone.now()

    # Ambil konfigurasi grup untuk cek ambang batas
    config = GroupConfig.objects.first()

    saved_channels = []
    skipped_channels = []
    all_alerts = []

    # Jika readings kosong, artinya semua relay OFF
    if not readings:
        for ch in [1, 2]:
            cache.set(f"last_relay_state_{ch}", False, 86400)
            _auto_resolve_all(ch, esp_timestamp)
            cache.delete(f"sensor_fail_start_{ch}")

    for reading in readings:
        ch = reading.get("channel")
        relay_on = reading.get("relay_on", False)
        sensor_ok = reading.get("sensor_ok", False)

        if ch not in (1, 2):
            continue

        # Simpan data hanya jika relay ON dan sensor OK
        if relay_on and sensor_ok:
            SensorLog.objects.create(
                channel=ch,
                timestamp=esp_timestamp,
                voltage=reading.get("voltage", 0),
                current=reading.get("current", 0),
                power=reading.get("power", 0),
                energy=reading.get("energy", 0),
                frequency=reading.get("frequency", 0),
                pf=reading.get("pf", 0),
            )
            saved_channels.append(ch)
        else:
            skipped_channels.append(ch)

        # Cek ambang batas dan buat notifikasi jika perlu
        if config:
            alerts = _check_thresholds_and_notify(ch, reading, config)
            all_alerts.extend(alerts)

    # Broadcast ke WebSocket dashboard
    _broadcast_sensor_update(body, config, all_alerts)

    # Broadcast notifikasi baru ke WebSocket (jika ada)
    if all_alerts:
        _broadcast_notification_update(all_alerts)

    return JsonResponse({
        "received": True,
        "saved_channels": saved_channels,
        "skipped_channels": skipped_channels,
        "alerts": all_alerts,
    })


# ============================================================
#  GET /api/efficiency-summary
# ============================================================

@require_GET
def efficiency_summary(request):
    """
    GET /api/efficiency-summary
    Response:
    {
      "on_time": "17:30",
      "off_time": "05:00",
      "dim_start": "01:00",
      "dim_end": "05:00"
    }
    """
    config = GroupConfig.objects.first()
    if not config:
        return JsonResponse({"error": "Belum ada konfigurasi grup"}, status=404)
        
    return JsonResponse({
        "on_time": config.on_time.strftime("%H:%M"),
        "off_time": config.off_time.strftime("%H:%M"),
        "dim_start": config.dimming_start.strftime("%H:%M") if config.dimming_enabled else config.on_time.strftime("%H:%M"),
        "dim_end": config.off_time.strftime("%H:%M")
    })

# ============================================================
#  WebSocket Broadcast Helpers
# ============================================================

# Kunci yang dikirim ke dashboard per channel (tanpa address/uart/pin)
_WS_CHANNEL_KEYS = (
    "channel", "relay_on", "sensor_ok",
    "voltage", "current", "power", "energy", "frequency", "pf",
)


def _build_ws_channel(reading: dict) -> dict:
    """
    Bersihkan data reading dari ESP32 menjadi format PRD
    (hanya field yang relevan untuk dashboard, tanpa address/uart/pin).
    """
    return {k: reading.get(k) for k in _WS_CHANNEL_KEYS}


def _broadcast_sensor_update(sensor_payload, config, alerts):
    """
    Broadcast data sensor terbaru ke semua klien dashboard via WebSocket.

    Format pesan sesuai PRD § "WebSocket Message dari Server ke Browser":
    {
        "type": "sensor_update",
        "timestamp": "...",
        "group_status": "NYALA" / "MATI" / "PENJARANGAN",
        "channels": [{channel, relay_on, sensor_ok, V, A, W, kWh, Hz, PF}, ...],
        "active_alerts": [...]
    }
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    now_local = timezone.localtime()

    # Tentukan group_status
    if config:
        status = _compute_relay_status(config, now_local.time())
        group_status = status["group_status"]
    else:
        group_status = "MATI"

    # Bersihkan channel data sesuai format PRD (tanpa address/uart/pin)
    readings = sensor_payload.get("readings", [])
    channels_clean = []
    for r in readings:
        ch_clean = _build_ws_channel(r)
        ch_clean["updated_at"] = sensor_payload.get("timestamp")
        channels_clean.append(ch_clean)

    # Kumpulkan semua notifikasi aktif (bukan hanya yang baru dibuat)
    active_alerts = list(
        NotificationLog.objects.filter(status="active").values(
            "id", "channel", "type", "message", "created_at"
        )
    )
    for alert in active_alerts:
        if alert.get("created_at"):
            alert["created_at"] = alert["created_at"].strftime("%Y-%m-%dT%H:%M:%S")

    ws_data = {
        "type": "sensor_update",
        "timestamp": sensor_payload.get("timestamp"),
        "group_status": group_status,
        "channels": channels_clean,
        "active_alerts": active_alerts,
    }

    async_to_sync(channel_layer.group_send)(
        "dashboard",
        {
            "type": "dashboard_update",
            "data": ws_data,
        }
    )


def _broadcast_notification_update(alerts):
    """
    Broadcast notifikasi baru ke semua klien dashboard via WebSocket.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    ws_data = {
        "type": "notification_new",
        "alerts": alerts,
    }

    async_to_sync(channel_layer.group_send)(
        "dashboard",
        {
            "type": "notification_update",
            "data": ws_data,
        }
    )

# ============================================================
#  GET /api/efficiency-data-7days
# ============================================================

@require_GET
def efficiency_data_7days(request):
    """
    Mengambil data SensorLog dari 7 hari terakhir, lalu mengelompokkan
    berdasarkan Jam:Menit (HH:MM) untuk menghitung rata-rata tegangan dan arus.
    """
    from collections import defaultdict

    config = GroupConfig.objects.first()
    if not config:
        return JsonResponse({"error": "Belum ada konfigurasi grup"}, status=404)

    seven_days_ago = timezone.now() - timedelta(days=7)
    
    # Ambil data 7 hari terakhir. Karena bisa cukup banyak (ratusan ribu), kita batasi kolomnya.
    # Kita hanya mengambil timestamp, voltage, dan current.
    logs = SensorLog.objects.filter(
        timestamp__gte=seven_days_ago
    ).values('timestamp', 'voltage', 'current')

    grouped = defaultdict(lambda: {"vSum": 0.0, "iSum": 0.0, "count": 0})

    # Proses pengelompokan (aggregasi) di Python / sisi server
    for log in logs:
        # Konversi ke waktu lokal agar sesuai dengan "HH:MM" di zona waktu pengguna
        local_dt = timezone.localtime(log['timestamp'])
        hhmm = local_dt.strftime("%H:%M")
        
        grouped[hhmm]["vSum"] += float(log['voltage'] or 0)
        grouped[hhmm]["iSum"] += float(log['current'] or 0)
        grouped[hhmm]["count"] += 1

    # Format hasil ke struktur data yang diharapkan frontend
    # {"17:30": {"vSum": ..., "iSum": ..., "count": ...}, ...}
    result = dict(grouped)
    return JsonResponse(result)
