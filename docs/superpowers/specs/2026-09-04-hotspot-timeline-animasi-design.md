# Desain: Timeline Animasi Hotspot di Peta ETA SENEU

Tanggal: 2026-09-04
Status: disetujui (menunggu review spec sebelum rencana implementasi)
Cabang kerja: `feat/hotspot-timeline-animasi`

## 1. Tujuan

Menambahkan pemutar (playback) waktu pada peta hotspot utama (`HotspotMap.tsx`)
sehingga pengguna dapat "memutar" sebaran titik panas dari awal ke akhir jendela
waktu yang sedang dipilih, dan melihat pola menyebar/menumpuknya kejadian.

Mode yang dipilih: **kumulatif dengan pudar berdasar umur** — titik menumpuk
seiring playhead maju; bucket saat playhead menyala penuh, bucket-bucket
sebelumnya meredup bertahap sampai batas lantai opacity, titik "masa depan"
disembunyikan.

Non-tujuan (v1):
- Tidak ada mode "jendela geser" (dicatat sebagai tambahan mudah berikutnya).
- Tidak ada ekspor GIF/MP4.
- Tidak ada perubahan backend — animasi murni memfilter/menata array `hotspots`
  yang sudah dimuat di sisi klien.
- State toggle tidak dipersist ke localStorage.
- Tidak diterapkan ke peta di `KpsDetailView.tsx` (hanya peta utama).

## 2. Konteks kode yang relevan

- `hooks/useDashboardData.ts` — satu-satunya pemegang state dashboard; memuat
  `hotspots: DashboardHotspot[]` sekali dan mengopernya ke `HotspotMap`. Tiap
  hotspot punya `detectedAt` (string ISO). Jendela waktu diturunkan dari
  `endDate` + preset (lihat `buildTimeRange`). Cache localStorage membatasi
  ~6.000 titik.
- `components/HotspotMap.tsx` (~953 baris) — merender tiap hotspot sebagai
  `<CircleMarker>` (renderer canvas bersama `fireCanvasRenderer`, `tolerance:18`)
  atau `<Marker>` divIcon untuk FRP tinggi (`> HIGH_FRP_THRESHOLD`), di dalam
  `<LayerGroup ref={hotspotLayerGroupRef}>` pada pane `kps-interaktif`. Perilaku
  load-bearing (didokumentasikan di CLAUDE.md):
  - tiap `<Popup>` hotspot WAJIB `pane="popupPane"`;
  - titik dipaksa `bringToFront()` tiap render lewat effect pada
    `hotspotLayerGroupRef`;
  - SATU canvas `fireCanvasRenderer` dipakai bersama semua layer api di pane itu
    (target tap ~25px);
  - `PolygonInfoLayer` menerima prop `hotspots` dan menahan popup poligon bila
    tap dalam 30px dari titik mana pun.
- Tombol toggle peta yang sudah ada ("Angin", "Fungsi Kawasan Hutan", overlay
  cuaca) — pola untuk menempatkan tombol "Timeline".
- `lib/date.ts` — helper WIB/Asia-Jakarta untuk label waktu.
- `constants/time-windows.ts` — `TimePreset`, opsi preset.

## 3. Arsitektur

### 3.1 Berkas baru

| Berkas | Isi |
|---|---|
| `lib/hotspotTimeline.ts` | Fungsi murni, tanpa React/Leaflet. Diekspor: `computeBuckets`, `opacityForBucket`, `bucketLabelWIB`, konstanta (`MAX_FRAMES`, `FADE_BUCKETS`, `OPACITY_FLOOR`, `SPEED_STEPS`, `TICK_MS`). |
| `hooks/useHotspotTimeline.ts` | Hook state + loop animasi. |
| `components/HotspotTimelineControl.tsx` | Bar kontrol melayang (presentasional). |
| `lib/hotspotTimeline.test.ts` | Unit test fungsi murni. |
| `hooks/useHotspotTimeline.test.ts` | Unit test hook (React Testing Library + fake timers). |
| `components/HotspotTimelineControl.test.tsx` | Render test bar kontrol. |

### 3.2 Perubahan `HotspotMap.tsx`

1. **Ekstrak `HotspotMarkersLayer` (child internal, `React.memo`).** Pindahkan
   blok `hotspots.map(...)` yang ada **apa adanya** (JSX, `fireCanvasRenderer`,
   `<Marker>`/`<CircleMarker>`, `<Popup pane="popupPane">`, `getHighIntensityIcon`)
   ke komponen `HotspotMarkersLayer({ hotspots, onOpenKpsDetail, registerMarker })`.
   Di-`memo` dengan pembanding default (re-render hanya jika `hotspots`/handler
   berubah — keduanya stabil selama animasi). `<LayerGroup ref>` + effect
   `bringToFront` tetap di `HotspotMap` membungkus child ini agar perilaku
   z-order tidak berubah.
