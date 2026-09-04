"""Tes LandCoverService. Tidak ada panggilan GEE/DB nyata (bahaya #1)."""

from __future__ import annotations

import pytest

from app.services.land_cover_service import (
    CLASS_KEYS,
    SAMPLES_PER_CLASS_PER_YEAR,
    TRAIN_BUFFER_M,
    YEARS,
    _LAND_COVER_RUN_STATE,
    LandCoverError,
    LandCoverService,
    _build_summary_text,
    _dw_label_to_class,
    _net_change,
    land_cover_any_running,
)


def _svc() -> LandCoverService:
    return LandCoverService.__new__(LandCoverService)


def test_years_constant() -> None:
    assert YEARS == (2021, 2022, 2023, 2024, 2025)


def test_land_cover_any_running_none_when_empty() -> None:
    assert not _LAND_COVER_RUN_STATE
    assert land_cover_any_running() is None


def test_land_cover_any_running_returns_the_running_polygon() -> None:
    _LAND_COVER_RUN_STATE[42] = {"state": "running", "step": "2021 (1/5) — sampel"}
    try:
        result = land_cover_any_running()
        assert result == {"polygon_id": 42, "step": "2021 (1/5) — sampel"}
    finally:
        _LAND_COVER_RUN_STATE.pop(42, None)


@pytest.mark.parametrize(
    "label,expected",
    [(0, "air"), (1, "hutan"), (2, "semak"), (3, "semak"), (4, "pertanian"),
     (5, "semak"), (7, "terbuka"), (6, None), (8, None), (99, None)],
)
def test_dw_label_to_class(label, expected) -> None:
    assert _dw_label_to_class(label) == expected


