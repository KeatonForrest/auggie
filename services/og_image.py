"""Generate dynamic Open Graph images for shared document links."""

import math
import os
from io import BytesIO
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# Resolve paths relative to project root
_ROOT = Path(__file__).resolve().parent.parent
_FONTS_DIR = _ROOT / "static" / "fonts"
_STATIC_DIR = _ROOT / "static"

# Image dimensions (standard OG)
WIDTH, HEIGHT = 1200, 630

# Colors
WHITE = (255, 255, 255)
BG = (249, 250, 251)          # gray-50
DARK = (17, 24, 39)            # gray-900
MUTED = (107, 114, 128)        # gray-500
LIGHT_BORDER = (229, 231, 235) # gray-200
BLUE = (37, 99, 235)           # blue-600
GREEN = (34, 197, 94)          # green-500
YELLOW = (234, 179, 8)         # yellow-500
RED = (248, 113, 113)          # red-400
LIGHT_GRAY = (243, 244, 246)   # gray-100
BAR_BG = (229, 231, 235)       # gray-200


def _score_color(score: int) -> tuple:
    if score >= 70:
        return GREEN
    elif score >= 40:
        return YELLOW
    return RED


def _load_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a bundled Inter font, falling back to system fonts."""
    path = _FONTS_DIR / name
    if path.exists():
        return ImageFont.truetype(str(path), size)
    # Fallback chain for systems without bundled fonts
    for fallback in ["/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if os.path.exists(fallback):
            return ImageFont.truetype(fallback, size)
    return ImageFont.load_default()


def _load_mascot() -> Image.Image | None:
    """Load the Auggie detective mascot."""
    path = _STATIC_DIR / "auggie-detective.png"
    if path.exists():
        return Image.open(path).convert("RGBA")
    return None


def _draw_rounded_rect(draw: ImageDraw.Draw, xy: tuple, radius: int, fill=None, outline=None, width=1):
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _draw_score_ring(img: Image.Image, center: tuple, radius: int, score: int, color: tuple, thickness: int = 10):
    """Draw a score ring (arc) on the image."""
    draw = ImageDraw.Draw(img)
    cx, cy = center
    bbox = (cx - radius, cy - radius, cx + radius, cy + radius)
    # Background ring
    draw.arc(bbox, 0, 360, fill=BAR_BG, width=thickness)
    # Score arc (0-360 degrees, starting from top)
    angle = int((score / 100) * 360)
    if angle > 0:
        draw.arc(bbox, -90, -90 + angle, fill=color, width=thickness)


def generate_og_image(
    company_name: str,
    opportunity_score: int | None = None,
    pain_score: int | None = None,
    fit_score: int | None = None,
    timing_score: int | None = None,
    score_summary: str | None = None,
) -> bytes:
    """Generate a 1200x630 OG image card and return PNG bytes."""
    img = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(img)

    # Fonts
    font_bold_40 = _load_font("Inter-Bold.ttf", 40)
    font_bold_28 = _load_font("Inter-Bold.ttf", 28)
    font_semi_18 = _load_font("Inter-SemiBold.ttf", 18)
    font_reg_16 = _load_font("Inter-Regular.ttf", 16)
    font_reg_20 = _load_font("Inter-Regular.ttf", 20)
    font_bold_56 = _load_font("Inter-Bold.ttf", 56)
    font_semi_14 = _load_font("Inter-SemiBold.ttf", 14)
    font_reg_14 = _load_font("Inter-Regular.ttf", 14)
    font_semi_24 = _load_font("Inter-SemiBold.ttf", 24)

    # ── Background: subtle top accent bar ──
    draw.rectangle((0, 0, WIDTH, 6), fill=BLUE)

    # ── Left section: mascot ──
    mascot = _load_mascot()
    mascot_x = 60
    mascot_size = 200
    if mascot:
        mascot_resized = mascot.resize((mascot_size, mascot_size), Image.LANCZOS)
        # Center vertically
        mascot_y = (HEIGHT - mascot_size) // 2
        img.paste(mascot_resized, (mascot_x, mascot_y), mascot_resized)

    # ── Right content area ──
    content_x = mascot_x + mascot_size + 60  # 320

    # Company name
    name_y = 60
    # Truncate long names
    display_name = company_name
    if len(display_name) > 30:
        display_name = display_name[:28] + "..."
    draw.text((content_x, name_y), display_name, fill=DARK, font=font_bold_40)

    # Subtitle
    draw.text((content_x, name_y + 52), "Research Report", fill=MUTED, font=font_reg_20)

    # ── Score section ──
    if opportunity_score is not None:
        scores_y = 170

        # Large composite score circle
        score_cx = content_x + 70
        score_cy = scores_y + 75
        score_radius = 62
        ring_thickness = 12
        score_color = _score_color(opportunity_score)

        # Draw filled circle background
        draw.ellipse(
            (score_cx - score_radius, score_cy - score_radius,
             score_cx + score_radius, score_cy + score_radius),
            fill=LIGHT_GRAY
        )
        # Score ring
        _draw_score_ring(img, (score_cx, score_cy), score_radius, opportunity_score, score_color, ring_thickness)

        # Score number centered in circle
        score_text = str(opportunity_score)
        bbox = draw.textbbox((0, 0), score_text, font=font_bold_56)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((score_cx - tw // 2, score_cy - th // 2 - 4), score_text, fill=DARK, font=font_bold_56)

        # Label under circle
        label = "Opportunity"
        bbox = draw.textbbox((0, 0), label, font=font_semi_14)
        lw = bbox[2] - bbox[0]
        draw.text((score_cx - lw // 2, score_cy + score_radius + 12), label, fill=MUTED, font=font_semi_14)

        # ── Sub-score bars ──
        bar_x = content_x + 200
        bar_w = 380
        bar_h = 14
        bar_radius = 7

        sub_scores = [
            ("Pain", pain_score),
            ("Fit", fit_score),
            ("Timing", timing_score),
        ]

        for i, (label, score) in enumerate(sub_scores):
            if score is None:
                continue
            by = scores_y + 18 + (i * 50)
            color = _score_color(score)

            # Label
            draw.text((bar_x, by - 2), label, fill=MUTED, font=font_semi_18)

            # Bar background
            bar_left = bar_x + 80
            _draw_rounded_rect(draw, (bar_left, by + 2, bar_left + bar_w, by + 2 + bar_h), bar_radius, fill=BAR_BG)

            # Bar fill
            fill_w = max(bar_radius * 2, int(bar_w * score / 100))
            _draw_rounded_rect(draw, (bar_left, by + 2, bar_left + fill_w, by + 2 + bar_h), bar_radius, fill=color)

            # Score number
            draw.text((bar_left + bar_w + 14, by - 2), str(score), fill=DARK, font=font_semi_18)

        # ── Score summary ──
        if score_summary:
            summary_y = scores_y + 180
            # Wrap text to fit
            max_chars = 85
            summary = score_summary[:200]
            lines = []
            while summary:
                if len(summary) <= max_chars:
                    lines.append(summary)
                    break
                # Find last space before limit
                cut = summary[:max_chars].rfind(" ")
                if cut == -1:
                    cut = max_chars
                lines.append(summary[:cut])
                summary = summary[cut:].lstrip()
                if len(lines) >= 2:
                    if summary:
                        lines[-1] = lines[-1][:max_chars - 3] + "..."
                    break

            for j, line in enumerate(lines):
                draw.text((content_x, summary_y + j * 24), line, fill=MUTED, font=font_reg_16)

    # ── Bottom branding bar ──
    draw.line((0, HEIGHT - 56, WIDTH, HEIGHT - 56), fill=LIGHT_BORDER, width=1)
    draw.text((content_x, HEIGHT - 42), "auggie.tools", fill=BLUE, font=font_semi_18)

    # ── Export ──
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf.getvalue()