2. **Callback-ref registry.** `registerMarker(id, layerOrNull)` mengisi
   `markerRefs.current: Map<string, L.CircleMarker | L.Marker>`; dipanggil dari
   prop `ref` tiap `<CircleMarker>`/`<Marker>`. `null` saat unmount → hapus dari
   Map. `markerRefs` adalah `useRef` di `HotspotMap`.
3. **Toggle "Timeline".** State `timelineOn` (`useState(false)`) di `HotspotMap`.
   Tombol di deret tombol peta, ikon jam/putar. Nonaktif (disabled) bila
   `hotspots.length === 0`.
4. **Saat `timelineOn`:**
   - Panggil `useHotspotTimeline(hotspots, { enabled: timelineOn })`.
   - Render `<HotspotTimelineControl {...timeline} />` (posisi absolute,
     bawah-tengah, `z-index` di atas atribusi Leaflet, di bawah panel/popup).
   - Effect driver: `useEffect` bergantung `[timeline.playheadIndex, timelineOn]`
     yang menata-ulang style marker via `markerRefs` (lihat 3.4).
   - Saat `timelineOn` berubah `true→false`: satu pass mengembalikan semua
     marker ke style penuh (`fillOpacity` awal, `interactive:true`, `setOpacity(1)`
     untuk `<Marker>`), lalu render statis berjalan seperti semula.

### 3.3 `lib/hotspotTimeline.ts` — fungsi murni

```
type Bucket = { index: number; start: number; end: number; count: number };

// Aturan granularitas dari lebar rentang (ms):
//   <= 48 jam  -> bucket 1 jam
//   <= 7 hari  -> bucket 3 jam
//   >  7 hari  -> bucket 1 hari
// Lalu jika jumlah bucket > MAX_FRAMES (120), perbesar bucketMs kelipatan 2
// sampai <= MAX_FRAMES.
computeBuckets(hotspots: {detectedAt: string}[], filterWindow?: {start:number; end:number}): Bucket[]
//   - rentang = filterWindow bila ada, selain itu [min,max] detectedAt hotspot.
//   - rentang di-"floor" ke kelipatan bucketMs pada start.
//   - count = jumlah hotspot dengan start <= detectedAt < end (bucket terakhir inklusif end).
//   - hotspot dengan detectedAt tak valid diabaikan (tidak masuk bucket mana pun).
//   - hotspots kosong -> [] .

// opacity untuk sebuah bucket b saat playhead di p:
//   b > p              -> 0        (masa depan, disembunyikan + non-interaktif)
//   b === p            -> 1        (bucket aktif)
//   p - b <= FADE_BUCKETS (6) -> lerp linear dari ~0.85 ke OPACITY_FLOOR
//   selain itu         -> OPACITY_FLOOR (0.28)
// Dikuantisasi ke langkah 0.05 supaya perubahan style per-tick terbatas pada
// beberapa bucket saja.
opacityForBucket(playheadIndex: number, bucketIndex: number): number

bucketLabelWIB(ms: number, bucketMs: number): string   // "8 Agu 2026, 13:00 WIB" / "8 Agu 2026" untuk bucket harian

const MAX_FRAMES = 120;
const FADE_BUCKETS = 6;
const OPACITY_FLOOR = 0.28;
const SPEED_STEPS = [1, 2, 4] as const;
const TICK_MS = 700;   // interval per-langkah pada 1x
```

### 3.4 `hooks/useHotspotTimeline.ts`

Input: `hotspots`, `{ enabled, filterWindow? }`. Di v1 `filterWindow` TIDAK
dioper (`HotspotMap` tidak menerima rentang waktu terselesaikan sebagai prop),
sehingga rentang bucket = `[min,max]` `detectedAt` dari `hotspots` yang dimuat.
Parameter dibiarkan opsional untuk perluasan.

State internal:
- `buckets` — `useMemo(() => computeBuckets(hotspots, filterWindow), [hotspots, filterWindow])`.
- `playheadIndex` — `useState`. Saat `buckets` berubah (data baru) → set ke
  `buckets.length - 1` dan `isPlaying=false` (re-init: tampilkan semua, jeda).
- `isPlaying` — `useState(false)`.
- `speedIdx` — `useState(0)` → `speed = SPEED_STEPS[speedIdx]`.

Loop:
- `requestAnimationFrame` akumulasi `elapsed`; saat `elapsed >= TICK_MS / speed`
  → `playheadIndex++`. Di `playheadIndex === buckets.length - 1` → `isPlaying=false`
  (berhenti, tidak loop).
