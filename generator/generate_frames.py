"""
ONOFRE Viewer — Generació de dades pel viewer web
=====================================================
Es crida al final del pipeline ONOFRE (cell 4 → Finestra_IF / tipus de
piroconvecció; cell 6 → ROS/FLI), un cop tens els arrays ja calculats
per a tots els timesteps del run.

Canvi de disseny respecte a la primera versió: en comptes de reprojectar
i exportar un PNG per timestep, exportem la graella de valors en cru
(JSON, quantitzat) i és el navegador qui la dibuixa amb <canvas>, cel·la
a cel·la, fent servir la projecció pròpia de Leaflet. Avantatges:
  - Sempre nítid, a qualsevol zoom (cada cel·la = un rectangle exacte).
  - El retall per costa surt "gratis": les cel·les fora de terra (NaN)
    simplement no es dibuixen — no cal reprojectar cap imatge.
  - No calen rasterio/pyproj al backend per aquesta part.

Per cada variable:
  - emmascara (opcional) amb build_land_mask + apply_polygon_mask
  - quantitza els valors (arrodonits, NaN → null) i escriu manifest.json
    amb: lon, lat (graella), color_bins (paleta ja convertida a hex),
    i els frames (values 2D per timestep)
  - genera també el mosaic.png / animation.gif "oficials" (matplotlib,
    fixos, reutilitzant les teves funcions de plot tal qual — això no
    canvia, són una referència estàtica, no cal que siguin "zoomables")

Estructura de sortida:
  output/<var_id>/<run_tag>/
      manifest.json   (lon, lat, color_bins, frames[].values)
      mosaic.png
      animation.gif
"""

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap

# ──────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓ DE VARIABLES
# ──────────────────────────────────────────────────────────────────────────
EXTENT_EUROPE    = dict(lon_min=-23.5, lon_max=62.375, lat_min=29.5, lat_max=70.375)
EXTENT_CATALUNYA = dict(lon_min=0.0,   lon_max=3.5,    lat_min=40.375, lat_max=43.0)

Finestra_palet = ['white', 'xkcd:light beige', 'xkcd:yellow', 'gold',
                   'darkorange', 'red', 'darkred']
cmap_complexitat = ListedColormap(Finestra_palet)
norm_complexitat = BoundaryNorm([0, 1, 2, 3, 4, 5, 6, 7], ncolors=cmap_complexitat.N, clip=True)

colors_piroc     = ['darkred', 'gold', 'yellow', 'lightgreen']
cmap_piroc       = ListedColormap(colors_piroc)
norm_piroc       = BoundaryNorm([0.5, 1.5, 2.5, 3.5, 4.5], ncolors=cmap_piroc.N, clip=True)

# ROS: mateix colormap/llindars que ja fas servir a plot_ROS_gridspec_ICONEU
ros_bounds = [0, 0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0]
cmap_ros   = plt.cm.afmhot_r
norm_ros   = BoundaryNorm(ros_bounds, cmap_ros.N)

VARIABLES = {
    "complexitat": dict(
        title="Finestra IF — Complexitat",
        domain="catalunya",  # el pipeline actual retalla a CAT a la cel·la 2, abans de calcular-ho
        domain_note="Cobertura Catalunya (el pipeline actual retalla el domini abans de calcular-ho; tècnicament podria ampliar-se a tot ICON-EU).",
        cmap=cmap_complexitat,
        norm=norm_complexitat,
        legend_labels=["0", "1", "2", "3", "4", "5", "6"],
        decimals=0,
        transparent_zero=True,  # el 0 (sense activitat) no es dibuixa, es veu el mapa de sota
    ),
    "piroconveccio": dict(
        title="Tipus de piroconvecció",
        domain="catalunya",
        domain_note="Cobertura Catalunya (el pipeline actual retalla el domini abans de calcular-ho; tècnicament podria ampliar-se a tot ICON-EU).",
        cmap=cmap_piroc,
        norm=norm_piroc,
        legend_labels=["1 - c", "2 - opyroCu", "3 - pyroCu", "4 - pyroCb"],
        decimals=0,
    ),
    "ros_fli": dict(
        title="ROS (Rothermel)",
        domain="catalunya",
        domain_note="Cobertura Catalunya (humitat de combustible calculada només amb estacions SMC catalanes).",
        cmap=cmap_ros,
        norm=norm_ros,
        legend_labels=[f"{v} km/h" for v in ros_bounds],
        decimals=1,
    ),
}

