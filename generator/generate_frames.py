"""
ONOFRE Viewer — Generació de frames per al viewer web
=======================================================
Es crida al final del pipeline ONOFRE (cell 4 → Finestra_IF / tipus de
piroconvecció; cell 6 → ROS/FLI), un cop tens els arrays ja calculats
per a tots els timesteps del run.

Per cada variable:
  - reprojecta cada timestep de EPSG:4326 (graella ICON-EU) a EPSG:3857
  - exporta un PNG amb fons transparent (NaN → alpha=0)
  - escriu manifest.json amb els bounds (EPSG:4326, pel L.imageOverlay de Leaflet)
  - genera el mosaic PNG (tots els passos, reutilitzant plot_time_mosaic_gridspec)
  - genera el GIF animat a partir dels mateixos frames

Estructura de sortida:
  output/<var_id>/<run_tag>/
      frames/f000.png, f001.png, ...
      manifest.json
      mosaic.png
      animation.gif
"""

import json
import shutil
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import BoundaryNorm, ListedColormap
from PIL import Image
import imageio.v2 as imageio
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.transform import from_bounds
from rasterio.crs import CRS

# ──────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓ DE VARIABLES
# ──────────────────────────────────────────────────────────────────────────
# domain: "europe" -> extent ICON-EU sencer / "catalunya" -> només CAT
# cmap / norm: reutilitzen els mateixos objectes que ja tens definits al
# notebook (cmap_complexitat/norm_complexitat, colors_grad/norm_piroconveccio).
# Per ROS/FLI encara no tens colormap definit al notebook que m'has passat:
# hi poso un placeholder (YlOrRd continu) — canvia'l pel que facis servir tu.

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
        domain="europe",
        cmap=cmap_complexitat,
        norm=norm_complexitat,
        legend_labels=["0", "1", "2", "3", "4", "5", "6"],
    ),
    "piroconveccio": dict(
        title="Tipus de piroconvecció",
        domain="europe",
        cmap=cmap_piroc,
        norm=norm_piroc,
        legend_labels=["1 - c", "2 - opyroCu", "3 - pyroCu", "4 - pyroCb"],
    ),
    "ros_fli": dict(
        title="ROS (Rothermel)",
        domain="catalunya",
        cmap=cmap_ros,
        norm=norm_ros,
        legend_labels=[f"{v} km/h" for v in ros_bounds],
    ),
}

OUTPUT_ROOT = Path("/home/pguarque/onofre-viewer/frontend/data")


# ──────────────────────────────────────────────────────────────────────────
# REPROJECCIÓ EPSG:4326 → EPSG:3857 + PNG amb transparència
# ──────────────────────────────────────────────────────────────────────────
def _extent_for(domain):
    return EXTENT_EUROPE if domain == "europe" else EXTENT_CATALUNYA


def reproject_to_webmercator(data, lon, lat):
    """
    data: array 2D (lat, lon), amb NaN on no hi ha dada.
    lon, lat: vectors 1D (graella regular EPSG:4326).
    Retorna (array_3857, bounds_3857).
    """
    data = np.asarray(data, dtype="float64")
    src_crs = CRS.from_epsg(4326)
    dst_crs = CRS.from_epsg(3857)

    src_transform = from_bounds(
        lon.min(), lat.min(), lon.max(), lat.max(),
        len(lon), len(lat)
    )

    dst_transform, width, height = calculate_default_transform(
        src_crs, dst_crs, len(lon), len(lat),
        lon.min(), lat.min(), lon.max(), lat.max()
    )

    dst = np.full((height, width), np.nan, dtype="float64")

    # cal invertir l'eix lat si ve ordenat de sud a nord (rasterio espera nord->sud)
    if lat[0] < lat[-1]:
        data = data[::-1, :]

    reproject(
        source=data,
        destination=dst,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs=dst_crs,
        resampling=Resampling.nearest,
        src_nodata=np.nan,
        dst_nodata=np.nan,
    )

    bounds_3857 = rasterio.transform.array_bounds(height, width, dst_transform)
    return dst, bounds_3857  # (left, bottom, right, top) en EPSG:3857


def bounds_3857_to_4326(bounds_3857):
    from pyproj import Transformer
    transformer = Transformer.from_crs(3857, 4326, always_xy=True)
    left, bottom, right, top = bounds_3857
    lon_min, lat_min = transformer.transform(left, bottom)
    lon_max, lat_max = transformer.transform(right, top)
    return [[lat_min, lon_min], [lat_max, lon_max]]  # format L.imageOverlay bounds