- Loop hanya jalan saat `enabled && isPlaying`. Dibersihkan di cleanup.

Aksi yang diekspor:
- `play()` — bila `playheadIndex` sudah di akhir → set ke 0 dulu, lalu
  `isPlaying=true` (efek "ulang").
- `pause()`, `toggle()`.
- `seek(index)` — clamp; set `isPlaying=false`.
- `cycleSpeed()` — `speedIdx = (speedIdx + 1) % SPEED_STEPS.length`.

Nilai yang diekspor untuk UI & driver: `buckets`, `playheadIndex`, `isPlaying`,
`speed`, `currentBucket` (`buckets[playheadIndex]`), `label` (`bucketLabelWIB`),
aksi di atas.

Driver (di `HotspotMap`, bukan di hook) — `useEffect([playheadIndex, timelineOn])`:
```
for (const [id, layer] of markerRefs.current) {
  const b = bucketIndexOf(id);            // dari Map<id, bucketIndex> yang dibangun bersama buckets
  const o = opacityForBucket(playheadIndex, b);
  if (layer instanceof L.Marker) {
    layer.setOpacity(o === 0 ? 0 : 1);    // divIcon: biner
  } else {
    // base awal CircleMarker: fillOpacity 0.98, stroke opacity 1, weight 2
    layer.setStyle({ fillOpacity: o === 0 ? 0 : o * 0.98, opacity: o === 0 ? 0 : 1, interactive: o > 0 });
  }
}
```
Optimasi: simpan `lastPlayhead`; hanya sentuh marker yang bucket-nya berada di
rentang yang opacity-nya berubah (`[min(last,cur) - FADE_BUCKETS, max(last,cur)]`).
Peta `bucketIndexOf` dibangun sekali per `buckets` (loop sekali atas `hotspots`).

### 3.5 `components/HotspotTimelineControl.tsx`

Presentasional. Props = keluaran hook + `onClose`.

Tata letak (bar tunggal, absolute bottom-center peta, lebar responsif):
- Kiri: tombol play/pause (ikon lucide `Play`/`Pause`).
- Tengah: **histogram-scrubber**. `buckets.length` batang, tinggi ∝
  `count / maxCount`. Batang index `<= playheadIndex` diberi warna aktif
  (oranye), sisanya redup. Playhead = garis/segitiga pada posisi
  `playheadIndex`. Interaksi: klik/drag pada area histogram → hitung index dari
  posisi x → `seek(index)`. Implementasi drag: `pointerdown`/`pointermove`/
  `pointerup` pada elemen container (bukan `<input range>` demi kontrol visual;
  namun sediakan `<input type="range">` tersembunyi/overlay untuk aksesibilitas
  keyboard + `aria-valuenow/min/max`).
- Kanan: label waktu berjalan (`label`) + tombol kecepatan (`{speed}×`, klik →
  `cycleSpeed`).
- Tombol "×" kecil (opsional) → `onClose` (mematikan `timelineOn`); atau cukup
  andalkan tombol toggle peta.

Kosong-data: bila `buckets.length === 0` → bar tidak dirender (atau tampil
"Tidak ada titik pada rentang ini"). Karena tombol toggle sudah disabled saat
`hotspots.length === 0`, kasus ini praktis tidak terjadi.

`prefers-reduced-motion`: animasi hanya berjalan atas aksi pengguna (tekan play),
jadi tidak perlu penonaktifan khusus; transisi CSS pada batang histogram
dimatikan bila media query aktif.

## 4. Alur data

```
useDashboardData ── hotspots ──► HotspotMap
                                   │
                    ┌──────────────┼───────────────────────────┐
                    ▼              ▼                           ▼
      HotspotMarkersLayer   useHotspotTimeline(hotspots)   HotspotTimelineControl
      (memo; render sekali)   │  buckets, playheadIndex        (render tiap tick,
      registerMarker(id,ref)  │  isPlaying, speed, aksi         murah)
             │                │
             ▼                ▼
      markerRefs: Map ◄─── driver useEffect([playheadIndex])
                            setStyle/setOpacity imperatif
```

Perubahan filter (waktu/satelit/provinsi) di `useDashboardData` → `hotspots`
baru → `HotspotMarkersLayer` re-render (wajar, di luar animasi) → `buckets`
dihitung ulang → hook re-init (playhead ke akhir, jeda).

## 5. Penanganan kasus tepi

