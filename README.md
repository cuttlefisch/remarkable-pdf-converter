# r2pdf — EPUB to Remarkable PDF Converter

Converts EPUB files into dark-mode, double-spaced PDFs sized and optimized for the [Remarkable Paper Pro](https://remarkable.com/) tablet. Pages use a warm dark background (`#1c1208`) with light text (`#e8d5b7`), and the output preserves table of contents links, internal cross-references, and inline images.

## Prerequisites

- **Python 3.11+**
- **WeasyPrint** system libraries — WeasyPrint requires Pango, Cairo, and GDK-PixBuf. Install them via your system package manager before `pip install`:
  - **Fedora / RHEL:** `sudo dnf install pango cairo gdk-pixbuf2`
  - **Debian / Ubuntu:** `sudo apt install libpango-1.0-0 libcairo2 libgdk-pixbuf-2.0-0`
  - See the [WeasyPrint installation docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation) for other platforms.

## Installation

```bash
git clone git@github.com:cuttlefisch/remarkable-pdf-converter.git
cd remarkable-pdf-converter
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This installs the `r2pdf` command inside the virtualenv. To make it available outside the venv, symlink the entry point:

```bash
ln -sf "$(pwd)/.venv/bin/r2pdf" ~/.local/bin/r2pdf
```

## Usage

### Single file

```bash
r2pdf book.epub
r2pdf book.epub -o /tmp/output/
```

### Bulk conversion (Calibre library)

```bash
r2pdf ~/Calibre-Library/ -o ~/remarkable-pdfs/
# or explicitly:
r2pdf --bulk ~/Calibre-Library/ -o ~/remarkable-pdfs/
```

### Dry run

```bash
r2pdf --bulk ~/Calibre-Library/ --dry-run
```

## CLI Options

| Option | Default | Description |
|---|---|---|
| `-o, --output DIR` | `~/remarkable-pdfs` | Output directory |
| `-b, --bulk` | off | Treat input as directory, convert all EPUBs recursively |
| `--font-size N` | `11` | Base font size in pt |
| `--line-height F` | `2.0` | Line height multiplier |
| `--margin MM` | — | Set all four page margins (mm), overrides individual margins |
| `--margin-top MM` | `15` | Top margin in mm |
| `--margin-bottom MM` | `15` | Bottom margin in mm |
| `--margin-left MM` | `10` | Left margin in mm |
| `--margin-right MM` | `10` | Right margin in mm |
| `--workers N` | `4` | Parallel workers for bulk conversion |
| `--skip-existing` | off | Skip files that already have an output PDF |
| `--dry-run` | off | Print what would be converted without converting |
| `-v, --verbose` | off | Enable debug output |

## License

GPL-3.0 — see [LICENSE](LICENSE).
