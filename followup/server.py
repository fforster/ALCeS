"""HTTP API + web GUI of the follow-up potential tool.

    python -m followup.server [--store ~/data/alces_followup] [--port 8790]
    -> http://127.0.0.1:8790/            GUI
       GET  /api/meta                    classes, surveys, bands, survey time span, site presets
       POST /api/run   (JSON = engine.Query fields)  -> counts, nightly series, distributions
"""
from __future__ import annotations

import argparse
from dataclasses import fields
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import engine

HERE = Path(__file__).resolve().parent
SITES = {
    "Cerro Pachón (Rubin, SOAR, Gemini-S)": (-30.2446, -70.7494, 2700),
    "Cerro Tololo (CTIO)": (-30.1690, -70.8063, 2207),
    "La Silla (ESO)": (-29.2567, -70.7300, 2400),
    "Paranal (VLT)": (-24.6272, -70.4042, 2635),
    "Las Campanas (Magellan)": (-29.0146, -70.6926, 2380),
    "SAAO Sutherland (SALT)": (-32.3794, 20.8107, 1798),
    "Siding Spring (AAT)": (-31.2733, 149.0617, 1164),
    "Mauna Kea (Keck, Subaru, Gemini-N)": (19.8260, -155.4747, 4160),
    "Roque de los Muchachos (GTC, NOT, LT)": (28.7606, -17.8816, 2396),
    "Kitt Peak (KPNO)": (31.9583, -111.5967, 2096),
    "Palomar (ZTF)": (33.3563, -116.8650, 1712),
    "Calar Alto": (37.2236, -2.5463, 2168),
    "Devasthal (India)": (29.3610, 79.6850, 2450),
    "Xinglong (China)": (40.3958, 117.5775, 960),
}

app = FastAPI(title="ALCeS follow-up potential")
STORE = {"path": engine.STORE}


class RunRequest(BaseModel):
    lat: float = Field(-30.2446, ge=-90, le=90)
    lon: float = Field(-70.7494, ge=-180, le=360)
    height: float = 2700.0
    classes: list[str] = ["SNIa", "SNII"]
    surveys: list[str] = ["WFD"]
    band: str = "r"
    mag_lim: float = Field(20.0, ge=5, le=30)
    airmass_max: float = Field(2.0, ge=1.0, le=10)
    t_min: float = Field(0.0, ge=0)
    t_max: float = Field(30.0, gt=0)
    mjd_start: float = 61400.0
    mjd_end: float = 61765.0
    step_min: float = Field(15.0, ge=1, le=240)
    sun_alt: float = Field(-18.0, ge=-30, le=0)
    fold_years: bool = True


@app.get("/api/meta")
def meta():
    cat = engine.catalog(str(STORE["path"]))
    ent = cat["entries"]
    classes = sorted({e["class"] for e in ent.values()}, key=lambda c: list(engine_order()).index(c)
                     if c in engine_order() else 99)
    lo = min(e["t_fd_range"][0] for e in ent.values())
    hi = max(e["t_fd_range"][1] for e in ent.values())
    return {"classes": classes, "surveys": sorted({e["survey"] for e in ent.values()}, reverse=True),
            "bands": cat["bands"], "n_days": cat["n_days"], "mjd_range": [lo, hi],
            "entries": {k: {kk: v[kk] for kk in ("class", "survey", "n_sim", "N_det_10yr", "parts")}
                        for k, v in ent.items()},
            "sites": {k: {"lat": v[0], "lon": v[1], "height": v[2]} for k, v in SITES.items()}}


def engine_order():
    from .build import CLASSES
    return CLASSES


@app.post("/api/run")
def api_run(req: RunRequest):
    q = engine.Query(**{f.name: getattr(req, f.name) for f in fields(engine.Query)})
    if q.lon > 180:
        q.lon -= 360
    try:
        return engine.run(q, STORE["path"])
    except (ValueError, FileNotFoundError) as e:
        raise HTTPException(400, str(e))


@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/vendor/plotly.min.js")
def plotly_js():
    """plotly.js bundled with the plotly Python package: the GUI works without a CDN."""
    import plotly
    return FileResponse(Path(plotly.__file__).parent / "package_data" / "plotly.min.js",
                        media_type="text/javascript")


def main():
    import uvicorn
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", type=Path, default=engine.STORE)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8790)
    a = ap.parse_args()
    STORE["path"] = a.store.expanduser()
    uvicorn.run(app, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
