# New Hotspot Metric Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menambahkan metrik `hotspot baru sejak sync sebelumnya` untuk scheduler hotspot.

**Architecture:** Scheduler menyimpan fingerprint stabil dari hotspot hasil sync sukses terakhir. Sync sukses berikutnya membandingkan fingerprint saat ini dengan baseline sebelumnya untuk menghitung jumlah hotspot baru, lalu mengekspos nilainya ke JSON metrics dan Prometheus.

**Tech Stack:** FastAPI, asyncio, pytest

---

### Task 1: Tulis failing test untuk new hotspot metric

**Files:**
- Modify: `backend/app/tests/test_scheduler.py`

- [ ] Tambahkan test baseline first sync = 0 dan sync berikutnya menghitung hotspot baru.
- [ ] Tambahkan assertion untuk JSON metrics dan Prometheus metric baru.

### Task 2: Implement fingerprint dan counter baru

**Files:**
- Modify: `backend/app/services/scheduler.py`

- [ ] Tambahkan state fingerprint dan `last_new_hotspot_count`.
- [ ] Hitung delta fingerprint hanya saat sync sukses.

### Task 3: Expose metrics

**Files:**
- Modify: `backend/app/api/metrics.py`

- [ ] Tambahkan metric JSON dan Prometheus untuk jumlah hotspot baru.

### Task 4: Verifikasi

**Files:**
- Modify: `backend/app/tests/test_scheduler.py`

- [ ] Jalankan test scheduler dan regression subset.
