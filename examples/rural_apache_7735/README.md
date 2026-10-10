# Example: Rural Road & Apache Boulevard, Tempe, Arizona

This is the output of one complete pipeline run for a signalised four-leg intersection near Arizona State University. Apache Boulevard carries the Valley Metro light rail in its median. The run used tracing `autoloop-geometry-6` and classification `hybrid-pilot-v8-street-view-counts`.

The same junction has two IDs in the sources:

| Source | ID |
|---|---|
| Tempe macro network | node 7735 |
| City UTDF signal data | intersection 76 |

![Lane labels on the satellite image](results/annotated/labels/overview.jpg)

Model output is a prediction, not reference data.

## Dashboard

[`dashboard/intersection_explorer_example.html`](../../dashboard/intersection_explorer_example.html) is the dashboard built for this intersection alone. It is a single 1.6 MB file holding the data, the images and the map library. Download it and open it in a browser; only the background map tiles need a connection. It shows four things:

- The traced lanes on the satellite image.
- Each approach's lanes and movements, with UTDF and OpenStreetMap beside them.
- Every street view, with the model's observation boxes.
- The signal and sign audit, and the labelled figures.

![Intersection Explorer](screenshots/intersection_explorer.png)

## Lane panels

![Lane panels for each approach and exit](results/annotated/labels/sections.jpg)

## What the model read

The model read 16 movements: 12 proposed and 4 left unresolved. Motor lanes on each approach, beside the City's UTDF data:

| Approach | EB | NB | SB | WB |
|---|---:|---:|---:|---:|
| VLM | 4 | 4 | 5 | 6 |
| UTDF | 4 | 5 | 5 | 4 |

The differences are left as they came out:

- **NB:** one lane short.
- **WB:** two lanes too many. Strips next to the light-rail median were read as motor lanes shared with rail.

The dashboard shows each difference with the blind automated check and the manual check of the imagery.

## Files

```
network/                     GMNS excerpt (nodes and links within 600 m of node 7735)
screenshots/                 dashboard screenshot used in the READMEs
figures/                     README figures: street views, projected boundaries, YOLO boxes, signals and signs, shade lift
results/
  imagery/                   site config, evidence config, exit views, acquisition record
  geometry/                  traced sections (lane boundaries on the satellite image) and the loop summary
  classification/            lanes, movements, lane-use audits, street-view contexts, CSV tables, report
  exits/                     exit re-audit
  controls/                  signal and sign audit
  lane_check/                blind lane-count check against UTDF, with review sheets
  atlas/                     GeoJSON of the lanes and rejected regions, atlas data, georeference, report
  images/                    satellite image and every street view, named by approach, position and direction
  annotated/                 lane labels, candidate and accepted regions, tracing plan, movements per approach
  answers/                   every raw model answer (87), laid out by stage
  export.json                list of the exported files
```

Paths inside the configs (for example `runs/imagery_tempe_7735/...`) point into the run folders the results were exported from. Those folders are not included. The reports are in Chinese.

## Try the first step

The network excerpt is enough to list the sections and the request budget for this node, without any API key or network access:

```bash
python scripts/pipeline/run_site_pipeline.py --name example_7735 --node-id 7735 \
  --node-csv examples/rural_apache_7735/network/node.csv \
  --link-csv examples/rural_apache_7735/network/link.csv --plan-only
```

## Sources and attribution

- Satellite imagery: © Mapbox, © Maxar.
- Street-level imagery: © Google.
- Network: derived from OpenStreetMap, © OpenStreetMap contributors, ODbL.
- Reference lanes in the dashboard: City of Tempe UTDF signal timing data.

The images are included here only to illustrate the method.