| Kasus | Perilaku |
|---|---|
| `hotspots` kosong | Tombol toggle disabled. |
| Semua `detectedAt` sama / rentang < 1 bucket | 1 bucket; play langsung selesai; histogram 1 batang. |
| `detectedAt` tak valid | Titik diabaikan dari bucketing; tetap dirender statis penuh saat playhead di akhir; saat animasi diberi `OPACITY_FLOOR` (diperlakukan sebagai bucket 0) — dokumentasikan di kode. |
| Toggle dimatikan saat play | Loop berhenti (cleanup), satu pass restore style penuh. |
| Data berubah saat play | Hook re-init: playhead ke akhir, `isPlaying=false`, satu pass restore. |
| Klik titik saat play | Popup terbuka (`pane="popupPane"`), animasi lanjut. |
| Layer FRP tinggi (`<Marker>` divIcon) | Opacity biner (0 atau 1) via `setOpacity`. |
| Peta di `KpsDetailView` | Tidak terpengaruh (fitur hanya di peta utama). |

## 6. Rencana pengujian

**Unit — `lib/hotspotTimeline.test.ts`:**
- `computeBuckets`: granularitas 1 jam untuk rentang 36 jam; 3 jam untuk 5 hari;
  1 hari untuk 20 hari; pelebaran bucket saat > `MAX_FRAMES` (rentang 1 tahun).
- `computeBuckets`: `count` per bucket benar; batas inklusif/eksklusif; hotspot
  `detectedAt` invalid diabaikan; input kosong → `[]`.
- `opacityForBucket`: `b>p`→0; `b===p`→1; peluruhan dalam `FADE_BUCKETS`;
  lantai `OPACITY_FLOOR` di luar itu; kuantisasi 0.05.
- `bucketLabelWIB`: format jam vs harian; zona WIB.

**Hook — `hooks/useHotspotTimeline.test.ts` (fake timers):**
- Awal: `playheadIndex === buckets.length - 1`, `isPlaying === false`.
- `play()` dari akhir → playhead ke 0 lalu maju; `2×` → maju 2× lebih cepat per
  satuan waktu; berhenti di bucket terakhir (`isPlaying` jadi `false`).
- `seek(n)` clamp + pause.
- Ganti prop `hotspots` → re-init (playhead ke akhir, pause).
- `enabled=false` → loop tidak jalan.

**Komponen — `components/HotspotTimelineControl.test.tsx`:**
- Jumlah batang histogram === `buckets.length`.
- Klik play memanggil `toggle`/`play`; ikon berubah sesuai `isPlaying`.
- Interaksi scrub memanggil `seek` dengan index sesuai posisi.
- Label waktu === `bucketLabelWIB(currentBucket.start, bucketMs)`.
- `aria-valuenow/min/max` pada input range tersembunyi.

**Integrasi ringan (opsional, jika hemat):** render `HotspotMap` dengan
`hotspots` contoh, nyalakan toggle, pastikan bar muncul dan `markerRefs` terisi.

**Verifikasi manual:** `cd frontend && npm test` (vitest) + `npm run build`
(`tsc --noEmit` + `vite build`) hijau. Cek asap di `npm run dev`: play pada
preset 7 Hari & 30 Hari dengan data nyata, pastikan mulus dan popup masih bisa
diklik.

**Backend:** tidak ada perubahan → tidak ada test backend.

## 7. Risiko & mitigasi

- **Regresi perilaku load-bearing `HotspotMap`** (canvas `tolerance:18`,
  `bringToFront` tiap render, `pane="popupPane"`, guard `PolygonInfoLayer` 30px).
  Mitigasi: pindahkan JSX marker **identik** ke child; `<LayerGroup ref>` +
  effect `bringToFront` + `fireCanvasRenderer` + prop `hotspots` ke
  `PolygonInfoLayer` tetap di `HotspotMap`. Tidak mengubah string/opsi apa pun,
  hanya membungkus `memo` + menambah `ref`.
- **`React.memo` tidak efektif** bila handler `onOpenKpsDetail` berubah tiap
  render. Mitigasi: pastikan handler dibungkus `useCallback` di pemanggil
  (`App.tsx`) atau di `HotspotMap`; verifikasi via test/console saat implementasi.
- **Kebocoran ref** ke ~6.000 layer. Mitigasi: callback-ref menghapus entri saat
  `null`; `markerRefs` di-`clear()` saat `hotspots` berubah identitas.
- **Jank saat re-init data besar** (bukan saat play). Diterima — sama seperti
  render peta biasa sekarang.
- **Cap 6.000 titik dari cache**: animasi pada rentang panjang bisa kehilangan
  sebagian titik lama. Diterima untuk v1; sama batasannya dengan tampilan statis.

## 8. Perluasan berikutnya (di luar cakupan)

- Toggle mode "jendela geser".
- Ekspor GIF/MP4 rentang animasi (menyambung ke kebutuhan deck .pptx).
- Persist state toggle + kecepatan di `dashboardPersistence`.
- Terapkan ke peta `KpsDetailView`.
