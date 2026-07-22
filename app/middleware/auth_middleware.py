from django.utils.deprecation import MiddlewareMixin
from django.shortcuts import redirect

# URL yang boleh diakses tanpa login (dipanggil ESP32, tidak punya session)
EXEMPT_URLS = [
    '/api/relay-status',
    '/api/sensor-data',
    '/api/efficiency-summary',
    # Catatan: /api/efficiency-data TIDAK di-exempt karena hanya dipanggil
    # dari browser dashboard (user sudah login).
]


class LoginRequiredMiddleware(MiddlewareMixin):
    """
    Middleware yang mewajibkan login untuk semua halaman kecuali:
    - Halaman login/logout bawaan Django
    - Endpoint API (/api/*) yang dipanggil oleh ESP32
    """

    def process_request(self, request):
        # Izinkan akses tanpa login ke API endpoints (ESP32 tidak punya session)
        for url in EXEMPT_URLS:
            if request.path.startswith(url):
                return None

        # Izinkan halaman login itu sendiri
        if request.path in ('/login/', '/logout/'):
            return None

        # Jika user belum login, arahkan ke halaman login
        if not request.user.is_authenticated:
            return redirect(f'/login/?next={request.path}')

        return None
