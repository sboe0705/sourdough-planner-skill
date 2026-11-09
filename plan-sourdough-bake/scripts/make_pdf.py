#!/usr/bin/env python3
"""Render a baking plan as a one-page, print-friendly A4 PDF.

Reads the recipe JSON and the JSON output of schedule.py, so nothing is
hard-coded: title, subtitle, source link, ingredients and steps all come
from those two files. The PDF holds only the recipe and the plan: no notes,
assumptions, conflicts or adjustments.

Layout: title -> subtitle (with the source domain as a link) -> optional
image -> ingredients in two columns -> one section per day ("Day before",
"Bake day", or real dates with --dates). Each step shows its clock time on
the left and "Step · Duration" plus the instruction on the right. An
"Oven on" row marks the preheat moment and a "Done" row ends the plan.

Needs reportlab (pip install reportlab); Pillow is only needed for PNG and
other non-JPEG images. The plan model (build_model) is plain Python and
works without reportlab. Run with --help for usage.

  python3 schedule.py recipe.json --finish 2026-11-14T10:00 > plan.json
  python3 make_pdf.py recipe.json plan.json -o plan.pdf --lang de
"""

from __future__ import annotations

import argparse
import html
import io
import json
import os
import re
import sys
import urllib.request
from datetime import datetime
from urllib.parse import urlparse

# --- layout constants (points unless noted; 1 mm = 72 / 25.4 pt) -----------
MM = 72 / 25.4
MARGIN_X_MM = 20
MARGIN_Y_MM = 18
FRAME_PADDING = 12  # the frame pads 6 pt on each side
TIME_COL_MM = 18
INGREDIENT_AMOUNT_MM = 20
IMAGE_MAX_HEIGHT_MM = 85
IMAGE_MIN_HEIGHT_MM = 40  # the image shrinks down to this to keep one page
STEP_GAP = 9
STEP_GAP_COMPACT = 5  # used only when the plan would not fit on one page
ACCENT = "#8a5a2b"
SUBTLE = "#666666"
BODY = "#333333"

LABELS = {
    "en": {
        "ingredients": "Ingredients",
        "bake_day": "Bake day",
        "day_before": "Day before",
        "days_before": "{n} days before",
        "oven_on": "Oven on",
        "preheat": "Preheat for {duration}.",
        "done": "Done",
        "source": "Recipe",
        "date": "{weekday}, {day} {month_name} {year}",
        "weekdays": "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday,Sunday",
        "months": "January,February,March,April,May,June,July,August,September,"
                  "October,November,December",
        "decimal": ".",
    },
    "de": {
        "ingredients": "Zutaten",
        "bake_day": "Backtag",
        "day_before": "Vortag",
        "days_before": "{n} Tage vorher",
        "oven_on": "Ofen an",
        "preheat": "{duration} vorheizen.",
        "done": "Fertig",
        "source": "Rezept",
        "date": "{weekday}, {day}. {month_name} {year}",
        "weekdays": "Montag,Dienstag,Mittwoch,Donnerstag,Freitag,Samstag,Sonntag",
        "months": "Januar,Februar,März,April,Mai,Juni,Juli,August,September,"
                  "Oktober,November,Dezember",
        "decimal": ",",
    },
}

# Emoji and pictographs: the PDF fonts have no glyphs for them.
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF"
    "\U0000FE00-\U0000FE0F\U0000200D\U000020E3]+")


class PlanError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Plan model (no reportlab needed)
# ---------------------------------------------------------------------------

def clean(text) -> str:
    """Drop emoji and collapse the whitespace they leave behind."""
    text = _EMOJI.sub("", str(text or ""))
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def labels_for(lang: str, overrides=None) -> dict:
    if lang not in LABELS:
        raise PlanError(f"unknown language {lang!r} (use {', '.join(sorted(LABELS))}, "
                        "and --label for anything else)")
    out = dict(LABELS[lang])
    for key, value in (overrides or {}).items():
        if key not in out:
            raise PlanError(f"unknown label {key!r} (known: {', '.join(sorted(out))})")
        out[key] = value
    return out


