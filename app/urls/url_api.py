from django.urls import path
from app.views import view_api as api

urlpatterns = [
    path('api/relay-status', api.relay_status, name='api-relay-status'),
    path('api/sensor-data',  api.sensor_data,  name='api-sensor-data'),
    path('api/efficiency-summary', api.efficiency_summary, name='api-efficiency-summary'),
    path('api/efficiency-data-7days', api.efficiency_data_7days, name='api-efficiency-data-7days'),
]