def array_to_rgba_png(data_3857, cmap, norm, path):
    """Converteix l'array reprojectat a PNG RGBA (alpha=0 on NaN)."""
    if norm is not None:
        normed = norm(data_3857)
    else:
        vmin = np.nanmin(data_3857)
        vmax = np.nanmax(data_3857)
        normed = (data_3857 - vmin) / (vmax - vmin + 1e-12)

    rgba = cmap(normed, bytes=True)  # (H, W, 4) uint8
    alpha = np.where(np.isnan(data_3857), 0, 255).astype("uint8")
    rgba[..., 3] = alpha

    Image.fromarray(rgba, mode="RGBA").save(path)


# ──────────────────────────────────────────────────────────────────────────
# PIPELINE PER VARIABLE
# ──────────────────────────────────────────────────────────────────────────
def generate_variable(var_id, data_list, lon, lat, times, run_tag,
                       mosaic_fn=None, mosaic_kwargs=None, mosaic_fig=None):
    """
    data_list : llista d'arrays 2D, un per timestep (sortida de
                calculate_Finestra_IF+finestra_reclass, tipus_piroconveccio,
                o ROS/FLI, ja calculats al notebook).
    lon, lat  : vectors 1D EPSG:4326 de la graella d'origen.
    times     : llista de pd.Timestamp / datetime, mateixa llargada que data_list.
    run_tag   : p.ex. "20260720_00"
    mosaic_fn : (opcional) funció amb signatura
                mosaic_fn(data_list, lon, lat, times, title=..., cmap=..., norm=..., **mosaic_kwargs)
                — encaixa directament amb plot_time_mosaic_gridspec.
    mosaic_fig: (opcional) una figura matplotlib ja generada (p. ex. amb
                plot_ROS_gridspec_ICONEU, que té una signatura diferent i no
                encaixa amb mosaic_fn). Si es passa, es fa servir tal qual i
                s'ignora mosaic_fn.
    """
    cfg = VARIABLES[var_id]
    out_dir = OUTPUT_ROOT / var_id / run_tag
    frames_dir = out_dir / "frames"
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "variable": var_id,
        "title": cfg["title"],
        "domain": cfg["domain"],
        "run": run_tag,
        "legend_labels": cfg["legend_labels"],
        "frames": [],
    }

    frame_paths_for_gif = []

    for i, (data, t) in enumerate(zip(data_list, times)):
        data_3857, bounds_3857 = reproject_to_webmercator(data, lon, lat)
        bounds_4326 = bounds_3857_to_4326(bounds_3857)

        frame_name = f"f{i:03d}.png"
        frame_path = frames_dir / frame_name
        array_to_rgba_png(data_3857, cfg["cmap"], cfg["norm"], frame_path)

        manifest["frames"].append({
            "file": f"frames/{frame_name}",
            "time": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "bounds": bounds_4326,
        })
        frame_paths_for_gif.append(frame_path)

    with open(out_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    # ── GIF (mateixos frames, sobre fons blanc perquè es vegi bé fora de Leaflet) ──
    gif_frames = []
    for p in frame_paths_for_gif:
        im = Image.open(p).convert("RGBA")
        bg = Image.new("RGBA", im.size, "white")
        bg.paste(im, mask=im.split()[3])
        gif_frames.append(np.array(bg.convert("RGB")))
    imageio.mimsave(out_dir / "animation.gif", gif_frames, duration=0.5, loop=0)

    # ── Mosaic "tal i com surt al codi" (reutilitza la teva funció existent) ──
    if mosaic_fig is not None:
        # figura ja generada externament (p. ex. plot_ROS_gridspec_ICONEU,
        # que rep ds_out directament i no encaixa amb la signatura de mosaic_fn)
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

    print(f"[{var_id}] {len(data_list)} frames → {out_dir}")

    # ── Publica com a "latest" (el frontend llegeix RUN_TAG="latest") ──
    latest_dir = OUTPUT_ROOT / var_id / "latest"
    if latest_dir.exists():
        shutil.rmtree(latest_dir)
    shutil.copytree(out_dir, latest_dir)
    print(f"[{var_id}] publicat com a 'latest' → {latest_dir}")

    return out_dir


# ──────────────────────────────────────────────────────────────────────────
# EXEMPLE D'ÚS (al final del teu notebook, un cop tens els arrays calculats)
# ──────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(
        "Aquest script no s'executa sol: importa `generate_variable` al teu "
        "notebook/pipeline un cop tinguis `data_list`, `lon`, `lat`, `times` "
        "per a cada variable, p.ex.:\n\n"
        "  from generate_frames import generate_variable, VARIABLES\n"
        "  generate_variable('complexitat', finestra_list, new_lon.values, "
        "new_lat.values, list(ds_surf.time.values), run_tag,\n"
        "                    mosaic_fn=plot_time_mosaic_gridspec)\n"
    )
