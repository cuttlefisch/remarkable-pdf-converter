"""
r2pdf converter — Core conversion logic for EPUB to dark-mode PDFs
optimized for the Remarkable Paper Pro tablet.
"""

import base64
import json
import logging
import re
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote as _url_unquote
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_LIBRARY = Path.home() / "Calibre-Library"
DEFAULT_OUTPUT = Path.home() / "remarkable-pdfs"

CSS_TEMPLATE = """
@page {{
    size: 107.22mm 190.61mm;
    margin: {margin_top}mm {margin_right}mm {margin_bottom}mm {margin_left}mm;
    background-color: #1c1208;
}}
html {{
    background-color: #1c1208 !important;
}}
body {{
    background-color: #1c1208 !important;
    color: #e8d5b7 !important;
    line-height: {line_height} !important;
    font-size: {font_size}pt !important;
    font-family: 'Linux Libertine', Georgia, Palatino, 'Palatino Linotype', serif !important;
    margin: 0;
    padding: 0;
}}
* {{
    background-color: transparent !important;
    color: #e8d5b7 !important;
    border-color: #3a2e1a !important;
}}
h1, h2, h3, h4, h5, h6 {{
    color: #f5e8cc !important;
    line-height: 1.4 !important;
}}
code, pre {{
    background-color: #2a1e0a !important;
    color: #c8b89a !important;
}}
a {{
    color: #c8960a !important;
}}
img {{
    max-width: 100%;
    height: auto;
}}
.page-break {{
    page-break-before: always;
    margin: 0;
    padding: 0;
    height: 0;
    border: none;
}}
table {{
    border-collapse: collapse;
}}
td, th {{
    border: 1px solid #3a2e1a !important;
    padding: 0.3em 0.5em;
}}
blockquote {{
    border-left: 3px solid #c8960a !important;
    margin-left: 1em;
    padding-left: 0.8em;
    color: #c8b89a !important;
}}
"""

MIME_MAP = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.png': 'image/png', '.gif': 'image/gif',
    '.svg': 'image/svg+xml', '.webp': 'image/webp',
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class FileValidationError(Exception):
    pass

class ConversionError(Exception):
    pass

class OutputValidationError(Exception):
    pass


# ---------------------------------------------------------------------------
# File type detection
# ---------------------------------------------------------------------------

def detect_file_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".epub":
        return "epub"
    return "unknown"


# ---------------------------------------------------------------------------
# EPUB → HTML pipeline
# ---------------------------------------------------------------------------

NAMESPACES = {
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "xhtml": "http://www.w3.org/1999/xhtml",
}

for prefix, uri in NAMESPACES.items():
    ET.register_namespace(prefix, uri)


def _file_to_data_uri(path: Path) -> str | None:
    try:
        data = path.read_bytes()
        mime = MIME_MAP.get(path.suffix.lower(), 'image/png')
        b64 = base64.b64encode(data).decode('ascii')
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None


def _parse_xml(data: bytes) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        clean = b"\n".join(
            line for line in data.splitlines()
            if not line.strip().startswith(b"<!DOCTYPE")
        )
        return ET.fromstring(clean)


def epub_to_html_folder(epub_path: Path, tmp_dir: Path) -> tuple[list[Path], list[Path]]:
    """Extract EPUB, parse spine, return (ordered_html_files, all_asset_paths)."""
    extract_dir = tmp_dir / "epub_extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(epub_path, "r") as zf:
        zf.extractall(extract_dir)

    container_path = extract_dir / "META-INF" / "container.xml"
    if not container_path.exists():
        raise FileValidationError(f"No META-INF/container.xml in {epub_path}")

    container_xml = _parse_xml(container_path.read_bytes())
    rootfile_el = container_xml.find(
        ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"
    )
    if rootfile_el is None:
        raise FileValidationError(f"No rootfile element in container.xml of {epub_path}")

    opf_rel = rootfile_el.get("full-path", "")
    opf_path = extract_dir / opf_rel
    if not opf_path.exists():
        raise FileValidationError(f"OPF file not found: {opf_path}")

    opf_dir = opf_path.parent
    opf_xml = _parse_xml(opf_path.read_bytes())

    manifest = {}
    ns_opf = "http://www.idpf.org/2007/opf"
    for item in opf_xml.findall(f"{{{ns_opf}}}manifest/{{{ns_opf}}}item"):
        item_id = item.get("id", "")
        href = item.get("href", "")
        media_type = item.get("media-type", "")
        if item_id and href:
            manifest[item_id] = {"href": href, "media-type": media_type}

    spine_el = opf_xml.find(f"{{{ns_opf}}}spine")
    if spine_el is None:
        raise FileValidationError(f"No spine in OPF of {epub_path}")

    ordered_html = []
    for itemref in spine_el.findall(f"{{{ns_opf}}}itemref"):
        idref = itemref.get("idref", "")
        if idref in manifest:
            href = manifest[idref]["href"]
            html_path = opf_dir / href
            if html_path.exists():
                ordered_html.append(html_path)
            else:
                log.warning("Spine item not found: %s", html_path)

    if not ordered_html:
        raise FileValidationError(f"No readable HTML files found in spine of {epub_path}")

    assets = [f for f in extract_dir.rglob("*") if f.is_file()]

    return ordered_html, assets


