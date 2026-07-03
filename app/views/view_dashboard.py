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
    Menyediakan data awal (server-side) yang kemudian
    di-update real-time via WebSocket.
    """
    config = GroupConfig.objects.first()
    now_local = timezone.localtime()

    context = {
        "config": config,
        "server_time": now_local.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    if config:
        status = _compute_relay_status(config, now_local.time())
        context["group_status"] = status["group_status"]
        context["on_time"] = config.on_time.strftime("%H:%M")
        context["off_time"] = config.off_time.strftime("%H:%M")
        context["dimming_enabled"] = config.dimming_enabled
        context["dimming_start"] = config.dimming_start.strftime("%H:%M")
        context["dimming_end"] = config.dimming_end.strftime("%H:%M")
        context["data_send_interval"] = config.data_send_interval
    else:
        context["group_status"] = "MATI"
        context["data_send_interval"] = 5

    return render(request, "monitoring/dashboard.html", context)
