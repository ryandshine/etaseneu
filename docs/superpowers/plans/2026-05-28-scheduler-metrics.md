# Scheduler Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menambahkan metrics operasional scheduler dalam format JSON dan Prometheus untuk monitoring sync hotspot kebakaran.

**Architecture:** Status runtime scheduler tetap menjadi sumber kebenaran tunggal di service scheduler. API scheduler membaca state itu untuk endpoint JSON, dan endpoint `/api/metrics` merender subset state yang stabil untuk scraping Prometheus.

**Tech Stack:** FastAPI, asyncio, pytest, ASGI request tests

---

### Task 1: Tambahkan failing test untuk metrics scheduler

**Files:**
- Modify: `backend/app/tests/test_scheduler.py`

- [ ] Tambahkan test untuk JSON metrics dan Prometheus metrics.
- [ ] Jalankan test target dan verifikasi gagal karena endpoint/field belum ada.

### Task 2: Perluas runtime state scheduler

**Files:**
- Modify: `backend/app/services/scheduler.py`

- [ ] Simpan `last_successful_sync_at`, `consecutive_failures`, `next_scheduled_sync_at`, dan helper snapshot metrics.
- [ ] Pastikan sukses me-reset counter gagal dan gagal menambah counter gagal.

### Task 3: Tambahkan endpoint JSON dan Prometheus

**Files:**
- Modify: `backend/app/api/scheduler.py`
- Create: `backend/app/api/metrics.py`
- Modify: `backend/app/api/router.py`

- [ ] Tambahkan `/api/scheduler/metrics` untuk JSON operasional.
- [ ] Tambahkan `/api/metrics` untuk Prometheus text exposition.

### Task 4: Verifikasi

**Files:**
- Modify: `backend/app/tests/test_scheduler.py`

- [ ] Jalankan test scheduler.
- [ ] Jalankan subset regression test yang relevan.