def test_enabled_false_without_credentials(monkeypatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    for k in ("GEE_SERVICE_ACCOUNT_EMAIL", "GEE_SERVICE_ACCOUNT_KEY_PATH", "GEE_PROJECT_ID"):
        monkeypatch.setenv(k, "")
    try:
        svc = _svc()
        svc.settings = get_settings()
        assert svc.enabled is False
    finally:
        get_settings.cache_clear()


def test_ensure_ee_raises_when_not_configured(monkeypatch) -> None:
    from app.core.config import get_settings

    get_settings.cache_clear()
    for k in ("GEE_SERVICE_ACCOUNT_EMAIL", "GEE_SERVICE_ACCOUNT_KEY_PATH", "GEE_PROJECT_ID"):
        monkeypatch.setenv(k, "")
    try:
        svc = _svc()
        svc.settings = get_settings()
        svc._ee_initialized = False
        with pytest.raises(LandCoverError):
            svc._ensure_ee()
    finally:
        get_settings.cache_clear()


def test_net_change_and_summary() -> None:
    table = {
        2021: {"hutan": {"area_ha": 5400.0, "pct": 74.9}, "semak": {"area_ha": 1150.0, "pct": 15.9},
               "pertanian": {"area_ha": 380.0, "pct": 5.3}, "terbuka": {"area_ha": 180.0, "pct": 2.5},
               "air": {"area_ha": 101.0, "pct": 1.4}},
        2025: {"hutan": {"area_ha": 4470.0, "pct": 62.0}, "semak": {"area_ha": 1560.0, "pct": 21.6},
               "pertanian": {"area_ha": 810.0, "pct": 11.2}, "terbuka": {"area_ha": 270.0, "pct": 3.7},
               "air": {"area_ha": 101.0, "pct": 1.4}},
    }
    nc = _net_change(table)
    assert nc["hutan"] == pytest.approx(-930.0)
    assert nc["pertanian"] == pytest.approx(430.0)
    text = _build_summary_text(table)
    assert "Hutan" in text and "930" in text


def test_summary_says_stabil_when_hutan_change_is_negligible() -> None:
    # Delta hutan 0,3 ha -- di bawah ambang _MEANINGFUL_HA (0,5), tidak boleh
    # dibilang "naik 0 ha" (kontradiktif: 0 tapi disebut "naik").
    table = {
        2021: {"hutan": {"area_ha": 5400.0, "pct": 74.9}},
        2025: {"hutan": {"area_ha": 5400.3, "pct": 74.9}},
    }
    text = _build_summary_text(table)
    assert "relatif stabil" in text
    assert "naik" not in text and "turun" not in text


def test_summary_omits_gainers_below_meaningful_threshold() -> None:
    # net_change semak = 0,2 ha -- lolos filter lama (> 0) tapi dibulatkan
    # jadi "+0 ha" kalau ditampilkan; sekarang harus disaring habis, bukan
    # muncul sebagai "Beralih terutama ke Semak/Belukar (+0 ha)".
    table = {
        2021: {"hutan": {"area_ha": 5400.0, "pct": 90.0}, "semak": {"area_ha": 100.0, "pct": 10.0}},
        2025: {"hutan": {"area_ha": 4470.0, "pct": 74.5}, "semak": {"area_ha": 100.2, "pct": 10.0}},
    }
    text = _build_summary_text(table)
    assert "+0 ha" not in text
    assert "Beralih terutama ke" not in text
    text = _build_summary_text(table)
    assert "Hutan" in text and "930" in text


def test_summary_incomplete_data() -> None:
    assert "tidak lengkap" in _build_summary_text({2021: {}}).lower()


# ---------------------------------------------------------------------------
# Integrasi analyze_polygon — fake ee + fake store (TIDAK ada GEE/DB nyata).
#
# Catatan: test double di brief bersifat ILUSTRATIF. `_FakeEE.Image` di brief
# dibangun via `type(...)` sehingga `ee.Image("id")` (dipakai sebagai konstruktor
# untuk NASADEM) melempar TypeError, dan `_FakeReducer.sum()` mengembalikan str
# sehingga `.group(...)` gagal. Keduanya dikoreksi di bawah supaya
# `analyze_polygon` jalan end-to-end tanpa menyentuh Earth Engine sungguhan.
# ---------------------------------------------------------------------------


class _FakeGetInfo:
    def __init__(self, payload):
        self._payload = payload

    def getInfo(self):
        return self._payload


class _FakeImg:
    """Rantai method EE yang dipakai analyze_polygon — kebanyakan no-op."""

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def reduceRegion(self, *a, **k):
        # satu grup per kelas idx 0..4, luas 100 ha (1e6 m2) tiap kelas
        return _FakeGetInfo({"groups": [{"class": i, "sum": 1_000_000.0} for i in range(5)]})

    def getInfo(self):
        # Materialisasi sampel latih (`samples.getInfo()`): 5 kelas hadir
        # -> jalur Random Forest. Jumlah baris = target sampel penuh.
        from app.services.land_cover_service import FEATURE_NAMES

        feats = []
        for cls in range(5):
            for _ in range(SAMPLES_PER_CLASS_PER_YEAR * len(YEARS)):
                props = {name: 0.1 for name in FEATURE_NAMES}
                props["class_idx"] = cls
                feats.append({"properties": props})
        return {"features": feats}

    def reduceToVectors(self, *a, **k):
        # satu fitur per kelas (labelProperty="class_idx"), semua di dalam ROI
        return _FakeGetInfo(
            {
                "features": [
                    {
                        "properties": {"class_idx": i},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[104.0, -2.0], [104.05, -2.0], [104.05, -1.95],
                                 [104.0, -1.95], [104.0, -2.0]]
                            ],
                        },
                    }
                    for i in range(5)
                ]
            }
        )


class _FakeImageClass(_FakeImg):
    """Dipakai baik sebagai konstruktor (`ee.Image(id)`) maupun namespace
    static (`ee.Image.pixelArea()`, `ee.Image.cat(...)`)."""

    def __init__(self, *a, **k):
        pass

    @staticmethod
    def pixelArea():
        return _FakeImg()

    @staticmethod
    def cat(*a, **k):
        return _FakeImg()


class _FakeColl:
    def __getattr__(self, _name):
        return lambda *a, **k: self

    def median(self):
        return _FakeImg()

    def mode(self):
        return _FakeImg()

    def mean(self):
        return _FakeImg()