def format_amount(amount, decimal: str) -> str:
    if isinstance(amount, float) and amount.is_integer():
        amount = int(amount)
    text = str(amount)
    return text.replace(".", decimal) if isinstance(amount, float) else text


def source_domain(url: str) -> str:
    host = urlparse(url).netloc.split("@")[-1].split(":")[0].lower()
    return host[4:] if host.startswith("www.") else host


def day_heading(day, finish_day, labels: dict, use_dates: bool) -> str:
    if use_dates:
        weekdays = [w.strip() for w in labels["weekdays"].split(",")]
        months = [m.strip() for m in labels["months"].split(",")]
        if len(weekdays) != 7 or len(months) != 12:
            raise PlanError("the weekdays label needs 7 names and the months label 12")
        return labels["date"].format(weekday=weekdays[day.weekday()], day=day.day,
                                     month=day.month, month_name=months[day.month - 1],
                                     year=day.year)
    offset = (finish_day - day).days
    if offset == 0:
        return labels["bake_day"]
    if offset == 1:
        return labels["day_before"]
    return labels["days_before"].format(n=offset)


def collect_ingredients(steps, decimal: str) -> list:
    """Ingredients with an amount, in recipe order. Ingredients without an amount
    (a levain made in an earlier step) are intermediate products and left out."""
    out = []
    for step in steps:
        for ing in step.get("ingredients") or []:
            if ing.get("amount") is None:
                continue
            amount = format_amount(ing["amount"], decimal)
            if ing.get("unit"):
                amount += " " + clean(ing["unit"])
            name = clean(ing.get("name"))
            if ing.get("note"):
                name += f" ({clean(ing['note'])})"
            out.append((amount, name))
    return out


