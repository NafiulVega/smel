"""
View untuk halaman dashboard monitoring real-time.
"""

from django.shortcuts import render
from django.utils import timezone

from app.models import GroupConfig, NotificationLog
from app.views.view_api import _compute_relay_status


def dashboard(request):
    """
    Render halaman dashboard monitoring.
    Mendukung multi-grup via tab navigasi (seperti halaman Pengaturan).
    Group dipilih melalui query parameter ?group_id=X.
    Data awal (server-side) kemudian di-update real-time via WebSocket.
    """
    configs = list(GroupConfig.objects.all().order_by('id'))
    if not configs:
        # Auto-create default config jika belum ada
        from datetime import time as dt_time
        default_config = GroupConfig.objects.create(
            name="Jalan Nasional",
            is_active=True,
            on_time=dt_time(17, 30),
            off_time=dt_time(5, 0),
        )
        configs = [default_config]

    # Tentukan grup aktif berdasarkan query parameter
    group_id = request.GET.get("group_id")
    active_config = None
    if group_id:
        for c in configs:
            if str(c.id) == str(group_id):
                active_config = c
                break
    if not active_config:
        active_config = configs[0]

    now_local = timezone.localtime()

    context = {
        "configs": configs,
        "active_config": active_config,
        "config": active_config,  # backward compatibility
        "server_time": now_local.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    status = _compute_relay_status(active_config, now_local.time())
    context["group_status"] = status["group_status"]
    context["on_time"] = active_config.on_time.strftime("%H:%M")
    context["off_time"] = active_config.off_time.strftime("%H:%M")
    context["dimming_enabled"] = active_config.dimming_enabled
    context["dimming_start"] = active_config.dimming_start.strftime("%H:%M")
    context["dimming_end"] = active_config.dimming_end.strftime("%H:%M")
    context["data_send_interval"] = active_config.data_send_interval

    return render(request, "monitoring/dashboard.html", context)
