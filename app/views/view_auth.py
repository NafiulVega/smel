from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods


@require_http_methods(["GET", "POST"])
def login_view(request):
    """
    Halaman login. Redirect ke dashboard (atau URL ?next=) setelah berhasil.
    Jika sudah login, langsung ke dashboard.
    """
    if request.user.is_authenticated:
        return redirect('dashboard')

    next_url = request.GET.get('next') or request.POST.get('next') or '/dashboard'

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        if not username or not password:
            messages.error(request, 'Username dan password wajib diisi.')
            return render(request, 'auth/login.html', {'next': next_url})

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect(next_url)
        else:
            messages.error(request, 'Username atau password salah.')

    return render(request, 'auth/login.html', {'next': next_url})


def logout_view(request):
    """Logout dan redirect ke halaman login."""
    logout(request)
    messages.success(request, 'Anda berhasil logout.')
    return redirect('login')
