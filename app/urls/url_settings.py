from django.urls import path
from app.views import view_settings

urlpatterns = [
    path('settings/', view_settings.settings_view, name='settings'),
]
