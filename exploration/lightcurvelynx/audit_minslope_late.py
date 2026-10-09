"""
Fase 99: auditoria de MINSLOPE_EXTRAPMAG_LATE (0.1 mag/dia en los .INPUT
reales de KN-K17, KN-BULLA19 y BULLA-BNS-M2-2COMP).

SNANA extrapola mas alla del ultimo dia del template con una caida de al
menos 0.1 mag/dia; LightCurveLynx devuelve flujo 0 fuera del rango del
template. La diferencia solo puede importar si el template sigue siendo
detectable en su ULTIMA fase: despues de eso SNANA solo puede ser mas debil.

Esta auditoria mide, para cada template, la magnitud en su ultima fase en la
mejor banda (g/r/i/z/y), y la lleva al caso mas favorable del catalogo:
z_min de la clase (0.011, mu ~ 33.4). Si incluso ahi queda muy por debajo
del limite de una visita LSST (~24-25), implementar la extrapolacion no
cambia ninguna deteccion. Sin k-correccion (a z=0.011 es despreciable).

Uso (NLHPC, SLURM):  python3 audit_minslope_late.py
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from kn_confusion_diag import load_passbands, read_simsed_info, template_lightcurves

BANDS_RED = ["g", "r", "i", "z", "y"]
CLASSES = ["KN-K17", "KN-BULLA19"]  # BULLA-BNS-M2-2COMP usa la misma grilla fisica que KN-BULLA19


def _last_phase(args):
    path, flux_scale, passbands = args
    phase, mags = template_lightcurves(path, flux_scale, passbands)
    m_last = min((mags[b][-1] for b in BANDS_RED if np.isfinite(mags[b][-1])), default=np.nan)
    m_peak = min((np.nanmin(mags[b]) for b in BANDS_RED if np.isfinite(mags[b]).any()), default=np.nan)
    return float(phase[-1]), m_last, m_peak


def main() -> None:
    from astropy.cosmology import FlatLambdaCDM
    from run_simsed_poc import CLASS_CONFIGS

    passbands = load_passbands()
    cosmo = FlatLambdaCDM(H0=70, Om0=0.3)
    for cls in CLASSES:
        cfg = CLASS_CONFIGS[cls]
        z_min = cfg["genrange_redshift"][0]
        mu = float(cosmo.distmod(z_min).value)
        d = Path(cfg["simsed_dir"])
        files, _, _, flux_scale = read_simsed_info(d)
        with ProcessPoolExecutor(max_workers=4) as ex:
            res = list(ex.map(_last_phase, [(d / f, flux_scale, passbands) for f in files], chunksize=4))
        last_phase = np.array([r[0] for r in res])
        m_last = np.array([r[1] for r in res])
        m_peak = np.array([r[2] for r in res])
        app = m_last + mu
        # templates sin flujo en la ultima fase (M mas debil que el corte) -> NaN: ya son 0
        fin = np.isfinite(app)
        print(f"{cls}: {len(files)} templates, z_min={z_min} (mu={mu:.2f}); ultima fase "
              f"{last_phase.min():.1f}-{last_phase.max():.1f} d")
        print(f"  con flujo en la ultima fase: {fin.sum()}/{len(files)}")
        if fin.any():
            print(f"  m aparente en la ultima fase a z_min: mas brillante {np.nanmin(app):.2f}, "
                  f"mediana {np.nanmedian(app):.2f}")
            print(f"  caida pico -> ultima fase (mag): minima {np.nanmin(m_last - m_peak):.2f}, "
                  f"mediana {np.nanmedian(m_last - m_peak):.2f}")
            for lim in (24.5, 26.0):
                print(f"  templates mas brillantes que {lim} en la ultima fase a z_min: {(app < lim).sum()}")
        # Fraccion de la POBLACION generada (dndz real de la clase, templates con
        # peso uniforme) cuyo template sigue sobre el limite en su ultima fase:
        # solo esos eventos pueden tener una cola tardia distinta en SNANA.
        z_lo, z_hi = cfg["genrange_redshift"]
        zg = np.linspace(z_lo, z_hi, 2001)
        dndz = cosmo.differential_comoving_volume(zg).value / (1 + zg)  # tasa constante (powerlaw beta=0)
        cdf = np.concatenate([[0], np.cumsum(0.5 * (dndz[1:] + dndz[:-1]) * np.diff(zg))])
        cdf /= cdf[-1]
        mu_g = cosmo.distmod(zg).value
        for lim in (24.5, 26.0):
            frac = []
            for ml in m_last:
                if not np.isfinite(ml):
                    frac.append(0.0)
                    continue
                ok = ml + mu_g < lim
                frac.append(float(cdf[np.nonzero(ok)[0][-1]]) if ok.any() else 0.0)
            print(f"  fraccion de la poblacion con la ultima fase mas brillante que {lim}: "
                  f"{100 * np.mean(frac):.2f}%")


if __name__ == "__main__":
    main()