class _FakeClassifier:
    def train(self, *a, **k):
        return self

    def explain(self):
        return _FakeGetInfo({"outOfBagErrorEstimate": 0.19})


class _FakeReducer:
    def __getattr__(self, _n):
        # sum()/group()/max() semuanya mengembalikan token reducer chainable
        return lambda *a, **k: self


class _FakeGeom:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, _n):
        return lambda *a, **k: self


class _FakeFC:
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, _n):
        return lambda *a, **k: self


class _FakeEE:
    ImageCollection = staticmethod(lambda _id: _FakeColl())
    Image = _FakeImageClass
    Geometry = _FakeGeom
    Feature = staticmethod(lambda *a, **k: object())
    FeatureCollection = _FakeFC
    # ee.Dictionary({...}).getInfo() -> evaluasi tiap nilai (luas + vektor
    # per tahun dalam satu request)
    Dictionary = staticmethod(
        lambda d: _FakeGetInfo({k: v.getInfo() for k, v in d.items()})
    )
    Filter = type("F", (), {"lt": staticmethod(lambda *a, **k: "flt")})
    Reducer = _FakeReducer()
    Classifier = type(
        "C", (), {"smileRandomForest": staticmethod(lambda *a, **k: _FakeClassifier())}
    )
    Terrain = type("T", (), {"products": staticmethod(lambda *a, **k: _FakeImg())})


_TARGET_LAYERS = ("psagustus2026", "HUTAN_ADAT_APR26")


class _FakeStore:
    def __init__(self, target):
        self._target = target
        self.saved: dict | None = None
        self.errored: str | None = None
        self.running: tuple | None = None

    def read_land_cover_target_polygon(self, polygon_id):
        # meniru filter SQL: hanya poligon aktif di salah satu layer target
        if not self._target or self._target.get("layer_key") not in _TARGET_LAYERS:
            return None
        return self._target

    def mark_land_cover_running(self, polygon_id, layer_key):
        self.running = (polygon_id, layer_key)

    def mark_land_cover_error(self, polygon_id, message):
        self.errored = message

    def save_land_cover_result(self, polygon_id, layer_key, **kw):
        self.saved = {"polygon_id": polygon_id, "layer_key": layer_key, **kw}


_TARGET = {
    "id": 287785,
    "layer_key": "psagustus2026",
    "lembaga": "LPHD MUARA MERANG",
    "nama_prov": "Sumatera Selatan",
    "geometry_json": {
        "type": "Polygon",
        "coordinates": [
            [[104.0, -2.0], [104.1, -2.0], [104.1, -1.9], [104.0, -1.9], [104.0, -2.0]]
        ],
    },
}


def test_analyze_polygon_unknown_polygon_raises(monkeypatch) -> None:
    svc = _svc()
    svc.postgres_store = _FakeStore(None)
    monkeypatch.setattr(svc, "_ensure_ee", lambda: _FakeEE())
    with pytest.raises(LandCoverError):
        svc.analyze_polygon(999999)


def test_analyze_polygon_wrong_layer_key_raises(monkeypatch) -> None:
    svc = _svc()
    store = _FakeStore({**_TARGET, "layer_key": "layer_bukan_target"})
    svc.postgres_store = store
    monkeypatch.setattr(svc, "_ensure_ee", lambda: _FakeEE())
    with pytest.raises(LandCoverError):
        svc.analyze_polygon(287785)
    assert store.saved is None
    assert store.running is None  # tidak pernah mencapai try


