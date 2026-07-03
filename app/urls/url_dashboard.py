from django.urls import path
from app.views import view_dashboard as dashboard

urlpatterns = [
    path('dashboard', dashboard.dashboard, name='dashboard'),
]
