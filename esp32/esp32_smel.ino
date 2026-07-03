/*
 * ============================================================
 *  SMEL — Smart Electricity Monitoring
 *  Kode ESP32 Final — Sistem Monitoring Lampu Jalan
 * ============================================================
 *
 *  Hardware:
 *    - ESP32 DevKit V1
 *    - 2× PZEM-004T (Modbus RTU, address 0x10)
 *    - 2× Relay Module (GPIO 13 & GPIO 12)
 *
 *  Komunikasi:
 *    - GET  /api/relay-status  → setiap 10 siklus (~30-40 detik)
 *    - POST /api/sensor-data   → setiap siklus (~3-5 detik)
 *    - HTTP timeout: 2000ms (jaringan lokal)
 *
 *  Library yang dibutuhkan (install via Arduino Library Manager):
 *    - ArduinoJson       (Benoit Blanchon)   >= 6.x
 *    - PZEM-004T-v30     (Jakub Mandula)     >= 1.1
 *
 *  Board Manager: ESP32 by Espressif Systems >= 2.x
 *
 * ============================================================
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <PZEM004Tv30.h>
#include <time.h>

// ============================================================
//  KONFIGURASI — Sesuaikan bagian ini
// ============================================================
const char* WIFI_SSID      = "NAMA_WIFI_ANDA";       // Ganti dengan SSID WiFi
const char* WIFI_PASSWORD  = "PASSWORD_WIFI_ANDA";    // Ganti dengan password WiFi
const char* SERVER_IP      = "192.168.1.100";         // Ganti dengan IP server Django
const int   SERVER_PORT    = 8000;                    // Port server Django
const int   HTTP_TIMEOUT   = 3500;                    // ms — timeout HTTP (server melakukan DB + WebSocket)
const int   MAX_HTTP_RETRIES = 2;                     // Jumlah retry jika HTTP gagal

// Interval siklus dinamis: di-update dari API web dashboard
// Default awal 5 detik, akan di-overwrite oleh JSON dari server
unsigned long CYCLE_INTERVAL_MS = 5000;          // 5 detik per siklus

// Interval GET relay-status: setiap N siklus sensor
// N=1 × 5 detik = GET setiap 5 detik
const int   RELAY_POLL_EVERY_N_CYCLES = 1;

// Warmup: jeda setelah relay berubah OFF → ON sebelum baca sensor
// PZEM butuh waktu stabilisasi setelah beban terhubung
const unsigned long WARMUP_MS = 5000;                  // 5 detik warmup

// NTP — WIB (UTC+7)
const char* NTP_SERVER  = "pool.ntp.org";
const long  GMT_OFFSET  = 25200;   // 7 × 3600 = 25200
const int   DST_OFFSET  = 0;

// ============================================================
//  HARDWARE — Pemetaan Pin dan UART
// ============================================================
// | Channel | Relay Pin | PZEM UART | RX  | TX  | Address |
// |---------|-----------|-----------|-----|-----|---------|
// | 1       | GPIO 13   | UART2     | 16  | 17  | 0x10    |
// | 2       | GPIO 12   | UART1     | 18  | 19  | 0x10    |

#define NUM_CHANNELS 2
const int relayPins[NUM_CHANNELS] = {13, 12};

// Status relay — fallback jika server tidak bisa dihubungi
bool relayState[NUM_CHANNELS] = {false, false};

// Warmup tracking: waktu saat relay berubah OFF → ON
// Selama warmup, sensor tidak dibaca untuk menghindari false alarm
unsigned long relayOnTimestamp[NUM_CHANNELS] = {0, 0};
bool relayWarmingUp[NUM_CHANNELS] = {false, false};

// PZEM Channel 1 — UART2, RX=16, TX=17, Address 0x10
HardwareSerial SerialPZEM1(2);
PZEM004Tv30   pzem1(SerialPZEM1, 16, 17, 0x10);

// PZEM Channel 2 — UART1, RX=18, TX=19, Address 0x10
HardwareSerial SerialPZEM2(1);
PZEM004Tv30   pzem2(SerialPZEM2, 18, 19, 0x10);

// ============================================================
//  STRUKTUR DATA
// ============================================================
struct SensorReading {
    bool  relay_on;
    bool  sensor_ok;
    float voltage, current, power, energy, frequency, pf;
};

// ============================================================
//  UTILITY — Timestamp NTP (WIB)
// ============================================================
String getTimestamp() {
    struct tm t;
    if (!getLocalTime(&t)) return "1970-01-01T00:00:00";
    char buf[20];
    strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%S", &t);
    return String(buf);
}

// ============================================================
//  WIFI — Koneksi dan Reconnect
// ============================================================
void connectWiFi() {
    if (WiFi.status() == WL_CONNECTED) return;
    Serial.printf("Menghubungkan ke WiFi: %s", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    for (int i = 0; i < 20 && WiFi.status() != WL_CONNECTED; i++) {
        delay(500);
        Serial.print(".");
    }
    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("\nWiFi OK: " + WiFi.localIP().toString());
    } else {
        Serial.println("\nWiFi GAGAL — mode offline, relay tetap di state terakhir.");
    }
}

// ============================================================
//  API: GET /api/relay-status
// ============================================================
// Dipanggil setiap N siklus untuk mendapatkan status relay
// terbaru dari server (jadwal nyala/mati + penjarangan).
// Jika gagal → relay tetap di state terakhir (graceful fallback).
// ============================================================
bool fetchRelayStatus() {
    if (WiFi.status() != WL_CONNECTED) return false;

    HTTPClient http;
    String url = "http://" + String(SERVER_IP) + ":" + SERVER_PORT + "/api/relay-status";
    http.setReuse(false);  // Cegah koneksi TCP menggantung

    int code = -1;
    for (int attempt = 0; attempt < MAX_HTTP_RETRIES; attempt++) {
        http.begin(url);
        http.setTimeout(HTTP_TIMEOUT);
        code = http.GET();

        if (code == 200) break;  // Sukses

        Serial.printf("[GET] Gagal HTTP %d (percobaan %d/%d)\n",
                      code, attempt + 1, MAX_HTTP_RETRIES);
        http.end();
        if (attempt < MAX_HTTP_RETRIES - 1) delay(500);
    }

    if (code != 200) {
        Serial.println("[GET] Gagal — relay tetap di state terakhir");
        http.end();
        return false;
    }

    StaticJsonDocument<512> doc;
    DeserializationError err = deserializeJson(doc, http.getString());
    if (err != DeserializationError::Ok) {
        Serial.printf("[GET] JSON parse error: %s\n", err.c_str());
        http.end();
        return false;
    }
    http.end();

    // Update interval siklus dari server jika tersedia
    if (doc.containsKey("interval_sec")) {
        unsigned long newInterval = doc["interval_sec"].as<unsigned long>() * 1000;
        if (newInterval >= 1000 && CYCLE_INTERVAL_MS != newInterval) {
            CYCLE_INTERVAL_MS = newInterval;
            Serial.printf("[GET] Interval update: %lu ms\n", CYCLE_INTERVAL_MS);
        }
    }

    // Update relay sesuai perintah server
    for (JsonObject ch : doc["channels"].as<JsonArray>()) {
        int idx = ch["channel"].as<int>() - 1;  // 0-based index
        if (idx < 0 || idx >= NUM_CHANNELS) continue;

        bool newState = ch["relay_on"].as<bool>();
        if (relayState[idx] != newState) {
            Serial.printf("[RELAY] Ch%d (pin%d): %s -> %s\n",
                          idx + 1, relayPins[idx],
                          relayState[idx] ? "ON" : "OFF",
                          newState ? "ON" : "OFF");

            // Deteksi transisi OFF → ON: mulai warmup
            if (!relayState[idx] && newState) {
                relayWarmingUp[idx] = true;
                relayOnTimestamp[idx] = millis();
                Serial.printf("[WARMUP] Ch%d mulai warmup %lu ms\n",
                              idx + 1, WARMUP_MS);
            }
            // Deteksi transisi ON → OFF: reset warmup
            if (relayState[idx] && !newState) {
                relayWarmingUp[idx] = false;
            }
        }
        relayState[idx] = newState;
        digitalWrite(relayPins[idx], relayState[idx] ? HIGH : LOW);
    }
    return true;
}

// ============================================================
//  BACA SENSOR PZEM-004T
// ============================================================
// Hanya membaca sensor jika relay channel tersebut ON dan
// sudah melewati masa warmup.
// Jika relay OFF → skip, semua nilai false/0.
// Jika masih warmup → skip, relay_on=true tapi sensor_ok=false
//   TIDAK dikirim ke server (skipWarmup=true di loop).
// Jika relay ON tapi sensor gagal baca → sensor_ok = false.
// ============================================================
SensorReading readChannel(PZEM004Tv30 &pzem, bool relayOn, bool inWarmup) {
    SensorReading r = {};  // zero-init semua field
    r.relay_on = relayOn;

    if (!relayOn) return r;  // Relay OFF: tidak baca sensor

    // Masih dalam warmup: jangan baca sensor
    if (inWarmup) {
        r.sensor_ok = false;
        return r;
    }

    float v = pzem.voltage();
    if (isnan(v)) {
        r.sensor_ok = false;  // Gagal baca → server akan buat notifikasi N3
        return r;
    }

    r.sensor_ok  = true;
    r.voltage    = v;
    r.current    = pzem.current();
    r.power      = pzem.power();
    r.energy     = pzem.energy();
    r.frequency  = pzem.frequency();
    r.pf         = pzem.pf();
    return r;
}

// ============================================================
//  API: POST /api/sensor-data
// ============================================================
// Kirim data pembacaan sensor ke server setiap siklus.
// Server akan:
//   1. Simpan ke database (jika relay ON + sensor OK)
//   2. Cek ambang batas → buat notifikasi jika ada pelanggaran
//   3. Broadcast data ke WebSocket dashboard (real-time)
// ============================================================
bool sendSensorData(SensorReading readings[]) {
    if (WiFi.status() != WL_CONNECTED) return false;

    const char* uartLabels[NUM_CHANNELS] = {"UART2", "UART1"};

    StaticJsonDocument<1024> doc;
    doc["timestamp"]   = getTimestamp();
    JsonArray arr      = doc.createNestedArray("readings");

    for (int i = 0; i < NUM_CHANNELS; i++) {
        JsonObject obj  = arr.createNestedObject();
        obj["channel"]  = i + 1;
        obj["address"]  = "0x10";
        obj["uart"]     = uartLabels[i];
        obj["relay_on"] = readings[i].relay_on;
        obj["sensor_ok"]= readings[i].sensor_ok;

        if (readings[i].sensor_ok) {
            // Kirim nilai numerik dengan presisi yang sesuai
            obj["voltage"]   = serialized(String(readings[i].voltage,   1));
            obj["current"]   = serialized(String(readings[i].current,   3));
            obj["power"]     = serialized(String(readings[i].power,     1));
            obj["energy"]    = serialized(String(readings[i].energy,    3));
            obj["frequency"] = serialized(String(readings[i].frequency, 1));
            obj["pf"]        = serialized(String(readings[i].pf,        2));
        } else {
            // Sensor gagal baca atau relay OFF → semua null
            obj["voltage"] = obj["current"] = obj["power"] =
            obj["energy"]  = obj["frequency"] = obj["pf"] = nullptr;
        }
    }

    // Tambahkan delay terakhir ke payload JSON agar bisa dibaca di Django (jika diperlukan)
    static unsigned long last_delay_ms = 0;
    doc["delay_ms"] = last_delay_ms;

    String body;
    serializeJson(doc, body);

    HTTPClient http;
    String url = "http://" + String(SERVER_IP) + ":" + SERVER_PORT + "/api/sensor-data";
    http.setReuse(false);  // Cegah koneksi TCP menggantung

    int code = -1;
    for (int attempt = 0; attempt < MAX_HTTP_RETRIES; attempt++) {
        http.begin(url);
        http.setTimeout(HTTP_TIMEOUT);
        http.addHeader("Content-Type", "application/json");
        
        unsigned long startPost = millis();
        code = http.POST(body);
        unsigned long endPost = millis();
        
        // Simpan waktu tempuh pengiriman (delay HTTP)
        last_delay_ms = endPost - startPost;

        if (code == 200) break;  // Sukses

        Serial.printf("[POST] Gagal HTTP %d (percobaan %d/%d)\n",
                      code, attempt + 1, MAX_HTTP_RETRIES);
        http.end();
        if (attempt < MAX_HTTP_RETRIES - 1) delay(500);
    }

    bool ok = (code == 200);
    if (ok) {
        Serial.printf("[POST] Terkirim OK (Delay Pengiriman: %lu ms)\n", last_delay_ms);
    } else {
        Serial.printf("[POST] Gagal setelah %d percobaan\n", MAX_HTTP_RETRIES);
    }
    http.end();
    return ok;
}

// ============================================================
//  SETUP
// ============================================================
void setup() {
    Serial.begin(115200);
    Serial.println("\n====================================");
    Serial.println("  SMEL - Smart Electricity Monitor");
    Serial.println("====================================");

    // Relay OFF saat boot (kondisi aman)
    for (int i = 0; i < NUM_CHANNELS; i++) {
        pinMode(relayPins[i], OUTPUT);
        digitalWrite(relayPins[i], LOW);
    }
    Serial.println("[BOOT] Relay OFF (kondisi aman)");

    // Koneksi WiFi
    connectWiFi();

    // Sinkronisasi NTP ke WIB (UTC+7)
    configTime(GMT_OFFSET, DST_OFFSET, NTP_SERVER);
    Serial.print("[NTP] Sinkronisasi waktu");
    for (int i = 0; i < 10; i++) {
        struct tm t;
        if (getLocalTime(&t)) {
            Serial.println(" OK");
            break;
        }
        delay(500);
        Serial.print(".");
    }
    Serial.println("[NTP] Timestamp: " + getTimestamp());

    // GET relay-status pertama kali saat boot
    Serial.println("[BOOT] Mengambil status relay dari server...");
    if (!fetchRelayStatus()) {
        Serial.println("[BOOT] Server tidak tersedia — relay tetap OFF");
    }

    Serial.println("====================================");
    Serial.println("  Mulai loop monitoring...");
    Serial.println("====================================\n");
}

// ============================================================
//  LOOP — Interval Tetap CYCLE_INTERVAL_MS per siklus
// ============================================================
// Menggunakan millis() untuk menjamin interval antar siklus
// SELALU konsisten (default 5 detik), sehingga selisih
// timestamp di database tidak bervariasi.
//
// Alur per siklus:
//   1. Reconnect WiFi jika putus
//   2. Update status warmup per channel
//   3. GET relay-status (setiap 10 siklus)
//   4. Jika ada relay ON → baca sensor PZEM → POST ke server
//      (channel yang masih warmup di-skip baca sensornya)
//   5. Tunggu sampai CYCLE_INTERVAL_MS tercapai
// ============================================================
void loop() {
    static int cycleCount = 0;
    static unsigned long lastCycleTime = 0;

    // Tunggu sampai interval tercapai (non-blocking)
    unsigned long now = millis();
    if (lastCycleTime > 0 && (now - lastCycleTime) < CYCLE_INTERVAL_MS) {
        delay(10);  // yield CPU
        return;
    }
    lastCycleTime = now;
    unsigned long cycleStart = now;

    // 1. Reconnect WiFi jika putus
    if (WiFi.status() != WL_CONNECTED) {
        connectWiFi();
    }

    // 2. Update status warmup per channel
    //    Jika sudah lewat WARMUP_MS sejak transisi OFF→ON,
    //    tandai warmup selesai — sensor siap dibaca
    for (int i = 0; i < NUM_CHANNELS; i++) {
        if (relayWarmingUp[i]) {
            unsigned long elapsed = millis() - relayOnTimestamp[i];
            if (elapsed >= WARMUP_MS) {
                relayWarmingUp[i] = false;
                Serial.printf("[WARMUP] Ch%d warmup selesai (%lu ms), sensor siap\n",
                              i + 1, elapsed);
            }
        }
    }

    // 3. GET relay-status setiap N siklus
    //    Jadwal tidak berubah tiap detik, cukup cek periodik
    if (cycleCount % RELAY_POLL_EVERY_N_CYCLES == 0) {
        Serial.println("--- [GET] Relay Status ---");
        fetchRelayStatus();
    }

    // 4. Cek apakah ada relay yang ON
    bool anyRelayOn = false;
    for (int i = 0; i < NUM_CHANNELS; i++) {
        if (relayState[i]) {
            anyRelayOn = true;
            break;
        }
    }

    if (anyRelayOn) {
        // 4a. Baca sensor hanya untuk channel yang relay-nya ON
        //     dan sudah melewati masa warmup
        Serial.println("--- [PZEM] Baca Sensor ---");
        SensorReading readings[NUM_CHANNELS];
        readings[0] = readChannel(pzem1, relayState[0], relayWarmingUp[0]);
        readings[1] = readChannel(pzem2, relayState[1], relayWarmingUp[1]);

        // Cek apakah ada channel yang masih warmup
        bool anyWarmup = false;
        for (int i = 0; i < NUM_CHANNELS; i++) {
            if (relayState[i] && relayWarmingUp[i]) {
                anyWarmup = true;
            }
        }

        // Log ke Serial Monitor
        for (int i = 0; i < NUM_CHANNELS; i++) {
            Serial.printf("  Ch%d: relay=%s",
                i + 1,
                readings[i].relay_on ? "ON" : "OFF");
            if (relayState[i] && relayWarmingUp[i]) {
                Serial.print(" [WARMUP - skip]");
            } else if (readings[i].sensor_ok) {
                Serial.printf(" sensor=OK V=%.1f A=%.3f W=%.1f kWh=%.3f Hz=%.1f PF=%.2f",
                    readings[i].voltage, readings[i].current, readings[i].power,
                    readings[i].energy,  readings[i].frequency, readings[i].pf);
            } else {
                Serial.print(readings[i].relay_on ? " sensor=FAIL" : " sensor=OFF");
            }
            Serial.println();
        }

        // POST data ke server → broadcast ke WebSocket dashboard
        // Jika channel sedang warmup, tetap kirim data tapi
        // relay_on=true + sensor_ok=false → server tahu relay ON
        // tapi tidak akan buat notifikasi N3 karena baru transisi
        Serial.println("--- [POST] Kirim Data ---");
        sendSensorData(readings);
    } else {
        // 4b. Semua relay OFF → tidak perlu baca sensor atau POST
        Serial.println("--- Semua relay OFF, skip baca sensor ---");
    }

    // 5. Log durasi siklus
    cycleCount++;
    unsigned long elapsed = millis() - cycleStart;
    Serial.printf("=== Siklus #%d selesai dalam %lu ms (interval %lu ms) ===\n\n",
                  cycleCount, elapsed, CYCLE_INTERVAL_MS);
}