def test_analyze_polygon_happy_path_saves_all_years_classes(monkeypatch) -> None:
    svc = _svc()
    store = _FakeStore(_TARGET)
    svc.postgres_store = store
    monkeypatch.setattr(svc, "_ensure_ee", lambda: _FakeEE())

    result = svc.analyze_polygon(287785)

    assert result["years"] == list(YEARS)
    assert result["classes"] == list(CLASS_KEYS)
    assert result["oob_accuracy"] == pytest.approx(0.81)  # 1 - 0.19
    assert store.running == (287785, "psagustus2026")
    # 5 tahun x 5 kelas
    assert len(store.saved["year_class_rows"]) == len(YEARS) * 5
    assert store.saved["model_trees"] == 150
    assert store.saved["n_training"] == SAMPLES_PER_CLASS_PER_YEAR * 5 * len(YEARS)
    for year in YEARS:
        pct_sum = sum(r["pct"] for r in store.saved["year_class_rows"] if r["year"] == year)
        assert pct_sum == pytest.approx(100.0, abs=0.5)
    assert set(result["net_change"].keys()) == set(CLASS_KEYS)
    assert isinstance(result["summary_text"], str) and result["summary_text"]
    # progres live dibersihkan di finally
    assert 287785 not in _LAND_COVER_RUN_STATE
    # Loop _year_class_geom benar-benar jalan: fake reduceToVectors mengembalikan
    # satu poligon di dalam ROI untuk tiap kelas -> 5 tahun x 5 kelas = 25 baris
    # geometri, masing-masing sudah dinormalkan ke MultiPolygon. Tanpa assert ini,
    # regresi yang membuang pengisian year_geom_rows tidak akan ketahuan (Task 4
    # membaca year_geom_rows untuk lapisan peta).
    assert len(store.saved["year_geom_rows"]) == len(YEARS) * 5
    first_geom = store.saved["year_geom_rows"][0]
    assert set(first_geom) == {"year", "class_key", "geometry_geojson"}
    assert first_geom["geometry_geojson"]["type"] == "MultiPolygon"


def test_analyze_polygon_error_inside_try_marks_error_and_rewraps(monkeypatch) -> None:
    """Kegagalan DI DALAM try (mis. save gagal) harus: tandai error via
    mark_land_cover_error, tetap sudah set running lebih dulu, bersihkan progres
    live, dan dibungkus ulang jadi LandCoverError (bukan exception mentah)."""

    class _RaisingStore(_FakeStore):
        def save_land_cover_result(self, polygon_id, layer_key, **kw):
            raise RuntimeError("boom")

    svc = _svc()
    store = _RaisingStore(_TARGET)
    svc.postgres_store = store
    monkeypatch.setattr(svc, "_ensure_ee", lambda: _FakeEE())

    with pytest.raises(LandCoverError):
        svc.analyze_polygon(287785)

    assert store.errored is not None
    assert "boom" in store.errored
    assert store.running == (287785, "psagustus2026")  # running di-set sebelum gagal
    assert 287785 not in _LAND_COVER_RUN_STATE  # finally tetap membersihkan


def test_materialize_samples_drops_masked_rows_and_counts_classes() -> None:
    """Sampel latih ditarik ke klien SEKALI; baris yang salah satu fiturnya
    None (piksel ter-mask) atau tanpa class_idx dibuang sebelum dikirim balik
    sebagai FeatureCollection literal."""
    from app.services.land_cover_service import FEATURE_NAMES

    good = {n: 0.2 for n in FEATURE_NAMES} | {"class_idx": 1, "system:index": "x"}
    masked = {n: 0.2 for n in FEATURE_NAMES} | {"class_idx": 2, "ndvi": None}
    no_cls = {n: 0.2 for n in FEATURE_NAMES}
    other = {n: 0.3 for n in FEATURE_NAMES} | {"class_idx": 3}
    samples = _FakeGetInfo(
        {"features": [{"properties": p} for p in (good, masked, no_cls, other)]}
    )
    svc = _svc()
    rows, fc = svc._materialize_samples(_FakeEE(), samples)
    assert len(rows) == 2
    assert "system:index" not in rows[0]
    assert isinstance(fc, _FakeFC)
    assert svc._distinct_class_count(rows) == 2


def test_train_buffer_constant_is_sane() -> None:
    # sample latih diambil dari bbox poligon + buffer supaya RF melihat >1 kelas
    assert TRAIN_BUFFER_M >= 1000


