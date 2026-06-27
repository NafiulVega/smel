from django.urls import path
from app.views import view_auth as auth

urlpatterns = [
    path('login/',  auth.login_view,  name='login'),
    path('logout/', auth.logout_view, name='logout'),
]
