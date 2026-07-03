from django.urls import path
from app.views import view_logs

urlpatterns = [
    path('logs/sensor/', view_logs.sensor_logs_view, name='sensor-logs'),
    path('logs/sensor/import-csv/', view_logs.import_sensor_csv, name='import-sensor-csv'),
    path('logs/notifications/', view_logs.notification_logs_view, name='notification-logs'),
    path('logs/notifications/dismiss/<int:notif_id>/', view_logs.dismiss_notification, name='dismiss-notification'),
    path('logs/notifications/dismiss-all/', view_logs.dismiss_all_notifications, name='dismiss-all-notifications'),
]
