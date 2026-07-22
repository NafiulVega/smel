"""
View untuk halaman pengaturan GroupConfig.
"""

from datetime import time as dt_time

from django.shortcuts import render, redirect
from django.urls import reverse
from django.contrib import messages
from django.views.decorators.http import require_http_methods

from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from app.models import GroupConfig
from app.views.view_api import _is_time_in_range


def _parse_time(value):
    """Parse string HH:MM menjadi datetime.time, return None jika gagal."""
    if not value:
        return None
    try:
        parts = value.strip().split(":")
        return dt_time(int(parts[0]), int(parts[1]))
    except (ValueError, IndexError):
        return None


def _parse_float(value, default=0.0):
    """Parse string menjadi float, return default jika gagal."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


@require_http_methods(["GET", "POST"])
def settings_view(request):
    """
    Halaman pengaturan GroupConfig (mendukung multi-grup dengan tab).
    GET  → Tampilkan form dengan data terkini
    POST → Validasi & simpan, broadcast perubahan ke WebSocket
    """
    configs = list(GroupConfig.objects.all().order_by('id'))
    if not configs:
        default_config = GroupConfig.objects.create(
            name="Jalan Nasional",
            is_active=True,
            on_time=dt_time(17, 30),
            off_time=dt_time(5, 0),
        )
        configs = [default_config]

    # Default tab yang aktif
    active_tab = request.GET.get("active_tab")
    if not active_tab and configs:
        active_tab = str(configs[0].id)

    if request.method == "POST":
        group_id = request.POST.get("group_id")
        active_tab = str(group_id)
        
        config = None
        for c in configs:
            if str(c.id) == str(group_id):
                config = c
                break
                
        if not config:
            messages.error(request, "Grup tidak ditemukan.")
            return redirect("settings")

        errors = []

        # ── Parse semua field ──
        name = request.POST.get("name", "").strip() or config.name
        is_active = request.POST.get("is_active") == "on"

        on_time = _parse_time(request.POST.get("on_time"))
        off_time = _parse_time(request.POST.get("off_time"))
        if not on_time:
            errors.append("Jam nyala tidak valid (format HH:MM).")
        if not off_time:
            errors.append("Jam mati tidak valid (format HH:MM).")
        if on_time and off_time and on_time == off_time:
            errors.append("Jam nyala dan jam mati tidak boleh sama.")

        dimming_enabled = request.POST.get("dimming_enabled") == "on"
        dimming_start = _parse_time(request.POST.get("dimming_start"))
        dimming_end = _parse_time(request.POST.get("dimming_end"))

        if dimming_enabled:
            if not dimming_start:
                errors.append("Jam mulai penjarangan tidak valid.")
            if not dimming_end:
                errors.append("Jam selesai penjarangan tidak valid.")
            if dimming_start and dimming_end and dimming_start == dimming_end:
                errors.append("Jam mulai dan selesai penjarangan tidak boleh sama.")
            # Validasi: jam penjarangan harus dalam rentang jam nyala (inklusif batas akhir)
            if dimming_start and on_time and off_time:
                if not (_is_time_in_range(dimming_start, on_time, off_time) or dimming_start == off_time):
                    errors.append(
                        "Jam mulai penjarangan harus dalam rentang jam nyala "
                        f"({on_time.strftime('%H:%M')} - {off_time.strftime('%H:%M')})."
                    )
            if dimming_end and on_time and off_time:
                if not (_is_time_in_range(dimming_end, on_time, off_time) or dimming_end == off_time):
                    errors.append(
                        "Jam selesai penjarangan harus dalam rentang jam nyala "
                        f"({on_time.strftime('%H:%M')} - {off_time.strftime('%H:%M')})."
                    )

        ch1_current_min = _parse_float(request.POST.get("ch1_current_min"), 0.33)
        ch2_current_min = _parse_float(request.POST.get("ch2_current_min"), 0.33)
        if ch1_current_min < 0 or ch2_current_min < 0:
            errors.append("Ambang batas arus tidak boleh negatif.")

        data_send_interval_str = request.POST.get("data_send_interval", "").strip()
        data_send_interval = int(data_send_interval_str) if data_send_interval_str.isdigit() else 5
        if data_send_interval < 1:
            errors.append("Jeda waktu pengiriman data minimal 1 detik.")

        # ── Jika ada error, kembalikan form ──
        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, "monitoring/settings.html", {"configs": configs, "active_tab": active_tab})

        # ── Simpan ──
        config.name = name
        config.is_active = is_active
        config.on_time = on_time
        config.off_time = off_time
        config.dimming_enabled = dimming_enabled
        config.dimming_start = dimming_start or config.dimming_start
        config.dimming_end = dimming_end or config.dimming_end
        config.ch1_current_min = ch1_current_min
        config.ch2_current_min = ch2_current_min
        config.data_send_interval = data_send_interval
        config.save()

        # ── Broadcast ke WebSocket ──
        _broadcast_config_update(config)

        messages.success(request, f"Pengaturan grup {config.name} berhasil disimpan.")
        
        redirect_url = reverse("settings") + f"?active_tab={config.id}"
        return redirect(redirect_url)

    return render(request, "monitoring/settings.html", {"configs": configs, "active_tab": str(active_tab)})


def _broadcast_config_update(config):
    """Broadcast perubahan konfigurasi ke dashboard grup terkait via WebSocket."""
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    ws_data = {
        "type": "config_update",
        "config": {
            "group_id": config.id,
            "name": config.name,
            "data_send_interval": config.data_send_interval,
            "is_active": config.is_active,
            "on_time": config.on_time.strftime("%H:%M"),
            "off_time": config.off_time.strftime("%H:%M"),
            "dimming_enabled": config.dimming_enabled,
            "dimming_start": config.dimming_start.strftime("%H:%M"),
            "dimming_end": config.dimming_end.strftime("%H:%M"),
        },
    }

    # Broadcast ke group channel spesifik grup yang diubah
    ws_group = f"dashboard_{config.id}"
    async_to_sync(channel_layer.group_send)(
        ws_group,
        {
            "type": "config_update",
            "data": ws_data,
        },
    )
