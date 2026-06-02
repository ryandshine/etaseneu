# ETA SEUNEU

Aplikasi pemantauan hotspot lokal berbasis FastAPI dan React/Vite untuk membaca layer GeoJSON dari folder `shp/`, memfilter hotspot aktif, menampilkan ringkasan, dan mengekspor hasil ke Excel.

## Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Frontend

Gunakan Node/npm dari path non-snap bila `npm` default bermasalah.

```bash
export PATH=/home/ryandshinevps/.nvm/versions/node/v24.15.0/bin:/home/ryandshinevps/.local/bin:$PATH
cd frontend
npm install
npm run dev
```

## URLs lokal

- Frontend: `http://localhost:5173`
- Backend: `http://localhost:8000`
- API health: `http://localhost:8000/api/health`

## Deploy Dokploy

File yang disiapkan untuk deployment publik:

- `docker-compose.dokploy.yml`
- `Dockerfile.api`
- `Dockerfile.web`
- `.env.dokploy.example`

Langkah ringkas:

1. Salin `.env.dokploy.example` menjadi `.env.dokploy` lalu isi `NASA_FIRMS_API_KEY`.
2. Deploy `docker-compose.dokploy.yml` di Dokploy.
3. Pastikan service `web` terhubung ke domain `etaseneu.ditpps.com`.

Stack ini dirancang untuk satu domain publik:

- `https://etaseneu.ditpps.com` → frontend
- `https://etaseneu.ditpps.com/api/*` → proxy ke FastAPI internal
