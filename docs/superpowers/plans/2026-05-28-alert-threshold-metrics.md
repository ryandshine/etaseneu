# Alert Threshold Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menambahkan metric boolean alert-ready untuk scheduler hotspot berdasarkan jumlah hotspot baru per sync.

**Architecture:** Threshold alert dibaca dari config backend, lalu snapshot scheduler menghitung dua boolean derived metrics: ada hotspot baru dan hotspot baru melebihi threshold. Endpoint JSON dan Prometheus mengekspose nilai ini tanpa mengubah logika sync utama.

**Tech Stack:** FastAPI, pydantic-settings, pytest

---

### Task 1: Tulis failing test

**Files:**
- Modify: `backend/app/tests/test_scheduler.py`
- Modify: `backend/app/tests/test_config.py`

- [ ] Tambahkan test config threshold default/load.
- [ ] Tambahkan test JSON metrics dan Prometheus metric boolean.

### Task 2: Implement threshold config dan snapshot derived metrics

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/services/scheduler.py`

- [ ] Tambahkan config threshold.
- [ ] Hitung derived flags di snapshot metrics.

### Task 3: Expose metrics

**Files:**
- Modify: `backend/app/api/metrics.py`

- [ ] Tambahkan metric Prometheus boolean untuk alert rule.

### Task 4: Verifikasi

**Files:**
- Modify: `backend/app/tests/test_scheduler.py`

- [ ] Jalankan scheduler tests dan regression subset.