OUTPUT_ROOT = Path("/home/pguarque/onofre-viewer/docs/data")


# ──────────────────────────────────────────────────────────────────────────
# MÀSCARA TERRA/MAR (Natural Earth via cartopy) — vàlida a qualsevol domini
# ──────────────────────────────────────────────────────────────────────────
def build_polygon_mask(lon, lat, geoms):
    """
    Retorna un array booleà (len(lat), len(lon)), True dins del polígon.
    geoms: geometries shapely en EPSG:4326 (comarques, land Natural Earth, etc.)
    """
    from rasterio.features import geometry_mask
    from rasterio.transform import from_origin

    res_lon = float(lon[1] - lon[0])
    res_lat = float(lat[1] - lat[0])
    transform = from_origin(
        lon.min() - res_lon / 2,
        lat.max() + abs(res_lat) / 2,
        res_lon, abs(res_lat)
    )
    mask_outside = geometry_mask(
        geoms, out_shape=(len(lat), len(lon)),
        transform=transform, invert=False,  # True = FORA del polígon
        all_touched=True,  # una cel·la compta com a "dins" si el polígon la
                            # toca en qualsevol part, no només pel centre —
                            # evita perdre cel·les de costa que són majoritàriament terra
    )
    if lat[0] < lat[-1]:
        mask_outside = mask_outside[::-1, :]
    return ~mask_outside  # True = DINS del polígon


_land_geoms_cache = {}

def build_land_mask(lon, lat, resolution="10m"):
    """
    Màscara terra/mar a partir de Natural Earth (via cartopy), no d'un
    shapefile administratiu concret — vàlida tant per Catalunya com per
    tot Europa si algun dia s'amplia el domini del pipeline.

    resolution: "10m" (molt detallat, més lent), "50m" (bon compromís),
    "110m" (ràpid, poc detall de costa).
    """
    import cartopy.io.shapereader as shpreader

    if resolution not in _land_geoms_cache:
        land_shp = shpreader.natural_earth(
            resolution=resolution, category="physical", name="land"
        )
        _land_geoms_cache[resolution] = list(shpreader.Reader(land_shp).geometries())

    return build_polygon_mask(lon, lat, _land_geoms_cache[resolution])


def apply_polygon_mask(data_list, inside_mask):
    """Posa NaN fora del polígon a cada frame de data_list (còpia, no in-place)."""
    out = []
    for arr in data_list:
        arr = np.asarray(arr, dtype="float64").copy()
        arr[~inside_mask] = np.nan
        out.append(arr)
    return out


# ──────────────────────────────────────────────────────────────────────────
# PALETA → BINS HEX (perquè el navegador pugui pintar sense matplotlib)
# ──────────────────────────────────────────────────────────────────────────
def _rgb_to_hex(rgba):
    r, g, b = [int(round(c * 255)) for c in rgba[:3]]
    return f"#{r:02x}{g:02x}{b:02x}"


def cmap_to_bins(cmap, norm):
    """
    Converteix un cmap+BoundaryNorm en una llista de bins [{max, color}]
    ordenats ascendentment. El client aplica: primer bin amb valor <= max
    (si el valor supera tots els max, s'aplica l'últim bin).
    Funciona tant per ListedColormap (bins exactes) com per cmaps
    continus com afmhot_r (avalua cmap(norm(valor_representatiu))).
    """
    boundaries = list(norm.boundaries)
    bins = []
    for i in range(len(boundaries) - 1):
        lo, hi = boundaries[i], boundaries[i + 1]
        mid = (lo + hi) / 2
        rgba = cmap(norm(mid))
        bins.append({"max": float(hi), "color": _rgb_to_hex(rgba)})
    return bins


