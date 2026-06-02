# Scheduler Alerting Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menambahkan konfigurasi `.env` untuk threshold hotspot baru dan dokumentasi contoh alert rule Prometheus/Grafana.

**Architecture:** Runtime config tetap bersumber dari `.env`, sementara dokumentasi alerting menjelaskan endpoint metrics, metric penting, dan contoh rule berbasis threshold baru.

**Tech Stack:** FastAPI settings, Markdown docs

---

### Task 1: Tambahkan env var threshold

**Files:**
- Modify: `backend/.env`

- [ ] Tambahkan `SCHEDULER_NEW_HOTSPOT_ALERT_THRESHOLD` dengan komentar singkat.

### Task 2: Dokumentasikan alerting

**Files:**
- Create: `docs/monitoring/scheduler-alerting.md`

- [ ] Tulis daftar metric utama, contoh query Prometheus, dan contoh rule alerting.

### Task 3: Verifikasi

**Files:**
- Modify: `docs/monitoring/scheduler-alerting.md`

- [ ] Cek ulang path endpoint dan nama metric agar sesuai implementasi.
