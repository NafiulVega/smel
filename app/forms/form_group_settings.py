from django import forms
from app.models import GroupConfig


def _in_range(t, start, end):
    """
    Cek apakah waktu `t` berada dalam rentang [start, end).
    Mendukung crossing tengah malam (misal 17:30 – 05:00).
    """
    if start > end:          # crossing midnight
        return t >= start or t < end
    return start <= t < end


class GroupSettingsForm(forms.ModelForm):
    """
    Form pengaturan per group: jadwal nyala-mati, penjarangan, ambang batas.

    Validasi penjarangan (sesuai PRD):
      - Jam mulai & selesai WAJIB berada dalam rentang jam nyala.
      - Jam mulai != jam selesai.
      - Validasi hanya aktif jika penjarangan_aktif = True.
    """

    jam_nyala = forms.TimeField(
        widget=forms.TimeInput(
            attrs={'type': 'time', 'class': 'form-control'},
            format='%H:%M',
        ),
        input_formats=['%H:%M'],
        label='Jam Nyala',
    )
    jam_mati = forms.TimeField(
        widget=forms.TimeInput(
            attrs={'type': 'time', 'class': 'form-control'},
            format='%H:%M',
        ),
        input_formats=['%H:%M'],
        label='Jam Mati',
    )
    jam_mulai_penjarangan = forms.TimeField(
        widget=forms.TimeInput(
            attrs={'type': 'time', 'class': 'form-control'},
            format='%H:%M',
        ),
        input_formats=['%H:%M'],
        label='Jam Mulai Penjarangan',
        required=False,
    )
    jam_selesai_penjarangan = forms.TimeField(
        widget=forms.TimeInput(
            attrs={'type': 'time', 'class': 'form-control'},
            format='%H:%M',
        ),
        input_formats=['%H:%M'],
        label='Jam Selesai Penjarangan',
        required=False,
    )

    class Meta:
        # Form ini saat ini tidak digunakan secara langsung —
        # pengaturan ditangani manual di view_settings.py.
        # Dipertahankan sebagai referensi / potensi penggunaan di masa depan.
        model  = GroupConfig
        fields = [
            'is_active',
            'on_time', 'off_time',
            'dimming_enabled',
            'dimming_start', 'dimming_end',
            'ch1_current_min', 'ch2_current_min',
            'data_send_interval',
        ]

    def clean(self):
        cleaned = super().clean()
        penjarangan_aktif       = cleaned.get('penjarangan_aktif', False)
        jam_nyala               = cleaned.get('jam_nyala')
        jam_mati                = cleaned.get('jam_mati')
        jam_mulai_penjarangan   = cleaned.get('jam_mulai_penjarangan')
        jam_selesai_penjarangan = cleaned.get('jam_selesai_penjarangan')

        # Jam nyala tidak boleh sama dengan jam mati
        if jam_nyala and jam_mati and jam_nyala == jam_mati:
            raise forms.ValidationError("Jam nyala dan jam mati tidak boleh sama.")

        if penjarangan_aktif:
            # Wajib diisi jika penjarangan aktif
            if not jam_mulai_penjarangan:
                self.add_error('jam_mulai_penjarangan',
                               "Wajib diisi jika penjarangan aktif.")
            if not jam_selesai_penjarangan:
                self.add_error('jam_selesai_penjarangan',
                               "Wajib diisi jika penjarangan aktif.")

            if jam_nyala and jam_mati and jam_mulai_penjarangan and jam_selesai_penjarangan:
                fmt = '%H:%M'
                nyala_str = f"{jam_nyala.strftime(fmt)} – {jam_mati.strftime(fmt)}"

                if not _in_range(jam_mulai_penjarangan, jam_nyala, jam_mati):
                    self.add_error(
                        'jam_mulai_penjarangan',
                        f"Jam mulai penjarangan ({jam_mulai_penjarangan.strftime(fmt)}) "
                        f"harus berada dalam rentang jam nyala ({nyala_str})."
                    )
                if not _in_range(jam_selesai_penjarangan, jam_nyala, jam_mati):
                    self.add_error(
                        'jam_selesai_penjarangan',
                        f"Jam selesai penjarangan ({jam_selesai_penjarangan.strftime(fmt)}) "
                        f"harus berada dalam rentang jam nyala ({nyala_str})."
                    )
                if jam_mulai_penjarangan == jam_selesai_penjarangan:
                    raise forms.ValidationError(
                        "Jam mulai dan jam selesai penjarangan tidak boleh sama."
                    )

        return cleaned
