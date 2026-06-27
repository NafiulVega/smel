from django import forms
from app.models import Group


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
        model  = Group
        fields = [
            'is_active',
            'jam_nyala', 'jam_mati',
            'penjarangan_aktif',
            'jam_mulai_penjarangan', 'jam_selesai_penjarangan',
            'arus_min', 'daya_min',
        ]
        widgets = {
            'is_active':         forms.CheckboxInput(attrs={'class': 'custom-switch-input'}),
            'penjarangan_aktif': forms.CheckboxInput(attrs={'class': 'custom-switch-input'}),
            'arus_min': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.1', 'min': '0'}),
            'daya_min': forms.NumberInput(attrs={'class': 'form-control', 'step': '1',   'min': '0'}),
        }
        labels = {
            'is_active':         'Group Aktif',
            'penjarangan_aktif': 'Aktifkan Penjarangan',
            'arus_min':          'Arus Minimum (A)',
            'daya_min':          'Daya Minimum (W)',
        }

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
