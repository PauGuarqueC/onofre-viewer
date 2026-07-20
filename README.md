# ONOFRE Viewer — pla d'implementació

Visor web amb slider temporal per a les 3 sortides del pipeline ONOFRE:
**Complexitat (Finestra IF)**, **Tipus de piroconvecció** (Europa, des d'ICON-EU)
i **ROS/FLI** (Catalunya, requereix humitat de combustible de les estacions SMC).

## Arquitectura (mateix patró que l'echotops-viewer, repo separat)

```
labfire.ctfc.cat (cron, després del run ONOFRE)
   └─ generate_frames.py
        ├─ reprojecta cada timestep EPSG:4326 → EPSG:3857
        ├─ exporta PNG amb transparència (frames/f000.png, f001.png...)
        ├─ escriu manifest.json (bounds EPSG:4326, per L.imageOverlay)
        ├─ genera mosaic.png (reutilitza plot_time_mosaic_gridspec)
        └─ genera animation.gif (mateixos frames, fons blanc)
   └─ git push → repo onofre-viewer (codi + dades al mateix repo)
        └─ GitHub Pages serveix index.html + data/ estàticament
```

## Com posar-ho en marxa (pas a pas)

### 1. Crea el repo a GitHub

```bash
# des del teu ordinador, o des de labfire.ctfc.cat si hi tens gh/git configurat
gh repo create PauGuarqueC/onofre-viewer --public --clone
cd onofre-viewer
```

Si no fas servir `gh`, crea el repo des de la web de GitHub (buit, sense README) i fes:

```bash
git clone https://github.com/PauGuarqueC/onofre-viewer.git
cd onofre-viewer
```

### 2. Puja l'esquelet

Copia dins del repo el contingut d'aquest paquet:

```
onofre-viewer/
├── frontend/
│   └── index.html          ← el visor
├── generator/
│   └── generate_frames.py  ← ja apunta a frontend/data com a OUTPUT_ROOT
├── publish.sh
└── README.md
```

```bash
git add .
git commit -m "Setup inicial onofre-viewer"
git push
```

### 3. Activa GitHub Pages

A la web del repo: **Settings → Pages → Source → Deploy from a branch →
`main` / carpeta `/frontend`**. Al cap d'uns segons tindràs el visor a
`https://pauguarquec.github.io/onofre-viewer/`.

### 4. Clona el repo al servidor (labfire.ctfc.cat)

```bash
cd /home/pguarque
git clone https://github.com/PauGuarqueC/onofre-viewer.git
```

`generate_frames.py` ja escriu directament a
`/home/pguarque/onofre-viewer/frontend/data/<var_id>/<run_tag>/` **i** a
`.../latest/` (còpia automàtica que fa el propi script perquè el frontend,
que llegeix `RUN_TAG = "latest"`, sempre trobi el run més recent).

### 5. Connecta't al notebook

Al notebook (`GRAF_2026_amb_export.ipynb`), les dues cel·les noves que hem
afegit ja fan `sys.path.insert(0, "/home/pguarque/onofre-viewer/generator")`
— comprova només que el path coincideix amb on has clonat el repo.

### 6. Prova-ho localment abans d'automatitzar-ho

```bash
cd /home/pguarque/onofre-viewer/frontend
python3 -m http.server 8000
# obre http://localhost:8000 (o fes port-forward via SSH si ho vols veure
# des del teu portàtil: ssh -L 8000:localhost:8000 -p 2222 pguarque@labfire.ctfc.cat)
```

Si els 3 selectors carreguen mapa i el slider es mou, ja tens el pipeline
sencer funcionant.

### 7. Automatitza-ho amb cron (mateix patró que l'echotops-viewer)

```bash
chmod +x /home/pguarque/onofre-viewer/publish.sh
crontab -e
```

```
# Un cop tinguis clar a quina hora acaba el run ICON-EU / ONOFRE:
15 6 * * * /home/pguarque/onofre-viewer/publish.sh >> /home/pguarque/onofre-viewer/publish.log 2>&1
```

`publish.sh` fa: `git pull` → executa el notebook amb `nbconvert --execute`
(el mateix `graf_env`) → `git add frontend/data` → commit + push. GitHub
Pages recull els canvis automàticament, sense cap altre pas.

### 2b. Afegeix `gif.js` (necessari pel botó "GIF" de la vista actual)

El GIF de la vista personalitzada es genera **al navegador**, amb la
llibreria [gif.js](https://github.com/jnordberg/gif.js). Cal que els fitxers
siguin del mateix origen que la pàgina (GitHub Pages), perquè els navegadors
bloquegen sovint la creació de Web Workers des d'un domini extern:

```bash
mkdir -p frontend/vendor
curl -L -o frontend/vendor/gif.js        https://raw.githubusercontent.com/jnordberg/gif.js/master/dist/gif.js
curl -L -o frontend/vendor/gif.worker.js https://raw.githubusercontent.com/jnordberg/gif.js/master/dist/gif.worker.js
git add frontend/vendor
```

## Descàrrega de la vista actual (zoom/retall a mida)

A banda del mapa "oficial" (extent fix, generat pel cron), el visor permet:

- **Retallar a la finestra visible**: qualsevol persona pot fer pan/zoom
  (p. ex. algú a Itàlia enquadrant la seva regió) i descarregar el mosaic o
  el GIF **només d'aquesta vista**, no del domini sencer.
- **Triar quants dies de pronòstic incloure** amb el slider "dies" — es
  filtren els frames del `manifest.json` per antiguitat respecte al primer
  timestep del run.

Això es fa **tot al navegador, sense servidor**: cada frame ja és una
imatge en Web Mercator amb uns bounds coneguts (el mateix domini per a
tots els timesteps d'una variable). El codi retalla el rectangle de píxels
que correspon a la intersecció entre el domini de la variable i la vista
actual del mapa (matemàtica de projecció Web Mercator, sense dependències
de geoprocessament), i compon el mosaic/GIF amb `<canvas>`.

**Limitació esperada**: si la variable és `ros_fli` (només Catalunya) i
algú fa zoom sobre Itàlia, la intersecció és buida i els botons de
descàrrega de la vista actual es desactiven automàticament, amb un avís.

## Coses a revisar / ajustar

1. **Connectar `generate_frames.py` amb el notebook real.**
   Al final de la cel·la 4 (Finestra_IF) i la cel·la 6 (ROS/FLI) hauries de
   tenir, per a cada timestep del run, un array 2D. Munta una llista
   `data_list` (un array per timestep) i crida:

   ```python
   from generate_frames import generate_variable

   generate_variable(
       "complexitat", finestra_list, new_lon.values, new_lat.values,
       list(pd.to_datetime(ds_surf.time.values)), run_tag,
       mosaic_fn=plot_time_mosaic_gridspec,
   )
   ```

   Repeteix per `piroconveccio` i `ros_fli`. Per `piroconveccio` i `ros_fli`
   necessitaràs acumular els resultats de `tipus_piroconveccio(...)` i del
   Rothermel/FLI per cada timestep en llistes, igual que ja fas per Finestra_IF.

2. **Colormap/llindars reals per ROS/FLI.** Al notebook que m'has passat no
   hi havia definit un `cmap`/`norm` per aquesta variable (la cel·la 6 es
   talla abans d'arribar-hi) — n'hi ha posat un placeholder (`YlOrRd` continu)
   a `VARIABLES["ros_fli"]` dins `generate_frames.py`. Canvia'l pel que facis
   servir tu habitualment per ROS/FLI.

3. **`OUTPUT_ROOT`** a `generate_frames.py` apunta a
   `/home/pguarque/onofre_viewer_output` — ajusta-ho si vols que
   coincideixi amb la carpeta que fas `git push` (com `OUTPUT_PLOTS` o el
   directori del repo clonat al servidor).

4. **Publicació.** Si el repo `onofre-viewer` té `frontend/` com a arrel de
   GitHub Pages, `DATA_ROOT = "./data"` a `index.html` ha d'apuntar on
   copiïs la carpeta `<var_id>/<run_tag>/` generada (p. ex. copiar-la a
   `frontend/data/<var_id>/latest/` abans del `git push`, tal com ja fas
   amb el manifest de l'echotops-viewer).

5. **Historial de runs (opcional).** Ara mateix el frontend només llegeix
   `RUN_TAG = "latest"`. Si vols poder consultar runs anteriors, genera
   també un `runs.json` amb la llista de `run_tag` disponibles i afegeix un
   petit selector — puc ajudar-t'ho quan ho vulguis.

## Notes de disseny

- **ROS/FLI mai surt fora de Catalunya**: el manifest ho declara amb
  `"domain": "catalunya"` i el frontend mostra un avís i recentra el mapa,
  però no cal restringir el `imageOverlay` — simplement no hi ha frame fora
  d'aquest extent.
- **Descàrrega "tal i com surt al codi"** = `mosaic.png`, generat reutilitzant
  `plot_time_mosaic_gridspec` sense canviar-ne la lògica.
- **GIF** i **mosaic** es generen a partir dels mateixos frames PNG que
  alimenten el viewer, així mai es desincronitzen entre ells.