# ──────────────────────────────────────────────────────────────────────────
# QUANTITZACIÓ DE LA GRAELLA (NaN → null, arrodonit a `decimals`)
# ──────────────────────────────────────────────────────────────────────────
def _quantize_grid(arr, decimals):
    arr = np.asarray(arr, dtype="float64")
    rounded = np.round(arr, decimals)
    if decimals <= 0:
        vals = np.where(np.isnan(rounded), None, rounded.astype(object))
        return [[None if v is None or (isinstance(v, float) and np.isnan(v)) else int(v)
                 for v in row] for row in rounded]
    return [[None if np.isnan(v) else round(float(v), decimals) for v in row]
            for row in rounded]


# ──────────────────────────────────────────────────────────────────────────
# PIPELINE PER VARIABLE
# ──────────────────────────────────────────────────────────────────────────
def generate_variable(var_id, data_list, lon, lat, times, run_tag,
                       mosaic_fn=None, mosaic_kwargs=None, mosaic_fig=None):
    """
    data_list : llista d'arrays 2D, un per timestep (ja emmascarats amb
                apply_polygon_mask si vols retall per costa).
    lon, lat  : vectors 1D EPSG:4326 de la graella d'origen.
    times     : llista de pd.Timestamp / datetime, mateixa llargada que data_list.
    run_tag   : p.ex. "20260720_00"
    mosaic_fn / mosaic_kwargs / mosaic_fig : igual que abans, per generar
                el PNG "oficial" (estàtic, no zoomable) reutilitzant les
                teves funcions de plot existents.
    """
    cfg = VARIABLES[var_id]
    out_dir = OUTPUT_ROOT / var_id / run_tag
    out_dir.mkdir(parents=True, exist_ok=True)

    decimals = cfg.get("decimals", 1)
    frames = []
    for arr, t in zip(data_list, times):
        frames.append({
            "time": pd.Timestamp(t).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "values": _quantize_grid(arr, decimals),
        })

    manifest = {
        "variable": var_id,
        "title": cfg["title"],
        "domain": cfg["domain"],
        "domain_note": cfg.get("domain_note"),
        "transparent_zero": cfg.get("transparent_zero", False),
        "run": run_tag,
        "legend_labels": cfg["legend_labels"],
        "color_bins": cmap_to_bins(cfg["cmap"], cfg["norm"]),
        "lon": [round(float(v), 5) for v in lon],
        "lat": [round(float(v), 5) for v in lat],
        "frames": frames,
    }

    with open(out_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, separators=(",", ":"))  # compacte, sense espais

    # ── Mosaic/GIF "oficials" (estàtics, referència fixa) ──────────────────
    if mosaic_fig is not None:
        mosaic_fig.savefig(out_dir / "mosaic.png", bbox_inches="tight", dpi=300, pad_inches=0.12)
    elif mosaic_fn is not None:
        fig = mosaic_fn(
            data_list, lon, lat, times,
            title=cfg["title"],
            cmap=cfg["cmap"], norm=cfg["norm"],
            **(mosaic_kwargs or {}),
        )
        fig.savefig(out_dir / "mosaic.png", bbox_inches="tight", dpi=300, pad_inches=0.12)
        plt.close(fig)

    print(f"[{var_id}] {len(data_list)} frames (JSON) → {out_dir}")

    # ── Publica com a "latest" (el frontend llegeix RUN_TAG="latest") ──
    latest_dir = OUTPUT_ROOT / var_id / "latest"
    if latest_dir.exists():
        shutil.rmtree(latest_dir)
    shutil.copytree(out_dir, latest_dir)
    print(f"[{var_id}] publicat com a 'latest' → {latest_dir}")

    return out_dir


if __name__ == "__main__":
    print(
        "Aquest script no s'executa sol: importa `generate_variable` (i, si "
        "vols retall per costa, `build_land_mask`/`apply_polygon_mask`) al "
        "teu notebook un cop tinguis `data_list`, `lon`, `lat`, `times`."
    )
