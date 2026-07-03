"""
Views untuk halaman log sensor dan log notifikasi.
"""

import csv
import io
from datetime import datetime

from dateutil import parser as dateutil_parser

from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse
from django.core.paginator import Paginator
from django.utils import timezone
from django.contrib import messages
from django.views.decorators.http import require_http_methods, require_POST

from app.models import SensorLog, NotificationLog


# ============================================================
#  /logs/sensor/ — Tabel Historis SensorLog
# ============================================================

@require_http_methods(["GET"])
def sensor_logs_view(request):
    """
    Halaman log sensor dengan filter channel, tanggal, dan ekspor CSV.
    Pagination 50 baris per halaman.
    """
    qs = SensorLog.objects.all()

    # ── Filter channel ──
    channel = request.GET.get("channel", "")
    if channel in ("1", "2"):
        qs = qs.filter(channel=int(channel))

    # ── Filter tanggal ──
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    if date_from:
        try:
            dt_from = timezone.make_aware(
                datetime.strptime(date_from, "%Y-%m-%d"),
                timezone.get_current_timezone(),
            )
            qs = qs.filter(timestamp__gte=dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = timezone.make_aware(
                datetime.strptime(date_to + " 23:59:59", "%Y-%m-%d %H:%M:%S"),
                timezone.get_current_timezone(),
            )
            qs = qs.filter(timestamp__lte=dt_to)
        except ValueError:
            pass

    # ── Ekspor CSV ──
    if request.GET.get("export") == "csv":
        return _export_sensor_csv(qs)

    # ── Pagination ──
    paginator = Paginator(qs, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "channel": channel,
        "date_from": date_from,
        "date_to": date_to,
        "total_count": qs.count(),
    }
    return render(request, "monitoring/sensor_logs.html", context)


def _export_sensor_csv(queryset):
    """Ekspor queryset SensorLog ke file CSV."""
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="sensor_log_{timezone.localtime().strftime("%Y%m%d_%H%M%S")}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow([
        "ID", "Channel", "Timestamp", "Date", "Time", "Voltage (V)", "Current (A)",
        "Power (W)", "Energy (kWh)", "Frequency (Hz)", "Power Factor"
    ])

    for log in queryset.iterator():
        writer.writerow([
            log.id,
            log.channel,
            timezone.localtime(log.timestamp).strftime("%Y-%m-%d %H:%M:%S"),
            timezone.localtime(log.timestamp).strftime("%Y-%m-%d"),
            timezone.localtime(log.timestamp).strftime("%H:%M:%S"),
            log.voltage,
            log.current,
            log.power,
            log.energy,
            log.frequency,
            log.pf,
        ])

    return response


