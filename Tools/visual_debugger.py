#!/usr/bin/env python3
"""
Visual Debugger for HTML→PNG card generation.
- Renders with html2image
- Optionally trims whitespace with the same algorithm as in core/html_visual_generator.py
- Compares raw vs. trimmed sizes
- Logs everything to stdout and to a report file

Run:
  python tools/visual_debugger.py --outdir _viz_debug

Optional flags:
  --no-trim              Disable trimming step
  --viewport 1365x768    Set viewport (widthxheight) for html2image (default: library default)
  --case summary|file|conversion|all   What to render (default: all)

The script tries to use project templates in ./templates/*.html and ./templates/card_styles.css.
If not found, it will produce a minimal synthetic test card.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple


# --- Third-party availability checks ---
try:
    from html2image import Html2Image  # type: ignore
    HTML2IMAGE_AVAILABLE = True
except Exception:
    Html2Image = None  # type: ignore
    HTML2IMAGE_AVAILABLE = False

try:
    from PIL import Image, ImageChops, ImageStat  # type: ignore
    PIL_AVAILABLE = True
except Exception:
    Image = ImageChops = ImageStat = None  # type: ignore
    PIL_AVAILABLE = False

# Try to import user's generator for a direct end-to-end test
GEN_AVAILABLE = False
try:
    from core.html_visual_generator import HtmlVisualGenerator  # type: ignore
    GEN_AVAILABLE = True
except Exception:
    GEN_AVAILABLE = False

# --- Paths ---
ROOT = Path(__file__).resolve().parents[1] if (Path(__file__).name == 'visual_debugger.py') else Path.cwd()
TEMPLATES = ROOT / 'templates'
CSS_FILE = TEMPLATES / 'card_styles.css'

# --- Minimal CSS override to guarantee tight render when the real CSS is hostile ---
OVERRIDE_TIGHT_CSS = (
    "html,body{background:transparent!important;margin:0!important;padding:0!important;"
    "display:block!important;width:max-content!important;height:max-content!important;overflow:visible!important;}"
)

BAD_BODY_CSS = (
    "body{min-height:100vh;display:flex;align-items:center;justify-content:center;"
    "background:linear-gradient(135deg,#111 0%,#222 100%);}"
)

# --- Logger ---
LOGGER = logging.getLogger('visual_debugger')
LOGGER.setLevel(logging.DEBUG)


def setup_logging(outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    report = outdir / 'viz_report.txt'
    fh = logging.FileHandler(report, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    fmt = logging.Formatter('%(asctime)s | %(levelname)s | %(message)s')
    fh.setFormatter(fmt)
    sh.setFormatter(fmt)
    LOGGER.addHandler(fh)
    LOGGER.addHandler(sh)
    return report


# --- Helper: trimming identical to project logic ---
def trim_whitespace(image_path: Path) -> Path:
    # это копия обновлённого _trim_whitespace с альфа-обрезкой
    if not (PIL_AVAILABLE and image_path.exists()):
        return image_path
    try:
        with Image.open(image_path) as img:
            if img.mode in ("RGBA", "LA"):
                # обрезка по альфе
                rgba = img.convert("RGBA")
                a = rgba.split()[3]
                mask = a.point(lambda v: 255 if v > 2 else 0, mode="1")
                bbox = mask.getbbox()
                if bbox:
                    cropped = rgba.crop(bbox)
                    out = image_path.with_name(f"trimmed_{image_path.name}")
                    cropped.save(out, "PNG", optimize=True)
                    return out
        return image_path
    except Exception:
        return image_path


# --- Helper: analyze PNG ---
def analyze_image(image_path: Path):
    """Extended analyzer that reports alpha stats and tight bbox using alpha when possible."""
    data = {
        'exists': image_path.exists(),
        'path': str(image_path),
        'size': None,
        'mode': None,
        'has_alpha': None,
        'corner_colors': None,
        'alpha_stats': None,
        'bbox_alpha': None,
        'bbox_rgb': None,
    }
    if not (PIL_AVAILABLE and image_path.exists()):
        return data
    with Image.open(image_path) as img:
        data['mode'] = img.mode
        w, h = img.size
        data['size'] = [w, h]
        corners = [img.getpixel((0,0)), img.getpixel((w-1,0)), img.getpixel((0,h-1)), img.getpixel((w-1,h-1))]
        data['corner_colors'] = corners
        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and 'transparency' in img.info)
        data['has_alpha'] = has_alpha
        if has_alpha:
            a = img.convert('RGBA').split()[3]
            stat = ImageStat.Stat(a)
            data['alpha_stats'] = {'min': stat.extrema[0][0], 'max': stat.extrema[0][1], 'mean': stat.mean[0]}
            bbox_a = a.point(lambda v: 255 if v > 2 else 0, '1').getbbox()
            data['bbox_alpha'] = bbox_a
        # RGB bbox for reference
        bg = Image.new(img.mode, (w, h), img.getpixel((0,0)))
        diff = ImageChops.add(ImageChops.difference(img, bg), ImageChops.difference(img, bg), 2.0, -10)
        data['bbox_rgb'] = diff.getbbox()
    return data


# --- HTML builders using templates or fallbacks ---

def load_template(name: str) -> str:
    path = TEMPLATES / name
    if path.exists():
        return path.read_text(encoding='utf-8')
    # Minimal fallback: a simple .card
    if name == 'summary_template.html':
        return (
            "<html><head><meta charset='utf-8'></head><body>"
            "<div class='card'><div class='header'><h1 class='title'>{title}</h1></div>"
            "<div class='content'><div class='files-section'><h3>{files_title}</h3>"
            "<div class='files-list'>{files_html}</div></div></div>"
            "<div class='footer'><span class='timestamp'>{timestamp}</span></div>"
            "</div></body></html>"
        )
    if name == 'conversion_template.html':
        return (
            "<html><head><meta charset='utf-8'></head><body>"
            "<div class='card'><div class='header {status_class}'><h1 class='title'>{status_icon} {status_text}</h1></div>"
            "<div class='content'><div class='conversion-flow'><div class='track-box source'><div class='track-title'>Исходная дорожка</div>"
            "<div class='track-info'><span class='channels'>{src_channels}ch</span><span class='codec'>{src_codec}</span></div></div>"
            "<div class='arrow'>→</div><div class='track-box target'><div class='track-title'>Результат</div>"
            "<div class='track-info'><span class='channels'>{tgt_channels}ch</span><span class='codec'>{tgt_codec}</span></div></div></div></div>"
            "<div class='footer'><span class='timestamp'>{timestamp}</span></div></div>"
            "</body></html>"
        )
    if name == 'file_info_template.html':
        return (
            "<html><head><meta charset='utf-8'></head><body>"
            "<div class='card'><div class='header'><h1 class='title'>{title}</h1></div>"
            "<div class='content'><div class='file-name'>{filename}</div>"
            "<div class='file-details'><div class='detail'><span class='label'>Размер</span><span class='value'>{size}</span></div>"
            "<div class='detail'><span class='label'>Разрешение</span><span class='value'>{resolution}</span></div></div>"
            "<div class='audio-section'><h3>🎵 Аудио дорожки</h3><div class='audio-tracks'>{tracks_html}</div></div></div>"
            "<div class='footer'><span class='timestamp'>{timestamp}</span></div></div>"
            "</body></html>"
        )
    raise FileNotFoundError(name)


def load_css_variant(variant: str = 'as_is') -> str:
    base = CSS_FILE.read_text(encoding='utf-8') if CSS_FILE.exists() else ''
    if variant == 'as_is':
        return base if base else OVERRIDE_TIGHT_CSS
    if variant == 'bad':
        return BAD_BODY_CSS + base
    if variant == 'tight':
        return base + '\n' + OVERRIDE_TIGHT_CSS
    return OVERRIDE_TIGHT_CSS


# --- html2image render ---

def render_html(html: str, css: str, out: Path, viewport: Optional[Tuple[int, int]] = None) -> Path:
    if not HTML2IMAGE_AVAILABLE:
        raise RuntimeError('html2image is not available')
    out.parent.mkdir(parents=True, exist_ok=True)
    hti = Html2Image(output_path=str(out.parent))  # type: ignore
    kwargs = {
        'html_str': html,
        'css_str': css,
        'save_as': out.name,
    }
    if viewport:
        # html2image uses size=(w,h) to set viewport
        kwargs['size'] = viewport
    hti.screenshot(**kwargs)  # type: ignore[arg-type]
    return out


# --- Test cases ---

def sample_summary_html() -> str:
    tpl = load_template('summary_template.html')
    files = []
    for i in range(4):
        files.append(f"<div class='file-item processed'><span class='status-icon'>✅</span><span class='filename'>File_{i:02d}.mkv</span></div>")
    return tpl.format(
        title='🚀 Мониторинг запущен',
        startup_info="",
        total_files=4,
        processed_files=2,
        pending_files=1,
        error_files=1,
        files_title='📁 Файлы в директории:',
        files_html='\n'.join(files),
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M'),
    )


def sample_conversion_html() -> str:
    tpl = load_template('conversion_template.html')
    return tpl.format(
        status_class='error', status_icon='❌', status_text='Ошибка конвертации',
        filename='TWD.[S07E01].HD1080.DD5.1.LostFilm.[qqss44].mkv',
        src_channels=6, src_codec='UNKNOWN',
        tgt_channels=2, tgt_codec='AAC',
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M'),
    )


def sample_file_info_html() -> str:
    tpl = load_template('file_info_template.html')
    tracks = []
    for ch, lang, codec in [(2, 'ENG', 'AAC'), (6, 'RUS', 'AC3')]:
        tclass = 'stereo' if ch == 2 else 'surround'
        tracks.append(
            f"<div class='audio-track {tclass}'><span class='channels'>{ch}ch</span><span class='language'>{lang}</span><span class='codec'>{codec}</span></div>"
        )
    return tpl.format(
        title='📁 Информация о файле',
        filename='Example.EP01.1080p.WEB-DL.DDP5.1.H.264.mkv',
        size='1.8 GB', resolution='1916×1076',
        tracks_html='\n'.join(tracks),
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M'),
    )


# --- Runner ---

def run_case(outdir: Path, name: str, html_fn, css_variant: str, do_trim: bool, viewport: Optional[Tuple[int, int]]):
    LOGGER.info('--- Case: %s | css=%s | viewport=%s | trim=%s', name, css_variant, viewport, do_trim)
    html = html_fn()
    css = load_css_variant(css_variant)
    raw_path = outdir / f'{name}_{css_variant}_raw.png'
    render_html(html, css, raw_path, viewport)
    raw_info = analyze_image(raw_path)
    LOGGER.info('Raw: size=%s, uniform_corners=%s, bbox=%s, ratio=%.4f', raw_info.get('size'), raw_info.get('uniform_corners'), raw_info.get('bbox'), (raw_info.get('bbox_area_ratio') or 0))

    final_path = raw_path
    final_info = raw_info
    if do_trim:
        trimmed = trim_whitespace(raw_path)
        final_info = analyze_image(trimmed)
        final_path = trimmed
        LOGGER.info('Trimmed: size=%s, bbox=%s, ratio=%.4f', final_info.get('size'), final_info.get('bbox'), (final_info.get('bbox_area_ratio') or 0))

    return {
        'case': name,
        'css_variant': css_variant,
        'viewport': viewport,
        'raw': raw_info,
        'final': final_info,
        'final_path': str(final_path),
    }


def main():
    parser = argparse.ArgumentParser(description='Visual renderer debugger')
    parser.add_argument('--outdir', default='_viz_debug', help='Output directory for images and report')
    parser.add_argument('--no-trim', action='store_true', help='Disable trimming step')
    parser.add_argument('--viewport', default=None, help='Viewport WxH (e.g., 1365x768)')
    parser.add_argument('--case', default='all', choices=['all', 'summary', 'file', 'conversion'])
    args = parser.parse_args()

    outdir = Path(args.outdir)
    report_path = setup_logging(outdir)
    LOGGER.info('ROOT=%s', ROOT)
    LOGGER.info('Templates dir=%s (exists=%s)', TEMPLATES, TEMPLATES.exists())
    LOGGER.info('CSS file=%s (exists=%s)', CSS_FILE, CSS_FILE.exists())
    LOGGER.info('html2image=%s, PIL=%s, Generator=%s', HTML2IMAGE_AVAILABLE, PIL_AVAILABLE, GEN_AVAILABLE)

    viewport: Optional[Tuple[int, int]] = None
    if args.viewport:
        m = re.match(r'^(\d+)x(\d+)$', args.viewport.strip())
        if not m:
            raise SystemExit('--viewport format must be WxH, e.g., 1365x768')
        viewport = (int(m.group(1)), int(m.group(2)))

    results = []

    # 0) Try end-to-end via user's generator (summary card)
    if GEN_AVAILABLE:
        try:
            viz = HtmlVisualGenerator(do_trim=not args.no_trim)
            summary_info = {
                'startup': True,
                'stats': {'total_files': 4, 'processed_files': 2, 'pending_files': 1, 'error_files': 1},
                'recent_files': [
                    {'name': 'A.mkv', 'status': 'processed'},
                    {'name': 'B.mkv', 'status': 'pending'},
                    {'name': 'C.mkv', 'status': 'error'},
                    {'name': 'D.mkv', 'status': 'processed'},
                ],
                'directory': 'E:/Download/Movie',
                'interval': 300,
            }
            path = viz.generate_summary_card(summary_info)
            if path:
                dst = outdir / ('generator_summary.png')
                Path(path).replace(dst)
                results.append({'case': 'generator_summary', 'note': 'HtmlVisualGenerator', 'info': analyze_image(dst), 'path': str(dst)})
                LOGGER.info('Generator summary: %s', results[-1]['info'])
        except Exception:
            LOGGER.exception('Generator test failed')

    # 1) Synthetic runs over three CSS variants
    case_map = {
        'summary': sample_summary_html,
        'file': sample_file_info_html,
        'conversion': sample_conversion_html,
    }
    selected = ['summary', 'file', 'conversion'] if args.case == 'all' else [args.case]

    for cname in selected:
        for css_variant in ['as_is', 'bad', 'tight']:
            res = run_case(outdir, cname, case_map[cname], css_variant, do_trim=not args.no_trim, viewport=viewport)
            results.append(res)

    # Save JSON summary
    summary_json = outdir / 'viz_summary.json'
    summary_json.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')

    LOGGER.info('Written report: %s', report_path)
    LOGGER.info('Summary JSON: %s', summary_json)
    print(f"\nDone. Please send back: {report_path} and {summary_json} (plus a couple of PNGs if sizes look wrong).")


if __name__ == '__main__':
    main()