def _spine_anchor_id(html_path: Path) -> str:
    """Deterministic anchor ID for a spine file, used to resolve bare-filename links."""
    return "r2pdf--" + re.sub(r'[^a-zA-Z0-9_-]', '_', html_path.name)


def _extract_body_content(html_bytes: bytes, html_path: Path,
                          file_id_map: dict[str, str] | None = None) -> str:
    """Extract inner content of <body> from an HTML/XHTML file."""
    try:
        text = html_bytes.decode("utf-8", errors="replace")
    except Exception:
        text = html_bytes.decode("latin-1", errors="replace")

    body_match = re.search(
        r"<body[^>]*>(.*?)</body>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if body_match:
        content = body_match.group(1)
    else:
        head_match = re.search(r"</head>", text, re.IGNORECASE)
        content = text[head_match.end():] if head_match else text

    # Embed images as base64 data URIs.
    # Handles src= (img tags) and xlink:href= (SVG image elements).
    def embed_asset(m):
        attr = m.group(1)
        quote = m.group(2)
        val = m.group(3)
        if val.startswith(("http://", "https://", "data:", "file://")):
            return m.group(0)
        asset_path = (html_path.parent / val).resolve()
        uri = _file_to_data_uri(asset_path)
        if uri:
            return f'{attr}={quote}{uri}{quote}'
        log.warning("Could not embed asset, falling back to file://: %s", asset_path)
        return f'{attr}={quote}file://{asset_path}{quote}'

    content = re.sub(
        r'(src|xlink:href)=(["\'])(?!http|https|data:|file://)([^"\']+)\2',
        embed_asset,
        content,
        flags=re.IGNORECASE,
    )

    # Fix internal cross-file links after combining into a single HTML.
    #   "chapter.xhtml#anchor" → "#anchor"
    #   "chapter.xhtml"        → "#r2pdf--chapter_xhtml" (via file_id_map)
    def fix_internal_link(m):
        quote = m.group(1)
        href = m.group(2)
        if re.match(r'(?:https?|mailto|ftp|data):', href, re.IGNORECASE):
            return m.group(0)
        href = _url_unquote(href)
        if '#' in href:
            _, frag = href.split('#', 1)
            return f'href={quote}#{frag}{quote}'
        # Bare filename — resolve via file_id_map to the synthetic anchor
        if file_id_map:
            # Strip any path components to get just the filename
            basename = href.rsplit('/', 1)[-1] if '/' in href else href
            anchor = file_id_map.get(basename)
            if anchor:
                return f'href={quote}#{anchor}{quote}'
        return f'href={quote}#{quote}'

    content = re.sub(
        r'href=(["\'])([^"\']+)\1',
        fix_internal_link,
        content,
        flags=re.IGNORECASE,
    )

    return content


def build_combined_html(
    html_files: list[Path],
    tmp_dir: Path,
    title: str,
    css: str,
) -> Path:
    """Concatenate spine HTML files into a single combined.html."""
    # Build filename → synthetic anchor ID map so bare-filename ToC links resolve.
    file_id_map: dict[str, str] = {}
    for html_path in html_files:
        file_id_map[html_path.name] = _spine_anchor_id(html_path)

    parts = [
        f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{_html_escape(title)}</title>
<style>
{css}
</style>
</head>
<body>
"""
    ]

    for i, html_path in enumerate(html_files):
        content = _extract_body_content(html_path.read_bytes(), html_path,
                                        file_id_map=file_id_map)
        if i > 0:
            parts.append('<div class="page-break"></div>\n')
        anchor_id = file_id_map[html_path.name]
        parts.append(f'<div id="{anchor_id}">\n')
        parts.append(content)
        parts.append("\n</div>\n")

    parts.append("</body>\n</html>\n")

    combined_path = tmp_dir / "combined.html"
    combined_path.write_text("".join(parts), encoding="utf-8")
    return combined_path


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# WeasyPrint
# ---------------------------------------------------------------------------

def run_weasyprint(html_path: Path, output_pdf: Path) -> None:
    """Render combined HTML to PDF using WeasyPrint."""
    import weasyprint
    doc = weasyprint.HTML(filename=str(html_path), base_url=str(html_path.parent))
    doc.write_pdf(str(output_pdf))
    if not output_pdf.exists() or output_pdf.stat().st_size < 1024:
        raise OutputValidationError(
            f"WeasyPrint output missing/tiny: {output_pdf}"
        )


# ---------------------------------------------------------------------------
# Single-file conversion
# ---------------------------------------------------------------------------

def convert_single(
    input_path: Path,
    output_dir: Path,
    options: dict,
) -> Path:
    """Convert one EPUB to a Remarkable-optimized dark-mode PDF."""
    if not input_path.exists():
        raise FileValidationError(f"Input file not found: {input_path}")

    file_type = detect_file_type(input_path)
    if file_type == "unknown":
        raise FileValidationError(f"Unsupported file type: {input_path.suffix}")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_stem = _safe_stem(input_path)
    output_pdf = output_dir / f"{output_stem}.pdf"

    if options.get("skip_existing") and output_pdf.exists():
        log.info("Skipping (exists): %s", output_pdf.name)
        return output_pdf

    if options.get("dry_run"):
        log.info("[DRY RUN] Would convert: %s → %s", input_path, output_pdf)
        return output_pdf

    css = CSS_TEMPLATE.format(
        line_height=options.get("line_height", 2.0),
        font_size=options.get("font_size", 11),
        margin_top=options.get("margin_top", 15),
        margin_bottom=options.get("margin_bottom", 15),
        margin_left=options.get("margin_left", 10),
        margin_right=options.get("margin_right", 10),
    )
    title = input_path.stem.replace("_", " ")

    with tempfile.TemporaryDirectory(prefix="r2pdf_") as tmp_str:
        tmp_dir = Path(tmp_str)

        html_files, _ = epub_to_html_folder(input_path, tmp_dir)
        combined = build_combined_html(html_files, tmp_dir, title, css)
        run_weasyprint(combined, output_pdf)

    if not options.get("dry_run") and not output_pdf.exists():
        raise OutputValidationError(f"No output produced for {input_path}")

    log.info("Converted: %s → %s", input_path.name, output_pdf.name)
    return output_pdf


def _safe_stem(path: Path) -> str:
    """Create a safe output filename stem."""
    return path.stem.replace(" ", "_").replace("/", "_").replace("\\", "_")


# ---------------------------------------------------------------------------
# Bulk discovery
# ---------------------------------------------------------------------------

def find_convertible_files(source_dir: Path) -> list[Path]:
    """
    Walk Calibre library structure (Author/Book (ID)/) and return
    one EPUB per book directory.
    """
    source_dir = source_dir.resolve()
    book_dirs: dict[Path, Path] = {}

    for f in source_dir.rglob("*.epub"):
        if not f.is_file():
            continue
        book_dir = f.parent
        if book_dir not in book_dirs:
            book_dirs[book_dir] = f

    return [book_dirs[d] for d in sorted(book_dirs)]


def _output_name_for(input_path: Path, source_dir: Path) -> str:
    """Generate flat output filename like Author__Book_Title__ID.pdf"""
    try:
        rel = input_path.relative_to(source_dir)
        parts = rel.parts
        if len(parts) >= 2:
            author = parts[0].replace(" ", "_")
            book = parts[1].replace(" ", "_")
            return f"{author}__{book}"
        else:
            return _safe_stem(input_path)
    except ValueError:
        return _safe_stem(input_path)


# ---------------------------------------------------------------------------
# Bulk conversion
# ---------------------------------------------------------------------------

def convert_bulk(
    source_dir: Path,
    output_dir: Path,
    options: dict,
) -> dict:
    """Convert all books in source_dir. Returns stats dict."""
    files = find_convertible_files(source_dir)

    log.info("Found %d files to convert in %s", len(files), source_dir)

    if options.get("dry_run"):
        for f in files:
            name = _output_name_for(f, source_dir)
            log.info("[DRY RUN] %s → %s.pdf", f, name)
        return {"total": len(files), "converted": 0, "skipped": 0, "failed": 0, "dry_run": True}

    stats = {"total": len(files), "converted": 0, "skipped": 0, "failed": 0}
    progress_log = output_dir / "conversion_log.jsonl"
    output_dir.mkdir(parents=True, exist_ok=True)

    def _convert_one(f: Path) -> dict:
        out_stem = _output_name_for(f, source_dir)
        out_pdf = output_dir / f"{out_stem}.pdf"

        if options.get("skip_existing") and out_pdf.exists():
            return {"file": str(f), "status": "skipped", "output": str(out_pdf)}

        file_opts = dict(options)
        try:
            result_path = convert_single(f, output_dir, file_opts)
            if result_path.name != out_pdf.name and result_path.exists():
                result_path.rename(out_pdf)
            return {"file": str(f), "status": "ok", "output": str(out_pdf)}
        except (FileValidationError, ConversionError, OutputValidationError) as e:
            log.error("FAILED %s: %s", f.name, e)
            return {"file": str(f), "status": "failed", "error": str(e)}
        except Exception as e:
            log.error("UNEXPECTED ERROR %s: %s", f.name, e)
            return {"file": str(f), "status": "failed", "error": str(e)}

    workers = options.get("workers", 4)
    with open(progress_log, "a") as log_fh:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_convert_one, f): f for f in files}
            for future in as_completed(futures):
                result = future.result()
                log_fh.write(json.dumps(result) + "\n")
                log_fh.flush()
                if result["status"] == "ok":
                    stats["converted"] += 1
                elif result["status"] == "skipped":
                    stats["skipped"] += 1
                else:
                    stats["failed"] += 1

    return stats