def build_model(recipe: dict, schedule: dict, option: int = 0, lang: str = "en",
                label_overrides=None, subtitle=None, use_dates: bool = False) -> dict:
    """Turn the recipe and schedule.py's JSON into the plain content of the PDF."""
    labels = labels_for(lang, label_overrides)
    options = schedule.get("options") or []
    if not options:
        raise PlanError("the schedule JSON has no options (is it schedule.py's JSON output?)")
    if not 0 <= option < len(options):
        raise PlanError(f"option {option} does not exist (the schedule has {len(options)})")
    opt = options[option]
    steps = opt.get("steps") or []
    if not steps:
        raise PlanError("the chosen option has no steps")

    finish = datetime.fromisoformat(opt["finish"])
    events = []  # (time, order, row)
    for i, s in enumerate(steps):
        head = clean(s["title"])
        if s.get("duration"):
            head += " · " + s["duration"]
        events.append((datetime.fromisoformat(s["start"]), 2 * i,
                       {"time": None, "head": head, "desc": clean(s.get("desc"))}))
        if s.get("preheat_at"):
            pre = datetime.fromisoformat(s["preheat_at"])
            preheat_min = int((datetime.fromisoformat(s["start"]) - pre).total_seconds() // 60)
            # just after the step that is running when the oven goes on
            order = max((2 * j + 1 for j, t in enumerate(steps)
                         if datetime.fromisoformat(t["start"]) <= pre), default=-1)
            events.append((pre, order, {
                "time": None, "head": labels["oven_on"],
                "desc": labels["preheat"].format(duration=minutes_label(preheat_min))}))
    events.append((finish, 2 * len(steps), {"time": None, "head": labels["done"], "desc": ""}))
    events.sort(key=lambda e: (e[0], e[1]))

    days = []
    for when, _, row in events:
        row["time"] = when.strftime("%H:%M")
        heading = day_heading(when.date(), finish.date(), labels, use_dates)
        if not days or days[-1]["date"] != when.date():
            days.append({"date": when.date(), "heading": heading, "rows": []})
        days[-1]["rows"].append(row)

    sub = clean(subtitle if subtitle is not None else recipe.get("subtitle"))
    source = recipe.get("source") or {}
    url = source.get("url") if isinstance(source, dict) else None
    link = None
    if url and urlparse(url).scheme in ("http", "https"):
        link = {"url": url, "text": source_domain(url), "label": labels["source"]}

    return {
        "title": clean(recipe.get("name") or schedule.get("recipe") or ""),
        "subtitle": sub,
        "link": link,
        "ingredients_heading": labels["ingredients"],
        "ingredients": collect_ingredients(steps, labels["decimal"]),
        "days": days,
    }


def minutes_label(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    if h and m:
        return f"{h} h {m} min"
    return f"{h} h" if h else f"{m} min"


# ---------------------------------------------------------------------------
# Rendering (reportlab)
# ---------------------------------------------------------------------------

FONT_DIRS = (
    "/usr/share/fonts/truetype/dejavu",          # Debian, Ubuntu
    "/usr/share/fonts/dejavu-sans-fonts",         # Fedora
    "/usr/share/fonts/dejavu",                    # openSUSE, Alpine
    "/usr/share/fonts/TTF",                       # Arch
    "/usr/local/share/fonts",
    os.path.expanduser("~/.fonts"),
    os.path.expanduser("~/.local/share/fonts"),
    os.path.expanduser("~/Library/Fonts"),        # macOS
    "/Library/Fonts",
)


def register_fonts(font_dir=None) -> tuple[str, str, str]:
    """Register DejaVu Sans if it can be found, else reportlab's bundled Vera
    (DejaVu's ancestor), else fall back to Helvetica. Returns (regular, bold, name)."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    candidates = []
    dirs = ([font_dir] if font_dir else []) + list(FONT_DIRS)
    try:  # matplotlib bundles DejaVu Sans
        import matplotlib
        dirs.append(os.path.join(os.path.dirname(matplotlib.__file__), "mpl-data", "fonts", "ttf"))
    except Exception:
        pass
    for d in dirs:
        candidates.append(("DejaVu Sans", os.path.join(d, "DejaVuSans.ttf"),
                           os.path.join(d, "DejaVuSans-Bold.ttf")))
    import reportlab
    vera = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    candidates.append(("Vera", os.path.join(vera, "Vera.ttf"), os.path.join(vera, "VeraBd.ttf")))

    for name, regular, bold in candidates:
        if os.path.isfile(regular) and os.path.isfile(bold):
            try:
                pdfmetrics.registerFont(TTFont("PlanSans", regular))
                pdfmetrics.registerFont(TTFont("PlanSans-Bold", bold))
                pdfmetrics.registerFontFamily("PlanSans", normal="PlanSans", bold="PlanSans-Bold",
                                              italic="PlanSans", boldItalic="PlanSans-Bold")
                return "PlanSans", "PlanSans-Bold", name
            except Exception:
                continue
    return "Helvetica", "Helvetica-Bold", "Helvetica"


def load_image(ref: str):
    """Return image bytes from a local path or an http(s) URL."""
    if urlparse(ref).scheme in ("http", "https"):
        req = urllib.request.Request(ref, headers={"User-Agent": "plan-sourdough-bake/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read()
    with open(ref, "rb") as f:
        return f.read()


def render_pdf(model: dict, path: str, image=None, font_dir=None) -> dict:
    """Write the PDF. Returns {"pages", "font", "image"} where image is
    "none", "included" or "failed: <reason>". If the plan spills onto a second
    page, the image is shrunk (down to IMAGE_MIN_HEIGHT_MM) and then the spacing
    tightened to make it fit."""
    fonts = register_fonts(font_dir)
    image_data, image_status = None, "none"
    if image:
        try:
            image_data = load_image(image)
            _image_size(image_data)  # fail early on unreadable data
            image_status = "included"
        except Exception as exc:  # noqa: BLE001 - any failure: build without the image
            image_data, image_status = None, f"failed: {exc.__class__.__name__}: {exc}"

    # Aim for one page: first shrink the image step by step, then tighten the spacing.
    heights = range(IMAGE_MAX_HEIGHT_MM, IMAGE_MIN_HEIGHT_MM - 1, -5) if image_data else [0]
    attempts = [(h, False) for h in heights] + [(heights[-1], True)]
    for max_h, compact in attempts:
        buf = io.BytesIO()
        pages = _build(model, buf, fonts, image_data, max_h * MM, compact)
        if pages == 1:
            break
    with open(path, "wb") as f:
        f.write(buf.getvalue())
    return {"pages": pages, "font": fonts[2], "image": image_status}


def _image_size(data: bytes):
    from reportlab.lib.utils import ImageReader
    return ImageReader(io.BytesIO(data)).getSize()


def _build(model: dict, out, fonts, image_data, image_max_h: float, compact: bool) -> int:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    regular, bold, _ = fonts
    esc = html.escape

    def style(name, **kw):
        base = {"fontName": regular, "fontSize": 10, "leading": 13, "textColor": colors.black}
        base.update(kw)
        return ParagraphStyle(name, **base)

    st_title = style("title", fontName=bold, fontSize=22, leading=26, spaceAfter=4)
    st_sub = style("subtitle", fontSize=10, leading=14, textColor=colors.HexColor(SUBTLE))
    st_head = style("heading", fontName=bold, fontSize=13, leading=16,
                    textColor=colors.HexColor(ACCENT), spaceBefore=10 if compact else 14,
                    spaceAfter=4 if compact else 6)
    st_amount = style("amount", fontName=bold)
    st_ing = style("ingredient")
    st_time = style("time", fontName=bold, fontSize=10.5, leading=13)
    st_step = style("step", fontName=bold, fontSize=10.5, leading=13)
    st_desc = style("desc", fontSize=9.5, leading=12.5, textColor=colors.HexColor(BODY))

    doc = SimpleDocTemplate(
        out, pagesize=A4, leftMargin=MARGIN_X_MM * MM, rightMargin=MARGIN_X_MM * MM,
        topMargin=MARGIN_Y_MM * MM, bottomMargin=MARGIN_Y_MM * MM,
        initialFontName=regular, title=model["title"], creator="plan-sourdough-bake")
    width = doc.width - FRAME_PADDING  # never wider than the text column
    plain = [("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
             ("TOPPADDING", (0, 0), (-1, -1), 0), ("VALIGN", (0, 0), (-1, -1), "TOP")]

    story = [Paragraph(esc(model["title"]), st_title)]
    sub = esc(model["subtitle"])
    if model["link"]:
        link = model["link"]
        anchor = f'<a href="{esc(link["url"])}" color="{ACCENT}">{esc(link["text"])}</a>'
        sub = f'{sub} · {esc(link["label"])}: {anchor}' if sub else f'{esc(link["label"])}: {anchor}'
    if sub:
        story.append(Paragraph(sub, st_sub))

    if image_data is not None:
        iw, ih = _image_size(image_data)
        w, h = width, width * ih / iw
        if h > image_max_h:
            w, h = w * image_max_h / h, image_max_h
        img = Image(io.BytesIO(image_data), width=w, height=h)
        img.hAlign = "CENTER"
        story += [Spacer(1, 10), img]

    if model["ingredients"]:
        items = model["ingredients"]
        half = (len(items) + 1) // 2
        left, right = items[:half], items[half:]
        amount_w = INGREDIENT_AMOUNT_MM * MM
        col_w = width / 2
        rows = []
        for i in range(half):
            row = []
            for col in (left, right):
                if i < len(col):
                    row += [Paragraph(esc(col[i][0]), st_amount), Paragraph(esc(col[i][1]), st_ing)]
                else:
                    row += [Paragraph("", st_ing), Paragraph("", st_ing)]
            rows.append(row)
        table = Table(rows, colWidths=[amount_w, col_w - amount_w, amount_w, col_w - amount_w])
        table.setStyle(TableStyle(plain + [
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (0, -1), 4), ("RIGHTPADDING", (2, 0), (2, -1), 4),
            ("RIGHTPADDING", (1, 0), (1, -1), 10)]))
        story.append(KeepTogether([Paragraph(esc(model["ingredients_heading"]), st_head), table]))

    time_w = TIME_COL_MM * MM
    for day in model["days"]:
        # one table per step: a step never splits across pages, and the day
        # heading stays with its first step
        tables = []
        for i, r in enumerate(day["rows"]):
            cell = [Paragraph(esc(r["head"]), st_step)]
            if r["desc"]:
                cell.append(Paragraph(esc(r["desc"]), st_desc))
            table = Table([[Paragraph(esc(r["time"]), st_time), cell]],
                          colWidths=[time_w, width - time_w])
            gap = (STEP_GAP_COMPACT if compact else STEP_GAP) if i < len(day["rows"]) - 1 else 0
            table.setStyle(TableStyle(plain + [("BOTTOMPADDING", (0, 0), (-1, -1), gap)]))
            tables.append(table)
        story.append(KeepTogether([Paragraph(esc(day["heading"]), st_head), tables[0]]))
        story += tables[1:]

    doc.build(story)
    return doc.page


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def read_json(path: str):
    try:
        if path == "-":
            return json.load(sys.stdin)
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanError(f"cannot read {path}: {exc}") from exc


def parse_label(text: str) -> tuple[str, str]:
    key, sep, value = text.partition("=")
    if not sep or not key.strip():
        raise argparse.ArgumentTypeError(f"invalid label {text!r} (use KEY=TEXT)")
    return key.strip(), value


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Render a baking plan (schedule.py JSON + recipe JSON) as a one-page A4 PDF.",
        epilog="Labels: " + ", ".join(sorted(LABELS["en"])) + ". "
               "Templates: days_before uses {n}, preheat {duration}, "
               "date {weekday} {day} {month} {month_name} {year}; "
               "weekdays and months are comma-separated lists.")
    p.add_argument("recipe", help="recipe JSON file")
    p.add_argument("schedule", help="schedule.py JSON output, or - for stdin")
    p.add_argument("-o", "--output", required=True, help="PDF file to write")
    p.add_argument("--option", type=int, default=0, help="which option to render (default 0)")
    p.add_argument("--lang", default="en", choices=sorted(LABELS), help="label language (default en)")
    p.add_argument("--label", action="append", type=parse_label, default=[], metavar="KEY=TEXT",
                   help="override one label, e.g. --label done=Klaar (repeatable)")
    p.add_argument("--subtitle", help="subtitle, e.g. 'Baking plan for 2 loaves' "
                                      "(default: the recipe's subtitle)")
    p.add_argument("--image", metavar="PATH_OR_URL", help="recipe photo to show under the subtitle")
    p.add_argument("--dates", action="store_true",
                   help="head each day with its date instead of 'Day before' / 'Bake day'")
    p.add_argument("--font-dir", help="directory containing DejaVuSans.ttf and DejaVuSans-Bold.ttf")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        model = build_model(read_json(args.recipe), read_json(args.schedule), args.option,
                            args.lang, dict(args.label), args.subtitle, args.dates)
    except (PlanError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        import reportlab  # noqa: F401
    except ImportError as exc:
        # reportlab 5 installs on Python 3.9 but refuses to import there
        hint = "'reportlab<5'" if sys.version_info < (3, 10) else "reportlab"
        print(f"error: cannot import reportlab ({exc}); install it with: pip install {hint}",
              file=sys.stderr)
        return 3
    result = render_pdf(model, args.output, args.image, args.font_dir)
    result["pdf"] = args.output
    if result["image"].startswith("failed"):
        print(f"warning: image not included ({result['image'][8:]})", file=sys.stderr)
    if result["pages"] > 1:
        print(f"warning: the PDF has {result['pages']} pages", file=sys.stderr)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
