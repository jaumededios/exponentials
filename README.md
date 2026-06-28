# arXiv Math Weekly Exponentials

This workspace downloads arXiv metadata, builds weekly math subcategory counts,
fits sequential two-exponential models, and serves a static Plotly site.

Weekly bins start on Monday, which avoids the daily arXiv announcement hump.
The current partial week is skipped.

## Setup

```bash
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
curl -L --fail --continue-at - --output data/arxiv-metadata.json \
  'https://huggingface.co/datasets/labofsahil/arXiv-metadata-Dataset/resolve/main/arxiv-metadata.json?download=true'
```

The site builder writes `site/exponentials/data/series.json`, which contains
weekly counts and precomputed fit coefficients for every math subcategory.

## GitHub Pages deployment

The static site is deployed from the `site/` directory by GitHub Actions. The
published path is `/exponentials/`:

- GitHub project Pages: `https://<owner>.github.io/<repo>/exponentials/`
- Custom domain, if configured in the repository Pages settings:
  `https://<domain>/exponentials/`

The site uses one stable generated seed artifact:

- `site/exponentials/data/series.json`

Refresh it locally with:

```bash
.venv/bin/python scripts/build_exponentials_site.py
```

The builder scans the metadata snapshot, refreshes recent complete weeks from
the arXiv API, and reruns the sequential fit: first a slow exponential, then a
fast exponential on the residual. It intentionally skips the current partial
week. Recent complete weeks are re-fetched to absorb arXiv API lag. Fits use
500 smart random starts per stage.

The GitHub Action in `.github/workflows/refresh-arxiv-plots.yml` runs on push,
manually, and every Tuesday UTC. On GitHub it rebuilds the JSON, using the
committed JSON as the seed if the full metadata snapshot is not present, commits
the refreshed JSON back to the repository, then uploads `site/` and deploys it
to GitHub Pages. The site/action path serves JSON and renders in the browser
with Plotly; it does not generate matplotlib PNGs. In the repository settings,
set Pages to deploy from GitHub Actions.

## Static site

The toggleable site lives in `site/exponentials/` and can be served from a
static host at `/exponentials`, e.g. `jaume.dedios.cat/exponentials`.
Plotly provides the range selector, range slider, drag zoom, scroll zoom, and
modebar controls.

Local preview:

```bash
python3 -m http.server 8000 --directory site
```

Then open `http://localhost:8000/exponentials/`.
