"""HTTP API + web GUI of the follow-up potential tool.

    python -m followup.server [--store ~/data/alces_followup] [--port 8790]
    -> http://127.0.0.1:8790/            GUI
       GET  /api/meta                    classes, surveys, bands, survey time span, site presets
       POST /api/run   (JSON = engine.Query fields)  -> counts, nightly series, distributions
"""
from __future__ import annotations

import argparse
from dataclasses import fields
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import engine
from .sites import SITES

HERE = Path(__file__).resolve().parent

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
    fold_years: bool = False
    fold_year_list: list[int] | None = None


@app.get("/api/meta")
def meta():
    cat = engine.catalog(str(STORE["path"]))
    ent = cat["entries"]
    classes = sorted({e["class"] for e in ent.values()}, key=lambda c: CLASS_ORDER.index(c)
                     if c in CLASS_ORDER else 99)
    lo = min(e["t_fd_range"][0] for e in ent.values())
    hi = max(e["t_fd_range"][1] for e in ent.values())
    return {"classes": classes, "surveys": sorted({e["survey"] for e in ent.values()}, reverse=True),
            "bands": cat["bands"], "n_days": cat["n_days"], "k0": cat.get("k0", 0), "mjd_range": [lo, hi],
            "source": cat.get("source", "native-rate sweeps"),
            "entries": {k: {kk: v.get(kk) for kk in ("class", "survey", "n_sim", "N_det_10yr", "z_range")}
                        for k, v in ent.items()},
            "sites": [{"region": r, "name": n, "lat": la, "lon": lo, "height": h} for r, n, la, lo, h in SITES],
            "galactic_plane": galactic_plane()}


CLASS_ORDER = ["SNIa", "SNIa-91bg", "SNIax", "SNII", "SNIIn", "SNIbc", "SLSN-I", "TDE", "KN-Bulla19", "KN-K17",
               "ILOT", "CaRT", "PISN-MOSFIT", "PISN-He", "PISN-H"]


class ObjectRequest(RunRequest):
    cls: str
    survey: str
    idx: int = Field(ge=0)
    shift: float = 0.0


class NightRequest(ObjectRequest):
    mjd: float                               # any time inside the night (local noon to noon)


@app.post("/api/night")
def api_night(req: NightRequest):
    """One event during one night: model magnitudes, airmass, Sun altitude and the followable intervals."""
    q = engine.Query(**{f.name: getattr(req, f.name) for f in fields(engine.Query)})
    if q.lon > 180:
        q.lon -= 360
    try:
        return engine.night_detail(q, req.cls, req.survey, req.idx, req.shift, req.mjd, STORE["path"])
    except (ValueError, FileNotFoundError, KeyError, IndexError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/object")
def api_object(req: ObjectRequest):
    """Model light curve, Rubin photometry and visibility windows of one simulated event."""
    q = engine.Query(**{f.name: getattr(req, f.name) for f in fields(engine.Query)})
    if q.lon > 180:
        q.lon -= 360
    try:
        return engine.object_detail(q, req.cls, req.survey, req.idx, req.shift, STORE["path"])
    except (ValueError, FileNotFoundError, KeyError) as e:
        raise HTTPException(400, str(e))


@lru_cache(maxsize=1)
def galactic_plane():
    from astropy import units as u
    from astropy.coordinates import SkyCoord
    import numpy as np
    c = SkyCoord(l=np.arange(0, 361, 2.0) * u.deg, b=np.zeros(181) * u.deg, frame="galactic").icrs
    return {"ra": np.round(c.ra.deg, 3).tolist(), "dec": np.round(c.dec.deg, 3).tolist()}


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
