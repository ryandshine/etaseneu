# Scheduler Alerting

Dokumen ini merangkum metric scheduler hotspot yang sudah tersedia untuk monitoring kejadian kebakaran.

## Endpoint

- JSON operasional: `/api/scheduler/metrics`
- Prometheus exposition: `/api/metrics`

## Metric Utama

- `etaseneu_scheduler_last_sync_success`
  - `1` jika sync terakhir sukses
  - `0` jika sync terakhir gagal, skipped, atau belum pernah jalan
- `etaseneu_scheduler_consecutive_failures`
  - jumlah gagal beruntun pada scheduler
- `etaseneu_scheduler_last_new_hotspot_count`
  - jumlah hotspot baru yang muncul dibanding sync sukses sebelumnya
- `etaseneu_scheduler_has_new_hotspot`
  - `1` jika ada hotspot baru pada sync terakhir
- `etaseneu_scheduler_new_hotspot_over_threshold`
  - `1` jika `last_new_hotspot_count >= SCHEDULER_NEW_HOTSPOT_ALERT_THRESHOLD`
- `etaseneu_scheduler_new_hotspot_alert_threshold`
  - nilai threshold aktif dari konfigurasi
- `etaseneu_scheduler_seconds_since_last_successful_sync`
  - umur sejak sync sukses terakhir dalam detik
- `etaseneu_scheduler_next_scheduled_sync_timestamp_seconds`
  - estimasi jadwal sync berikutnya dalam Unix timestamp

## Konfigurasi

Atur threshold hotspot baru di [`.env`](/home/ryandshinevps/etaseneu/backend/.env):

```env
SCHEDULER_NEW_HOTSPOT_ALERT_THRESHOLD=1
```

Nilai `1` cocok untuk mode sensitif, yaitu alert setiap ada hotspot baru. Jika alert terlalu sering, naikkan ke `2`, `3`, atau lebih sesuai kebutuhan operasional.

## Contoh Query Prometheus

Alert saat ada hotspot baru:

```promql
etaseneu_scheduler_has_new_hotspot == 1
```

Alert saat hotspot baru melewati threshold:

```promql
etaseneu_scheduler_new_hotspot_over_threshold == 1
```

Alert saat scheduler gagal 2 kali berturut-turut:

```promql
etaseneu_scheduler_consecutive_failures >= 2
```

Alert saat tidak ada sync sukses lebih dari 4 jam:

```promql
etaseneu_scheduler_seconds_since_last_successful_sync > 14400
```

## Contoh Alert Rules

```yaml
groups:
  - name: etaseneu-scheduler
    rules:
      - alert: EtaseneuNewHotspotDetected
        expr: etaseneu_scheduler_has_new_hotspot == 1
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Hotspot baru terdeteksi"
          description: "Scheduler mendeteksi hotspot baru pada sync terakhir."

      - alert: EtaseneuNewHotspotOverThreshold
        expr: etaseneu_scheduler_new_hotspot_over_threshold == 1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Hotspot baru melewati threshold"
          description: "Jumlah hotspot baru pada sync terakhir melebihi threshold operasional."

      - alert: EtaseneuSchedulerUnhealthy
        expr: etaseneu_scheduler_consecutive_failures >= 2
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Scheduler hotspot tidak sehat"
          description: "Scheduler gagal minimal dua kali berturut-turut."

      - alert: EtaseneuSchedulerStale
        expr: etaseneu_scheduler_seconds_since_last_successful_sync > 14400
        for: 10m
        labels:
          severity: critical
        annotations:
          summary: "Sync hotspot stale"
          description: "Tidak ada sync sukses dalam lebih dari 4 jam."
```

## Rekomendasi Operasional

- Gunakan `warning` untuk `EtaseneuNewHotspotDetected` agar tim cepat tahu ada kejadian baru.
- Gunakan `critical` untuk `EtaseneuNewHotspotOverThreshold` dan `EtaseneuSchedulerUnhealthy`.
- Jika scheduler dijalankan tiap 3 jam, alert stale `4 jam` cukup aman untuk mendeteksi keterlambatan tanpa terlalu bising.
