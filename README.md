# Sistem Monitoring Lampu Jalan Berbasis IoT (SMEL)

Sistem Monitoring Lampu Jalan Berbasis IoT adalah sebuah platform berbasis web yang digunakan untuk memantau dan mengontrol lampu jalan secara terpusat. Sistem ini terhubung dengan perangkat **ESP32** dan sensor **PZEM-004T** melalui REST API dan menggunakan protokol **WebSocket** (via Django Channels) untuk menyajikan data secara real-time tanpa perlu me-refresh halaman (dashboard mobile-first).

Proyek ini dibuat sebagai prototipe sistem otomatisasi lampu jalan yang terintegrasi dan dapat mengontrol konsumsi daya dengan mengimplementasikan pengaturan jadwal nyala/mati lampu serta sistem penjarangan untuk meningkatkan efisiensi energi.

---

## 🚀 Fitur Utama

- **Monitoring Real-Time (WebSocket):** Menampilkan data tegangan (V), arus (A), daya (W), energi (kWh), frekuensi (Hz), dan power factor (PF) secara langsung di dashboard.
- **Kendali Jadwal (Nyala/Mati):** Pengaturan jadwal lampu secara otomatis (mendukung _crossing_ tengah malam, misal 17:30 - 05:00).
- **Fitur Penjarangan (Half-Night Dimming):** Mematikan sebagian lampu pada jam tertentu (misal: 01:00 - 04:00) untuk menghemat energi tanpa mematikan penerangan jalan sepenuhnya.
- **Logika Cerdas Pemanasan & Putus Mendadak:** Toleransi pemanasan awal sensor PZEM-004T untuk menghindari false-alarm saat relay baru dinyalakan.

---

## 🛠️ Arsitektur Hardware & Pemetaan Pin

Sistem dirancang untuk **1 Grup (Jalan Nasional)** yang memiliki **2 Channel Relay** (total mengontrol 10 lampu, masing-masing channel 5 lampu).

| Channel | Relay Pin | PZEM UART RX | PZEM UART TX | PZEM Address | Keterangan |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | GPIO 13 | GPIO 16 (UART2) | GPIO 17 (UART2) | `0x10` | Pin utama, selalu menyala saat jadwal aktif. |
| **2** | GPIO 12 | GPIO 18 (UART1) | GPIO 19 (UART1) | `0x10` | Pin penjarangan, dimatikan saat jam penjarangan. |

---

## 💻 Tech Stack & Software

- **Backend:** Python, Django 5.x, Django Channels (ASGI)
- **Database:** PostgreSQL (berdasarkan `psycopg2-binary`) / SQLite
- **Real-Time & Message Broker:** Redis, WebSocket
- **Hardware:** ESP32, Relay 2 Channel, PZEM-004T (V3.0)
- **Dependencies:** Pandas, NumPy, ReportLab, OpenPyXL (untuk export laporan)

---

## 📡 API Endpoints (Untuk ESP32)

Server menyediakan REST API lokal untuk ESP32:

### 1. GET `/api/relay-status`
Dipanggil secara periodik oleh ESP32 untuk mengambil status logika relay dari server berdasarkan pengaturan jadwal dan penjarangan.
- **Response Format:**
  ```json
  {
    "timestamp": "2024-01-15T18:30:00",
    "channels": [
      { "channel": 1, "address": "0x10", "uart": "UART2", "pin": 13, "relay_on": true },
      { "channel": 2, "address": "0x10", "uart": "UART1", "pin": 12, "relay_on": false }
    ]
  }
  ```

### 2. POST `/api/sensor-data`
Dipanggil oleh ESP32 setiap siklus pembacaan untuk mengirimkan data sensor ke server. Hanya dikirim jika relay dalam keadaan ON.
- **Request Format:**
  ```json
  {
    "timestamp": "2024-01-15T18:30:05",
    "readings": [
      {
        "channel": 1, "address": "0x10", "uart": "UART2",
        "relay_on": true, "sensor_ok": true,
        "voltage": 220.5, "current": 2.34, "power": 515.7,
        "energy": 1.234, "frequency": 50.0, "pf": 0.98
      }
    ]
  }
  ```
Begitu data di-POST, server akan langsung mem-broadcast data ke dashboard frontend melalui **WebSocket**.

---

## ⚙️ Panduan Instalasi (Local Development)

Ikuti langkah-langkah di bawah ini untuk menjalankan server di komputer lokal. Pastikan **Python 3.x** dan **Redis Server** sudah terinstall dan berjalan di mesin Anda.

### 1. Clone Repository & Setup Virtual Environment
```bash
git clone <repository-url>
cd smel
python -m venv env
```

### 2. Aktifkan Virtual Environment
- **Windows:**
  ```bash
  env\Scripts\activate
  ```
- **Linux/Mac:**
  ```bash
  source env/bin/activate
  ```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Konfigurasi Environment Variables
Buat file `.env` dengan cara menduplikasi file `.env.example` yang sudah disediakan, kemudian sesuaikan isinya:

- **Windows:**
  ```bash
  copy .env.example .env
  ```
- **Linux/Mac:**
  ```bash
  cp .env.example .env
  ```

Lalu buka file `.env` tersebut dan atur konfigurasi database serta `SECRET_KEY` sesuai kebutuhan.

### 5. Migrasi Database
```bash
python manage.py makemigrations
python manage.py migrate
```

### 6. Buat Superuser (Akun Admin)
```bash
python manage.py createsuperuser
```

### 7. Jalankan Server
Karena menggunakan Django Channels, gunakan daphne atau uvicorn untuk mensupport ASGI, atau jalankan runserver biasa yang otomatis memakai ASGI:
```bash
python manage.py runserver 0.0.0.0:8000
```
> _Akses dashboard melalui browser di `http://localhost:8000` atau `http://<IP-Lokal>:8000`._

---

## 📝 Catatan Penting
- **Redis Server:** Pastikan Redis berjalan di latar belakang (default di port `6379`) agar komunikasi WebSocket via Django Channels Layer dapat bekerja dengan baik.
- **Jaringan Lokal:** Pastikan ESP32 terhubung ke router/WiFi yang sama dengan server Django yang sedang berjalan, dan IP di konfigurasi ESP32 mengarah ke IP komputer server.