def test_analyze_polygon_samples_training_from_buffered_region(monkeypatch) -> None:
    """Titik latih & citra fitur harus dibangun untuk region ber-buffer
    (bukan poligon mentah), tapi ekstraksi luas/geometri tetap di poligon."""
    svc = _svc()
    store = _FakeStore(_TARGET)
    svc.postgres_store = store
    monkeypatch.setattr(svc, "_ensure_ee", lambda: _FakeEE())

    seen: dict[str, list] = {"feat": [], "pts": []}
    real_feat = svc._year_feature_image
    real_pts = svc._year_training_points

    def spy_feat(ee, roi, year, region=None):
        seen["feat"].append(region)
        return real_feat(ee, roi, year, region=region)

    def spy_pts(ee, roi, feat_img, year, region=None):
        seen["pts"].append(region)
        return real_pts(ee, roi, feat_img, year, region=region)

    monkeypatch.setattr(svc, "_year_feature_image", spy_feat)
    monkeypatch.setattr(svc, "_year_training_points", spy_pts)

    svc.analyze_polygon(287785)

    assert len(seen["feat"]) == len(YEARS)
    assert len(seen["pts"]) == len(YEARS)
    assert all(r is not None for r in seen["feat"])
    assert all(r is not None for r in seen["pts"])


def test_analyze_polygon_falls_back_to_dynamic_world_when_single_training_class(
    monkeypatch,
) -> None:
    """Poligon homogen: sample latih < 2 kelas -> RF di-skip, klasifikasi
    pakai Dynamic World langsung. Hasil tetap 5 tahun x 5 kelas tersimpan,
    tanpa metrik RF."""
    svc = _svc()
    store = _FakeStore(_TARGET)
    svc.postgres_store = store
    monkeypatch.setattr(svc, "_ensure_ee", lambda: _FakeEE())
    monkeypatch.setattr(svc, "_distinct_class_count", lambda *a, **k: 1)

    rf_calls: list = []
    monkeypatch.setattr(
        _FakeEE,
        "Classifier",
        type(
            "C",
            (),
            {
                "smileRandomForest": staticmethod(
                    lambda *a, **k: (rf_calls.append(1), _FakeClassifier())[1]
                )
            },
        ),
    )

    result = svc.analyze_polygon(287785)

    assert rf_calls == []  # RF tidak pernah dilatih
    assert result["oob_accuracy"] is None
    assert store.saved["model_trees"] == 0
    assert store.saved["n_training"] == 0
    assert len(store.saved["year_class_rows"]) == len(YEARS) * 5
    assert len(store.saved["year_geom_rows"]) == len(YEARS) * 5
    assert 287785 not in _LAND_COVER_RUN_STATE


def test_year_evaluate_retries_vectors_at_coarser_scale_on_gee_memory_limit() -> None:
    """GEE "User memory limit exceeded" pada vektorisasi 10 m -> ulang sekali
    dengan VECTOR_FALLBACK_SCALE (20 m); error lain tetap dilempar apa adanya."""
    from app.services.land_cover_service import VECTOR_FALLBACK_SCALE

    calls: list[int] = []

    class _Img(_FakeImg):
        def reduceToVectors(self, *a, **k):
            calls.append(k["scale"])
            if k["scale"] == 10:
                return _FakeGetInfo(_Boom("User memory limit exceeded."))
            return _FakeGetInfo({"features": []})

    class _Boom:
        def __init__(self, msg):
            self.msg = msg


    def _dict(d):
        out = {}
        for key, v in d.items():
            val = v.getInfo()
            if isinstance(val, _Boom):
                raise RuntimeError(val.msg)
            out[key] = val
        return _FakeGetInfo(out)

    ee = _FakeEE()
    ee.Dictionary = staticmethod(_dict)
    svc = _svc()
    areas, vectors = svc._year_evaluate(ee, _FakeImg(), _Img())
    assert calls == [10, VECTOR_FALLBACK_SCALE]
    assert areas["groups"]
    assert vectors == {"features": []}

    class _Other(_FakeImg):
        def reduceToVectors(self, *a, **k):
            return _FakeGetInfo(_Boom("Computation timed out."))

    with pytest.raises(RuntimeError, match="timed out"):
        svc._year_evaluate(ee, _FakeImg(), _Other())
