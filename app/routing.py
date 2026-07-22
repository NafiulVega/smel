from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # URL baru: ws/dashboard/<group_id>/ — setiap grup punya channel broadcast sendiri
    re_path(r"ws/dashboard/(?P<group_id>\d+)/$", consumers.DashboardConsumer.as_asgi()),
    # Fallback: ws/dashboard/ — kompatibilitas mundur (group_id=None, pakai grup pertama)
    re_path(r"ws/dashboard/$", consumers.DashboardConsumer.as_asgi()),
]