@require_POST
def import_sensor_csv(request):
    """
    Import data sensor dari file CSV menggunakan pandas.

    Mendukung kolom 'Timestamp' atau gabungan 'Date' dan 'Time'.
    """
    import pandas as pd

    csv_file = request.FILES.get("csv_file")

    if not csv_file:
        messages.error(request, "Pilih file CSV terlebih dahulu.")
        return redirect("sensor-logs")

    if not csv_file.name.endswith(".csv"):
        messages.error(request, "File harus berformat .csv")
        return redirect("sensor-logs")

    try:
        df = pd.read_csv(csv_file)

        if df.empty:
            messages.info(request, "File CSV kosong.")
            return redirect("sensor-logs")

        # Normalisasi spasi pada nama kolom
        df.columns = df.columns.str.strip()

        # Proses timestamp
        if 'Date' in df.columns and 'Time' in df.columns:
            # Jika ada kolom Date dan Time, gabungkan
            df['Timestamp'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Time'].astype(str))
        elif 'Timestamp' in df.columns:
            # Jika hanya ada Timestamp
            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        else:
            messages.error(request, "CSV harus memiliki kolom 'Timestamp' atau 'Date' dan 'Time'.")
            return redirect("sensor-logs")

        tz = timezone.get_current_timezone()
        
        # Buat timezone aware
        if df['Timestamp'].dt.tz is None:
            df['Timestamp'] = df['Timestamp'].dt.tz_localize(tz)
        else:
            df['Timestamp'] = df['Timestamp'].dt.tz_convert(tz)

        created = 0
        errors = []

        # Pastikan kolom-kolom lain tersedia
        required_cols = ['Channel', 'Voltage (V)', 'Current (A)', 'Power (W)', 'Energy (kWh)', 'Frequency (Hz)', 'Power Factor']
        for col in required_cols:
            if col not in df.columns:
                # Coba cari fallback case-insensitive
                for df_col in df.columns:
                    if col.lower() in df_col.lower():
                        df.rename(columns={df_col: col}, inplace=True)
                        break

        for idx, row in df.iterrows():
            row_num = idx + 2
            try:
                channel = int(row.get('Channel', 1))
                if channel not in (1, 2):
                    errors.append(f"Baris {row_num}: channel harus 1 atau 2")
                    continue

                SensorLog.objects.create(
                    channel=channel,
                    timestamp=row['Timestamp'].to_pydatetime(),
                    voltage=float(row.get('Voltage (V)', 0)),
                    current=float(row.get('Current (A)', 0)),
                    power=float(row.get('Power (W)', 0)),
                    energy=float(row.get('Energy (kWh)', 0)),
                    frequency=float(row.get('Frequency (Hz)', 0)),
                    pf=float(row.get('Power Factor', 0)),
                )
                created += 1

            except Exception as e:
                errors.append(f"Baris {row_num}: {str(e)}")
                continue

        if created > 0:
            messages.success(request, f"{created} data sensor berhasil diimport.")
        if errors:
            error_summary = "; ".join(errors[:5])
            if len(errors) > 5:
                error_summary += f" ... dan {len(errors) - 5} error lainnya"
            messages.warning(request, f"{len(errors)} baris gagal: {error_summary}")
        if created == 0 and not errors:
            messages.info(request, "Tidak ada data untuk diimport.")

    except Exception as e:
        messages.error(request, f"Gagal import: {str(e)}")

    return redirect("sensor-logs")


# ============================================================
#  /logs/notifications/ — Tabel NotificationLog
# ============================================================

@require_http_methods(["GET"])
def notification_logs_view(request):
    """
    Halaman log notifikasi dengan filter tipe, status, dan tombol dismiss.
    Pagination 50 baris per halaman.
    """
    qs = NotificationLog.objects.all()

    # ── Filter tipe ──
    notif_type = request.GET.get("type", "")
    if notif_type in ("N1", "N2", "N3"):
        qs = qs.filter(type=notif_type)

    # ── Filter status ──
    status = request.GET.get("status", "")
    if status in ("active", "resolved", "dismissed"):
        qs = qs.filter(status=status)

    # ── Filter channel ──
    channel = request.GET.get("channel", "")
    if channel in ("1", "2"):
        qs = qs.filter(channel=int(channel))

    # ── Pagination ──
    paginator = Paginator(qs, 50)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "notif_type": notif_type,
        "status_filter": status,
        "channel": channel,
        "total_count": qs.count(),
        "active_count": NotificationLog.objects.filter(status="active").count(),
    }
    return render(request, "monitoring/notification_logs.html", context)


# ============================================================
#  POST /logs/notifications/dismiss/<id>/
# ============================================================

@require_POST
def dismiss_notification(request, notif_id):
    """Dismiss satu notifikasi."""
    notif = get_object_or_404(NotificationLog, pk=notif_id)
    if notif.status == "active":
        notif.status = "dismissed"
        notif.dismissed_at = timezone.now()
        notif.save()
        messages.success(request, f"Notifikasi #{notif.id} berhasil di-dismiss.")
    else:
        messages.warning(request, f"Notifikasi #{notif.id} sudah berstatus {notif.get_status_display()}.")

    # Redirect kembali dengan filter yang sama
    return redirect(request.META.get("HTTP_REFERER", "/logs/notifications/"))


@require_POST
def dismiss_all_notifications(request):
    """Dismiss semua notifikasi aktif."""
    count = NotificationLog.objects.filter(status="active").update(
        status="dismissed",
        dismissed_at=timezone.now(),
    )
    messages.success(request, f"{count} notifikasi berhasil di-dismiss.")
    return redirect(request.META.get("HTTP_REFERER", "/logs/notifications/"))
