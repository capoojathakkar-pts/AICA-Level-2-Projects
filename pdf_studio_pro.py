#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ahmedabad PDF Studio Pro (with Secure Redaction)
=================================================
A professional, offline desktop PDF toolkit built with PyQt5.

Merged application combining:
    - Ahmedabad PDF Studio Pro: Merge, Split, Extract, Page Numbers,
      Rearrange, PDF <-> Image, Password Protect/Remove.
    - PDF Redaction Tool: Manual / Find & Redact / Smart Redaction with
      true content-stream removal (PyMuPDF based).

Adds:
    - Centralized ThemeManager: Light, Dark, System (Auto), Photo-based,
      and Brand Palette themes, applied consistently across every widget.
    - Theme persistence to a local JSON settings file.
    - TrialManager: a clearly isolated, replaceable 60-second trial gate.

Run:
    python pdf_studio_pro.py

On first run as a plain .py script, the app attempts to auto-install any
missing dependencies exactly once. When frozen into a .exe (PyInstaller),
this step is skipped automatically, since all dependencies are expected
to be bundled already.
"""

import os
import sys
import json
import subprocess
import importlib
import traceback
from pathlib import Path


# ---------------------------------------------------------------------------
# Section 1: Dependency bootstrap
# ---------------------------------------------------------------------------
def _running_as_frozen_exe() -> bool:
    """Return True if this code is currently running inside a PyInstaller exe."""
    return getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS")


def _ensure_dependencies() -> None:
    """Install any missing required packages. Skipped when running as a frozen exe."""
    if _running_as_frozen_exe():
        return

    # pip package name -> module name used in import statements
    required_packages = {
        "PyQt5": "PyQt5",
        "pypdf": "pypdf",
        "reportlab": "reportlab",
        "Pillow": "PIL",
        "PyMuPDF": "fitz",
        # pypdf needs "cryptography" to add/remove AES-encrypted passwords.
        "cryptography": "cryptography",
    }

    missing = []
    for pip_name, module_name in required_packages.items():
        try:
            importlib.import_module(module_name)
        except ImportError:
            missing.append(pip_name)

    if not missing:
        return

    print("PDF Studio Pro: installing required libraries, please wait ...")
    for pip_name in missing:
        base_command = [sys.executable, "-m", "pip", "install", "--quiet",
                         "--disable-pip-version-check", pip_name]
        try:
            subprocess.check_call(base_command)
            print(f"  - Installed {pip_name}")
            continue
        except Exception:
            pass

        # Some systems (notably certain Linux distributions) mark the
        # environment as "externally managed" and refuse plain pip installs.
        # Retry once with --break-system-packages, safe for a dedicated
        # desktop-app use case like this one.
        try:
            subprocess.check_call(base_command + ["--break-system-packages"])
            print(f"  - Installed {pip_name}")
        except Exception as second_error:
            print(f"  - Could not automatically install {pip_name}: {second_error}")
            print(f"    Please install it manually with:  pip install {pip_name}")


_ensure_dependencies()


# ---------------------------------------------------------------------------
# Section 2: Third-party imports (safe now that dependencies are ensured)
# ---------------------------------------------------------------------------
import re
import io
import math
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict

try:
    from PyQt5.QtCore import (
        Qt, QThread, pyqtSignal, QRectF, QPointF, QRect, QSize, QTimer,
        QObject
    )
    from PyQt5.QtGui import (
        QFont, QIcon, QColor, QPalette, QPixmap, QImage, QPainter, QPen,
        QBrush, QCursor, QKeySequence
    )
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QGridLayout, QPushButton, QLabel, QListWidget, QListWidgetItem,
        QFileDialog, QMessageBox, QLineEdit, QComboBox, QSpinBox,
        QGroupBox, QStackedWidget, QAbstractItemView, QProgressBar,
        QFrame, QCheckBox, QRadioButton, QButtonGroup, QSplitter,
        QPlainTextEdit, QScrollArea, QTabWidget, QToolButton, QMenu,
        QAction, QStatusBar, QProgressDialog, QSizePolicy, QDialog,
        QShortcut
    )
except ImportError:
    print("Fatal error: PyQt5 is required but could not be imported/installed.")
    print("Please run:  pip install PyQt5")
    raise

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    try:
        import pymupdf as fitz  # newer alias
        HAS_FITZ = True
    except ImportError:
        HAS_FITZ = False

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


APP_NAME = "Ahmedabad PDF Studio Pro"
APP_VERSION = "2.0"
SETTINGS_DIR = Path.home() / ".ahmedabad_pdf_studio_pro"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"


# ---------------------------------------------------------------------------
# Section 3: Theme definitions, brand palettes, and ThemeManager
# ---------------------------------------------------------------------------
# A "theme" is a flat dict of named color roles. Every role listed in
# _REQUIRED_ROLES must be present in every theme/palette so the stylesheet
# generator never hits a KeyError, and every visual layer of the UI stays
# consistent when the user switches themes.
_REQUIRED_ROLES = [
    "primary", "primary_dark", "secondary", "accent", "accent_dark",
    "background", "surface", "surface_alt", "text_primary", "text_secondary",
    "border", "success", "success_dark", "danger", "danger_dark",
    "on_primary", "on_accent",
]

THEME_LIGHT: Dict[str, str] = {
    "primary": "#1565C0",
    "primary_dark": "#0B3D91",
    "secondary": "#1652A3",
    "accent": "#D32F2F",
    "accent_dark": "#B71C1C",
    "background": "#F3F6FB",
    "surface": "#FFFFFF",
    "surface_alt": "#E8F1FC",
    "text_primary": "#12233F",
    "text_secondary": "#3B4B66",
    "border": "#C9D8ED",
    "success": "#1C7C4E",
    "success_dark": "#145B39",
    "danger": "#D32F2F",
    "danger_dark": "#B71C1C",
    "on_primary": "#FFFFFF",
    "on_accent": "#FFFFFF",
}

THEME_DARK: Dict[str, str] = {
    "primary": "#3E7BD6",
    "primary_dark": "#254E8C",
    "secondary": "#4A8FE0",
    "accent": "#E05353",
    "accent_dark": "#B8382F",
    "background": "#14181F",
    "surface": "#1D232D",
    "surface_alt": "#242B36",
    "text_primary": "#E8ECF2",
    "text_secondary": "#A6B0C0",
    "border": "#323B48",
    "success": "#2FA36B",
    "success_dark": "#227B50",
    "danger": "#E05353",
    "danger_dark": "#B8382F",
    "on_primary": "#FFFFFF",
    "on_accent": "#FFFFFF",
}

# Brand Palette themes: coordinated color sets, not single-accent swaps.
# New palettes can be added here without touching any other code.
BRAND_PALETTES: Dict[str, Dict[str, str]] = {
    "Ocean Blue": {
        "primary": "#1565C0", "primary_dark": "#0B3D91", "secondary": "#1E88E5",
        "accent": "#D32F2F", "accent_dark": "#B71C1C",
        "background": "#F3F6FB", "surface": "#FFFFFF", "surface_alt": "#E8F1FC",
        "text_primary": "#12233F", "text_secondary": "#3B4B66", "border": "#C9D8ED",
        "success": "#1C7C4E", "success_dark": "#145B39",
        "danger": "#D32F2F", "danger_dark": "#B71C1C",
        "on_primary": "#FFFFFF", "on_accent": "#FFFFFF",
    },
    "Emerald": {
        "primary": "#0F8A5F", "primary_dark": "#0A5E41", "secondary": "#14A876",
        "accent": "#C9622A", "accent_dark": "#9C4A1E",
        "background": "#F2F9F5", "surface": "#FFFFFF", "surface_alt": "#E3F4EA",
        "text_primary": "#12291F", "text_secondary": "#3D5A4A", "border": "#C7E3D3",
        "success": "#1C7C4E", "success_dark": "#145B39",
        "danger": "#C9622A", "danger_dark": "#9C4A1E",
        "on_primary": "#FFFFFF", "on_accent": "#FFFFFF",
    },
    "Royal Purple": {
        "primary": "#6A3FA0", "primary_dark": "#4A2A73", "secondary": "#8256BE",
        "accent": "#D6336C", "accent_dark": "#A32552",
        "background": "#F7F4FB", "surface": "#FFFFFF", "surface_alt": "#ECE4F6",
        "text_primary": "#241B33", "text_secondary": "#4E4162", "border": "#DACBEE",
        "success": "#1C7C4E", "success_dark": "#145B39",
        "danger": "#D6336C", "danger_dark": "#A32552",
        "on_primary": "#FFFFFF", "on_accent": "#FFFFFF",
    },
    "Slate Graphite": {
        "primary": "#3E5266", "primary_dark": "#28323F", "secondary": "#56728C",
        "accent": "#C9A227", "accent_dark": "#9C7D1C",
        "background": "#F3F4F6", "surface": "#FFFFFF", "surface_alt": "#E6E9ED",
        "text_primary": "#1B2027", "text_secondary": "#495564", "border": "#D2D7DE",
        "success": "#1C7C4E", "success_dark": "#145B39",
        "danger": "#C0392B", "danger_dark": "#96281D",
        "on_primary": "#FFFFFF", "on_accent": "#FFFFFF",
    },
    "Sunset Amber": {
        "primary": "#B85C1E", "primary_dark": "#8A4315", "secondary": "#D4791F",
        "accent": "#A6303E", "accent_dark": "#7C232E",
        "background": "#FBF5EF", "surface": "#FFFFFF", "surface_alt": "#F5E7D6",
        "text_primary": "#2E2113", "text_secondary": "#5C4630", "border": "#E7D3B6",
        "success": "#1C7C4E", "success_dark": "#145B39",
        "danger": "#A6303E", "danger_dark": "#7C232E",
        "on_primary": "#FFFFFF", "on_accent": "#FFFFFF",
    },
}


def _relative_luminance(hex_color: str) -> float:
    """Approximate perceived luminance of a hex color (0=black, 1=white)."""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return 0.5
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        return 0.5

    def lin(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = lin(r), lin(g), lin(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    la, lb = _relative_luminance(hex_a), _relative_luminance(hex_b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    r, g, b = (max(0, min(255, int(c))) for c in rgb)
    return "#{:02X}{:02X}{:02X}".format(r, g, b)


def _hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _adjust_lightness(hex_color: str, factor: float) -> str:
    """factor > 1 lightens toward white, factor < 1 darkens toward black."""
    r, g, b = _hex_to_rgb(hex_color)
    if factor >= 1:
        blend = factor - 1
        r = r + (255 - r) * blend
        g = g + (255 - g) * blend
        b = b + (255 - b) * blend
    else:
        r, g, b = r * factor, g * factor, b * factor
    return _rgb_to_hex((r, g, b))


def build_theme_from_image(image_path: str) -> Dict[str, str]:
    """
    Analyze an image's dominant colors and derive a complete, readable
    application theme from them. Falls back safely to THEME_LIGHT if
    analysis fails for any reason (missing Pillow, unreadable file, etc).
    """
    if not HAS_PIL:
        return dict(THEME_LIGHT)
    try:
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((150, 150))
        # Quantize to a small adaptive palette to find dominant colors
        # without needing any extra dependency beyond Pillow.
        quantized = img.quantize(colors=8, method=Image.MEDIANCUT)
        palette = quantized.getpalette()
        color_counts = quantized.getcolors()
        if not color_counts:
            return dict(THEME_LIGHT)
        color_counts.sort(key=lambda x: x[0], reverse=True)

        dominant_colors = []
        for count, idx in color_counts:
            r = palette[idx * 3]
            g = palette[idx * 3 + 1]
            b = palette[idx * 3 + 2]
            dominant_colors.append(_rgb_to_hex((r, g, b)))

        primary = dominant_colors[0]
        secondary = dominant_colors[1] if len(dominant_colors) > 1 else primary
        accent = dominant_colors[2] if len(dominant_colors) > 2 else secondary

        # Decide light vs dark mode from the average luminance of the image.
        avg_luminance = sum(_relative_luminance(c) for c in dominant_colors) / len(dominant_colors)
        is_dark_mode = avg_luminance < 0.45

        if is_dark_mode:
            background = _adjust_lightness(primary, 0.18)
            surface = _adjust_lightness(primary, 0.28)
            surface_alt = _adjust_lightness(primary, 0.38)
            text_primary = "#EDEFF3"
            text_secondary = "#B7BEC9"
            border = _adjust_lightness(primary, 0.5)
            # Ensure the primary itself is bright enough to read as an accent.
            if _relative_luminance(primary) < 0.35:
                primary = _adjust_lightness(primary, 1.6)
        else:
            background = _adjust_lightness(primary, 1.85)
            surface = "#FFFFFF"
            surface_alt = _adjust_lightness(primary, 1.7)
            text_primary = "#16202E"
            text_secondary = "#46536A"
            border = _adjust_lightness(primary, 1.55)
            # Ensure primary is dark enough to read as a UI accent on white.
            if _relative_luminance(primary) > 0.6:
                primary = _adjust_lightness(primary, 0.55)

        # Guarantee usable contrast; fall back to a safe accent otherwise.
        if _contrast_ratio(accent, background) < 2.2:
            accent = "#D32F2F" if not is_dark_mode else "#E05353"

        primary_dark = _adjust_lightness(primary, 0.7)
        accent_dark = _adjust_lightness(accent, 0.7)
        on_primary = "#FFFFFF" if _relative_luminance(primary) < 0.55 else "#12233F"
        on_accent = "#FFFFFF" if _relative_luminance(accent) < 0.55 else "#12233F"

        theme = {
            "primary": primary, "primary_dark": primary_dark, "secondary": secondary,
            "accent": accent, "accent_dark": accent_dark,
            "background": background, "surface": surface, "surface_alt": surface_alt,
            "text_primary": text_primary, "text_secondary": text_secondary,
            "border": border,
            "success": "#1C7C4E" if not is_dark_mode else "#2FA36B",
            "success_dark": "#145B39" if not is_dark_mode else "#227B50",
            "danger": accent, "danger_dark": accent_dark,
            "on_primary": on_primary, "on_accent": on_accent,
        }
        for role in _REQUIRED_ROLES:
            theme.setdefault(role, THEME_LIGHT[role])
        return theme
    except Exception:
        # Never let a bad image crash the app; fall back to a safe default.
        return dict(THEME_LIGHT)


def detect_system_theme() -> str:
    """
    Best-effort detection of OS light/dark preference. Returns 'light' or
    'dark'. Always falls back safely to 'light' if detection is unavailable
    or fails for any reason (never raises, never crashes the app).
    """
    try:
        if sys.platform == "darwin":
            result = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0 and "dark" in result.stdout.strip().lower():
                return "dark"
            return "light"
        elif sys.platform.startswith("win"):
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return "dark" if value == 0 else "light"
        else:
            # Linux/other: try common desktop-portal / gsettings hints.
            try:
                result = subprocess.run(
                    ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                    capture_output=True, text=True, timeout=2,
                )
                if result.returncode == 0 and "dark" in result.stdout.strip().lower():
                    return "dark"
            except Exception:
                pass
            return "light"
    except Exception:
        return "light"


class ThemeManager(QObject):
    """
    Centralized theme controller. Owns the current color role dict,
    generates one consistent global stylesheet from it, applies it to the
    whole QApplication, and persists the user's choice to disk.

    Modes: 'light', 'dark', 'system', 'photo', 'brand:<PaletteName>'.
    """

    themeChanged = pyqtSignal()

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.mode: str = "light"
        self.photo_path: Optional[str] = None
        self.brand_palette_name: Optional[str] = None
        self.colors: Dict[str, str] = dict(THEME_LIGHT)
        self._load_settings()
        self.apply_theme()

    # -- Persistence ----------------------------------------------------
    def _load_settings(self) -> None:
        """Load saved theme choice. Any failure silently falls back to
        light mode so the app always launches successfully."""
        try:
            if SETTINGS_FILE.exists():
                data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                mode = data.get("theme_mode", "light")
                photo_path = data.get("photo_path")

                if mode == "photo" and photo_path and os.path.exists(photo_path):
                    self.mode = "photo"
                    self.photo_path = photo_path
                elif mode.startswith("brand:") and mode.split(":", 1)[1] in BRAND_PALETTES:
                    self.mode = mode
                    self.brand_palette_name = mode.split(":", 1)[1]
                elif mode in ("light", "dark", "system"):
                    self.mode = mode
                else:
                    self.mode = "light"
        except Exception:
            # Corrupted or unreadable settings file: use safe defaults.
            self.mode = "light"

    def _save_settings(self) -> None:
        try:
            SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "theme_mode": self.mode,
                "photo_path": self.photo_path,
                "brand_palette_name": self.brand_palette_name,
            }
            SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass  # Persistence is best-effort; never block the UI on it.

    # -- Theme resolution -------------------------------------------------
    def _resolve_colors(self) -> Dict[str, str]:
        try:
            if self.mode == "dark":
                return dict(THEME_DARK)
            if self.mode == "system":
                return dict(THEME_DARK) if detect_system_theme() == "dark" else dict(THEME_LIGHT)
            if self.mode == "photo" and self.photo_path and os.path.exists(self.photo_path):
                return build_theme_from_image(self.photo_path)
            if self.mode.startswith("brand:"):
                name = self.mode.split(":", 1)[1]
                if name in BRAND_PALETTES:
                    return dict(BRAND_PALETTES[name])
            return dict(THEME_LIGHT)
        except Exception:
            return dict(THEME_LIGHT)

    def set_mode(self, mode: str, photo_path: Optional[str] = None) -> None:
        self.mode = mode
        if mode == "photo" and photo_path:
            self.photo_path = photo_path
        if mode.startswith("brand:"):
            self.brand_palette_name = mode.split(":", 1)[1]
        self.apply_theme()
        self._save_settings()

    def apply_theme(self) -> None:
        self.colors = self._resolve_colors()
        stylesheet = self._build_stylesheet(self.colors)
        try:
            self.app.setStyleSheet(stylesheet)
        except Exception:
            pass
        self.themeChanged.emit()

    # -- Stylesheet generation -------------------------------------------
    @staticmethod
    def _build_stylesheet(c: Dict[str, str]) -> str:
        """
        One global stylesheet driven entirely by the color-role dict, so
        every widget class across both merged applications (main windows,
        frames, panels, labels, buttons, inputs, dropdowns, menus, tabs,
        lists/tables, scrollbars, dialogs, borders, hover/selected states)
        updates consistently on every theme switch.
        """
        return f"""
QMainWindow, QDialog {{
    background-color: {c['background']};
}}

QWidget#sidebar {{
    background-color: {c['primary_dark']};
}}

QLabel#sidebarTitle {{
    color: {c['on_primary']};
    font-size: 18px;
    font-weight: 700;
    padding: 18px 12px 4px 12px;
}}

QLabel#sidebarSubtitle {{
    color: {c['surface_alt']};
    font-size: 11px;
    padding: 0px 12px 16px 12px;
}}

QPushButton#navButton {{
    background-color: transparent;
    color: {c['on_primary']};
    text-align: left;
    padding: 12px 16px;
    font-size: 13px;
    font-weight: 600;
    border: none;
    border-left: 4px solid transparent;
}}

QPushButton#navButton:hover {{
    background-color: {c['primary']};
}}

QPushButton#navButton:checked {{
    background-color: {c['primary']};
    border-left: 4px solid {c['accent']};
}}

QWidget#contentArea, QWidget#CentralWidget {{
    background-color: {c['background']};
}}

QLabel#pageTitle {{
    color: {c['primary_dark']};
    font-size: 22px;
    font-weight: 800;
}}

QLabel#pageDescription {{
    color: {c['text_secondary']};
    font-size: 12px;
}}

QLabel#HeaderTitle {{
    color: {c['on_primary']};
    font-size: 18px;
    font-weight: 800;
    padding: 2px 8px;
}}

QLabel#HeaderSub {{
    color: {c['surface_alt']};
    font-size: 10px;
    padding: 0 8px;
}}

QLabel#PageLabel {{
    color: {c['on_primary']};
    font-weight: 700;
    font-size: 13px;
}}

QFrame#headerBar {{
    background-color: {c['surface_alt']};
    border-bottom: 3px solid {c['accent']};
}}

QFrame#Divider {{
    background-color: {c['border']};
    max-height: 1px;
}}

QGroupBox {{
    font-size: 12px;
    font-weight: 700;
    color: {c['primary_dark']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 10px;
    background-color: {c['surface']};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {c['primary']};
}}

QPushButton {{
    background-color: {c['primary']};
    color: {c['on_primary']};
    border: none;
    border-radius: 6px;
    padding: 8px 14px;
    font-weight: 600;
    font-size: 12px;
}}

QPushButton:hover {{
    background-color: {c['primary_dark']};
}}

QPushButton:pressed {{
    background-color: {c['accent_dark']};
}}

QPushButton:disabled {{
    background-color: {c['border']};
    color: {c['text_secondary']};
}}

QPushButton#primaryAction, QPushButton#DangerButton {{
    background-color: {c['accent']};
    color: {c['on_accent']};
    font-weight: 700;
    font-size: 13px;
    padding: 10px 18px;
    border-radius: 6px;
    border: none;
}}

QPushButton#primaryAction:hover, QPushButton#DangerButton:hover {{
    background-color: {c['accent_dark']};
}}

QPushButton#primaryAction:disabled {{
    background-color: {c['border']};
    color: {c['text_secondary']};
}}

QPushButton#secondaryAction {{
    background-color: {c['primary']};
    color: {c['on_primary']};
    font-weight: 600;
    font-size: 12px;
    padding: 8px 14px;
    border-radius: 6px;
    border: none;
}}

QPushButton#secondaryAction:hover {{
    background-color: {c['primary_dark']};
}}

QPushButton#plainAction {{
    background-color: {c['surface']};
    color: {c['primary']};
    font-weight: 600;
    font-size: 12px;
    padding: 8px 14px;
    border-radius: 6px;
    border: 1px solid {c['primary']};
}}

QPushButton#plainAction:hover {{
    background-color: {c['surface_alt']};
}}

QPushButton#SuccessButton {{
    background-color: {c['success']};
    color: {c['on_accent']};
}}

QPushButton#SuccessButton:hover {{
    background-color: {c['success_dark']};
}}

QToolBar {{
    background-color: {c['primary_dark']};
    border: none;
    padding: 6px;
    spacing: 6px;
}}

QToolBar QToolButton {{
    color: {c['on_primary']};
    background-color: {c['primary']};
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 600;
}}

QToolBar QToolButton:hover, QToolBar QToolButton:checked {{
    background-color: {c['accent']};
}}

QToolButton {{
    color: {c['text_primary']};
    background-color: transparent;
    border-radius: 5px;
    padding: 4px 8px;
}}

QToolButton:hover {{
    background-color: {c['surface_alt']};
}}

QToolButton::menu-indicator {{
    width: 12px;
}}

QMenu {{
    background-color: {c['surface']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    padding: 4px;
}}

QMenu::item {{
    padding: 6px 22px 6px 12px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background-color: {c['surface_alt']};
    color: {c['primary_dark']};
}}

QMenu::separator {{
    height: 1px;
    background-color: {c['border']};
    margin: 4px 6px;
}}

QStatusBar {{
    background-color: {c['primary_dark']};
    color: {c['on_primary']};
    font-weight: 500;
}}

QListWidget, QPlainTextEdit {{
    border: 1px solid {c['border']};
    border-radius: 6px;
    background-color: {c['surface']};
    padding: 4px;
    color: {c['text_primary']};
    font-size: 12px;
}}

QListWidget::item {{
    padding: 6px;
    border-bottom: 1px solid {c['surface_alt']};
}}

QListWidget::item:selected {{
    background-color: {c['surface_alt']};
    color: {c['primary_dark']};
}}

QLineEdit, QComboBox, QSpinBox {{
    border: 1px solid {c['border']};
    border-radius: 5px;
    padding: 6px 8px;
    font-size: 12px;
    background-color: {c['surface']};
    color: {c['text_primary']};
}}

QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
    border: 1.5px solid {c['primary']};
}}

QComboBox QAbstractItemView {{
    background-color: {c['surface']};
    color: {c['text_primary']};
    selection-background-color: {c['surface_alt']};
    border: 1px solid {c['border']};
}}

QCheckBox, QRadioButton {{
    color: {c['text_primary']};
    font-size: 12px;
    padding: 3px;
}}

QScrollArea {{
    background-color: {c['background']};
    border: none;
}}

QScrollBar:vertical {{
    background: {c['surface']};
    width: 12px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {c['border']};
    min-height: 24px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical:hover {{
    background: {c['secondary']};
}}

QScrollBar:horizontal {{
    background: {c['surface']};
    height: 12px;
}}

QScrollBar::handle:horizontal {{
    background: {c['border']};
    min-width: 24px;
    border-radius: 5px;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
}}

QTabWidget::pane {{
    border: 1px solid {c['border']};
    background-color: {c['surface']};
    border-radius: 6px;
}}

QTabBar::tab {{
    background-color: {c['surface_alt']};
    color: {c['primary_dark']};
    font-weight: 700;
    padding: 8px 16px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}}

QTabBar::tab:selected {{
    background-color: {c['primary']};
    color: {c['on_primary']};
}}

QProgressBar {{
    border: 1px solid {c['border']};
    border-radius: 5px;
    text-align: center;
    height: 16px;
    color: {c['text_primary']};
    background-color: {c['surface']};
}}

QProgressBar::chunk {{
    background-color: {c['accent']};
    border-radius: 5px;
}}

QLabel#statusLabel {{
    color: {c['primary_dark']};
    font-size: 11px;
    font-style: italic;
}}

QLabel#fieldLabel {{
    color: {c['text_primary']};
    font-size: 12px;
    font-weight: 600;
}}

QLabel {{
    color: {c['text_primary']};
}}

QLabel#TrialBadge {{
    color: {c['on_accent']};
    background-color: {c['accent']};
    font-weight: 700;
    font-size: 11px;
    padding: 4px 10px;
    border-radius: 10px;
}}
"""


# ---------------------------------------------------------------------------
# Section 4: Theme menu widget (Appearance dropdown)
# ---------------------------------------------------------------------------
class ThemeMenuButton(QToolButton):
    """
    A toolbar-style button exposing Light / Dark / System / Brand Palette /
    Photo-based theme choices through a dropdown menu. Reusable in any
    header bar across the merged application.
    """

    def __init__(self, theme_manager: "ThemeManager", parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.setText("Appearance")
        self.setPopupMode(QToolButton.InstantPopup)
        self.setCursor(Qt.PointingHandCursor)
        self._build_menu()

    def _build_menu(self):
        menu = QMenu(self)

        light_action = menu.addAction("Light")
        light_action.triggered.connect(lambda: self.theme_manager.set_mode("light"))

        dark_action = menu.addAction("Dark")
        dark_action.triggered.connect(lambda: self.theme_manager.set_mode("dark"))

        system_action = menu.addAction("Use System Theme (Auto)")
        system_action.triggered.connect(lambda: self.theme_manager.set_mode("system"))

        menu.addSeparator()

        brand_menu = menu.addMenu("Brand Palette")
        for palette_name in BRAND_PALETTES:
            action = brand_menu.addAction(palette_name)
            action.triggered.connect(
                lambda checked=False, name=palette_name: self.theme_manager.set_mode(f"brand:{name}")
            )

        menu.addSeparator()
        photo_action = menu.addAction("Generate Theme From Photo...")
        photo_action.triggered.connect(self._choose_photo)

        self.setMenu(menu)

    def _choose_photo(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Image for Theme",
            "", "Image Files (*.png *.jpg *.jpeg *.bmp *.webp)"
        )
        if not path:
            return
        if not HAS_PIL:
            QMessageBox.warning(
                self, "Pillow Required",
                "Photo-based theme generation requires the Pillow library, "
                "which could not be found. Please install it with:\n"
                "pip install Pillow"
            )
            return
        self.theme_manager.set_mode("photo", photo_path=path)


# ---------------------------------------------------------------------------
# Section 5: Trial Manager
# ---------------------------------------------------------------------------
# Clearly isolated so it can later be swapped for a real licensing/activation
# system without touching any other part of the application. Uses Qt's own
# timer mechanism (QTimer), never sleep(), so the event loop and UI never
# freeze during the countdown.
class TrialManager(QObject):
    """
    Gates the main application behind a fixed-length trial window.

    trialExpired is emitted exactly once, on the GUI thread, when the
    trial period ends. Consumers (MainWindow) should disable protected
    controls and show the expiry notice in response to this signal.
    """

    trialExpired = pyqtSignal()
    tick = pyqtSignal(int)  # seconds remaining

    TRIAL_SECONDS = 60

    def __init__(self, parent=None):
        super().__init__(parent)
        self._remaining = self.TRIAL_SECONDS
        self._expired = False
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

    def start(self) -> None:
        self._remaining = self.TRIAL_SECONDS
        self._expired = False
        self.tick.emit(self._remaining)
        self._timer.start()

    def _on_tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            self._remaining = 0
            self._timer.stop()
            self._expired = True
            self.tick.emit(self._remaining)
            self.trialExpired.emit()
        else:
            self.tick.emit(self._remaining)

    @property
    def is_expired(self) -> bool:
        return self._expired

    @property
    def remaining_seconds(self) -> int:
        return self._remaining


class TrialExpiredOverlay(QWidget):
    """
    A full-window overlay shown when the trial ends. Always stays on top
    of the main window's content (it is the topmost child, re-raised on
    every resize) so the expiry notice cannot be hidden behind other panels.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.Window, QColor(10, 12, 16, 235))
        self.setPalette(pal)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        message = QLabel("Trial period expired.\nPlease contact the administrator for further use.")
        message.setAlignment(Qt.AlignCenter)
        message.setStyleSheet(
            "color: #FFFFFF; font-size: 20px; font-weight: 800; padding: 24px;"
        )
        message.setWordWrap(True)

        close_btn = QPushButton("Close Application")
        close_btn.setObjectName("DangerButton")
        close_btn.setFixedWidth(220)
        close_btn.clicked.connect(lambda: QApplication.instance().quit())

        layout.addWidget(message)
        layout.addWidget(close_btn, alignment=Qt.AlignCenter)
        self.hide()

    def show_overlay(self):
        if self.parentWidget():
            self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()

# ---------------------------------------------------------------------------
# Section 6: Page-range parsing helper (shared by Split / Extract / Rearrange)
# ---------------------------------------------------------------------------
def parse_page_ranges(range_text, total_pages):
    """
    Parse a user-supplied page range string such as "1, 3-5, 8-10" into a
    list of 0-indexed page groups. Each group is a list of 0-indexed page
    numbers, preserving the order and grouping the user typed (used by
    Split, where each comma-separated token becomes its own output file).

    Returns: list of lists of int (0-indexed), e.g. [[0], [2,3,4], [7,8,9]]
    Raises: ValueError with a human-readable message if the input is invalid.
    """
    if not range_text or not range_text.strip():
        raise ValueError("Please enter at least one page or page range.")

    groups = []
    tokens = [t.strip() for t in range_text.split(",") if t.strip()]

    if not tokens:
        raise ValueError("Please enter at least one page or page range.")

    for token in tokens:
        if "-" in token:
            parts = token.split("-")
            if len(parts) != 2:
                raise ValueError(f"Invalid range format: '{token}'. Use e.g. 3-5.")
            start_str, end_str = parts[0].strip(), parts[1].strip()
            if not start_str.isdigit() or not end_str.isdigit():
                raise ValueError(f"Invalid range: '{token}'. Only whole numbers are allowed.")
            start, end = int(start_str), int(end_str)
            if start < 1 or end < 1:
                raise ValueError(f"Page numbers must be 1 or greater: '{token}'.")
            if start > end:
                raise ValueError(f"Invalid range: '{token}'. Start page is greater than end page.")
            if end > total_pages:
                raise ValueError(f"Page {end} is out of range. The PDF has {total_pages} pages.")
            groups.append(list(range(start - 1, end)))
        else:
            if not token.isdigit():
                raise ValueError(f"'{token}' is not a valid page number.")
            page = int(token)
            if page < 1 or page > total_pages:
                raise ValueError(f"Page {page} is out of range. The PDF has {total_pages} pages.")
            groups.append([page - 1])

    return groups


def flatten_groups(groups):
    """Flatten a list of page groups into a single ordered list of 0-indexed pages."""
    flat = []
    for g in groups:
        flat.extend(g)
    return flat


# ---------------------------------------------------------------------------
# Section 7: Reusable small widgets
# ---------------------------------------------------------------------------
class FileListPanel(QWidget):
    """A labeled list widget with Add / Remove / Move Up / Move Down / Clear
    controls, used for selecting one or more input PDFs (or images)."""

    def __init__(self, title="Selected Files", file_filter="PDF Files (*.pdf)",
                 allow_multiple=True, allow_reorder=True, parent=None):
        super().__init__(parent)
        self.file_filter = file_filter
        self.allow_multiple = allow_multiple

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel(title)
        label.setObjectName("fieldLabel")
        layout.addWidget(label)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.setMinimumHeight(160)
        layout.addWidget(self.list_widget)

        button_row = QHBoxLayout()
        self.btn_add = QPushButton("Add File(s)")
        self.btn_add.setObjectName("secondaryAction")
        self.btn_remove = QPushButton("Remove Selected")
        self.btn_remove.setObjectName("plainAction")
        self.btn_clear = QPushButton("Clear All")
        self.btn_clear.setObjectName("plainAction")
        button_row.addWidget(self.btn_add)
        button_row.addWidget(self.btn_remove)
        button_row.addWidget(self.btn_clear)
        layout.addLayout(button_row)

        if allow_reorder:
            move_row = QHBoxLayout()
            self.btn_up = QPushButton("Move Up")
            self.btn_up.setObjectName("plainAction")
            self.btn_down = QPushButton("Move Down")
            self.btn_down.setObjectName("plainAction")
            move_row.addWidget(self.btn_up)
            move_row.addWidget(self.btn_down)
            layout.addLayout(move_row)
            self.btn_up.clicked.connect(self._move_up)
            self.btn_down.clicked.connect(self._move_down)

        self.btn_add.clicked.connect(self._add_files)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear.clicked.connect(self.list_widget.clear)

    def _add_files(self):
        if self.allow_multiple:
            files, _ = QFileDialog.getOpenFileNames(self, "Select File(s)", "", self.file_filter)
        else:
            file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", self.file_filter)
            files = [file_path] if file_path else []
        for f in files:
            if f:
                self.list_widget.addItem(QListWidgetItem(f))

    def _remove_selected(self):
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))

    def _move_up(self):
        row = self.list_widget.currentRow()
        if row > 0:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row - 1, item)
            self.list_widget.setCurrentRow(row - 1)

    def _move_down(self):
        row = self.list_widget.currentRow()
        if row < self.list_widget.count() - 1 and row != -1:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row + 1, item)
            self.list_widget.setCurrentRow(row + 1)

    def get_files(self):
        return [self.list_widget.item(i).text() for i in range(self.list_widget.count())]


class OutputFolderPicker(QWidget):
    """A labeled row for choosing the output folder where results are saved."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel("Output Folder")
        label.setObjectName("fieldLabel")
        layout.addWidget(label)

        row = QHBoxLayout()
        self.path_field = QLineEdit()
        self.path_field.setPlaceholderText("Choose a folder to save the result...")
        self.path_field.setReadOnly(True)
        browse_btn = QPushButton("Browse...")
        browse_btn.setObjectName("secondaryAction")
        browse_btn.clicked.connect(self._browse)
        row.addWidget(self.path_field)
        row.addWidget(browse_btn)
        layout.addLayout(row)

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Output Folder")
        if folder:
            self.path_field.setText(folder)

    def get_path(self):
        return self.path_field.text().strip()


class StatusBarWidget(QWidget):
    """A small progress bar + status label combo shown at the bottom of each page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.progress.setVisible(False)
        layout.addWidget(self.status_label)
        layout.addWidget(self.progress)

    def set_status(self, text):
        self.status_label.setText(text)

    def start_busy(self, text="Working..."):
        self.set_status(text)
        self.progress.setRange(0, 0)  # indeterminate
        self.progress.setVisible(True)

    def stop_busy(self, text=""):
        self.progress.setRange(0, 1)
        self.progress.setValue(1)
        self.progress.setVisible(False)
        self.set_status(text)


# ---------------------------------------------------------------------------
# Section 8: Worker thread (keeps the UI responsive during PDF operations)
# ---------------------------------------------------------------------------
class WorkerThread(QThread):
    """Runs a given function in a background thread and reports success/failure."""

    finished_ok = pyqtSignal(str)
    finished_error = pyqtSignal(str)

    def __init__(self, task_function, *args, **kwargs):
        super().__init__()
        self.task_function = task_function
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            result_message = self.task_function(*self.args, **self.kwargs)
            self.finished_ok.emit(result_message or "Done.")
        except Exception as exc:
            self.finished_error.emit(str(exc))


# ---------------------------------------------------------------------------
# Section 9: Feature pages (Ahmedabad PDF Studio Pro tools)
# ---------------------------------------------------------------------------
class BasePage(QWidget):
    """Common scaffolding shared by every feature page: title, description,
    a content area for the page's own controls, and a status bar."""

    def __init__(self, title, description, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(24, 20, 24, 20)
        self.main_layout.setSpacing(14)

        title_label = QLabel(title)
        title_label.setObjectName("pageTitle")
        desc_label = QLabel(description)
        desc_label.setObjectName("pageDescription")
        desc_label.setWordWrap(True)

        self.main_layout.addWidget(title_label)
        self.main_layout.addWidget(desc_label)

        line = QFrame()
        line.setObjectName("Divider")
        line.setFrameShape(QFrame.HLine)
        self.main_layout.addWidget(line)

        self.body_layout = QVBoxLayout()
        self.body_layout.setSpacing(12)
        self.main_layout.addLayout(self.body_layout)
        self.main_layout.addStretch(1)

        self.status_widget = StatusBarWidget()
        self.main_layout.addWidget(self.status_widget)

        self.worker = None

    def run_in_background(self, task_function, *args, on_success=None, **kwargs):
        self.status_widget.start_busy("Working, please wait...")
        self.worker = WorkerThread(task_function, *args, **kwargs)

        def _on_ok(message):
            self.status_widget.stop_busy(message)
            QMessageBox.information(self, "Success", message)
            if on_success:
                on_success()

        def _on_error(message):
            self.status_widget.stop_busy("An error occurred.")
            QMessageBox.critical(self, "Error", message)

        self.worker.finished_ok.connect(_on_ok)
        self.worker.finished_error.connect(_on_error)
        self.worker.start()

    @staticmethod
    def unique_output_path(folder, filename):
        """Avoid silently overwriting an existing file by appending a counter if needed."""
        base, ext = os.path.splitext(filename)
        candidate = os.path.join(folder, filename)
        counter = 1
        while os.path.exists(candidate):
            candidate = os.path.join(folder, f"{base} ({counter}){ext}")
            counter += 1
        return candidate

# ---- 9.1 Merge PDFs --------------------------------------------------------
class MergePage(BasePage):
    def __init__(self, parent=None):
        super().__init__(
            "Merge PDF Files",
            "Combine multiple PDF files into a single PDF, in the order shown below. "
            "Use Move Up / Move Down to arrange the order before merging.",
            parent,
        )

        self.file_panel = FileListPanel(title="PDF Files to Merge (in order)", file_filter="PDF Files (*.pdf)")
        self.body_layout.addWidget(self.file_panel)

        self.output_picker = OutputFolderPicker()
        self.body_layout.addWidget(self.output_picker)

        name_row = QHBoxLayout()
        name_label = QLabel("Output File Name")
        name_label.setObjectName("fieldLabel")
        self.output_name = QLineEdit("Merged.pdf")
        name_row.addWidget(name_label)
        name_row.addWidget(self.output_name)
        self.body_layout.addLayout(name_row)

        self.merge_btn = QPushButton("Merge PDFs")
        self.merge_btn.setObjectName("primaryAction")
        self.merge_btn.clicked.connect(self.on_merge_clicked)
        self.body_layout.addWidget(self.merge_btn)

    def on_merge_clicked(self):
        files = self.file_panel.get_files()
        out_folder = self.output_picker.get_path()

        if len(files) < 2:
            QMessageBox.warning(self, "Not Enough Files", "Please add at least two PDF files to merge.")
            return
        if not out_folder:
            QMessageBox.warning(self, "Output Folder Required", "Please choose an output folder.")
            return

        out_name = self.output_name.text().strip() or "Merged.pdf"
        if not out_name.lower().endswith(".pdf"):
            out_name += ".pdf"
        out_path = self.unique_output_path(out_folder, out_name)

        self.run_in_background(self._merge_task, files, out_path)

    @staticmethod
    def _merge_task(files, out_path):
        writer = PdfWriter()
        for f in files:
            reader = PdfReader(f)
            for page in reader.pages:
                writer.add_page(page)
        with open(out_path, "wb") as out_file:
            writer.write(out_file)
        return f"Merged {len(files)} files successfully.\nSaved to: {out_path}"


# ---- 9.2 Split PDF ----------------------------------------------------------
class SplitPage(BasePage):
    def __init__(self, parent=None):
        super().__init__(
            "Split PDF",
            "Upload a PDF and enter the pages/ranges to split. Each comma-separated "
            "entry becomes its own output PDF. Example: 1, 3-5, 8-10 on a 10-page "
            "PDF creates three files.",
            parent,
        )

        self.file_panel = FileListPanel(
            title="PDF File to Split", file_filter="PDF Files (*.pdf)", allow_multiple=False, allow_reorder=False
        )
        self.body_layout.addWidget(self.file_panel)

        range_row = QVBoxLayout()
        range_label = QLabel("Pages / Ranges to Split (e.g. 1, 3-5, 8-10)")
        range_label.setObjectName("fieldLabel")
        self.range_input = QLineEdit()
        self.range_input.setPlaceholderText("e.g. 1, 3-5, 8-10")
        range_row.addWidget(range_label)
        range_row.addWidget(self.range_input)
        self.body_layout.addLayout(range_row)

        self.output_picker = OutputFolderPicker()
        self.body_layout.addWidget(self.output_picker)

        prefix_row = QHBoxLayout()
        prefix_label = QLabel("Output File Name Prefix")
        prefix_label.setObjectName("fieldLabel")
        self.prefix_input = QLineEdit("Split")
        prefix_row.addWidget(prefix_label)
        prefix_row.addWidget(self.prefix_input)
        self.body_layout.addLayout(prefix_row)

        self.split_btn = QPushButton("Split PDF")
        self.split_btn.setObjectName("primaryAction")
        self.split_btn.clicked.connect(self.on_split_clicked)
        self.body_layout.addWidget(self.split_btn)

    def on_split_clicked(self):
        files = self.file_panel.get_files()
        out_folder = self.output_picker.get_path()

        if not files:
            QMessageBox.warning(self, "File Required", "Please select a PDF file to split.")
            return
        if not out_folder:
            QMessageBox.warning(self, "Output Folder Required", "Please choose an output folder.")
            return

        input_path = files[0]

        try:
            reader = PdfReader(input_path)
            total_pages = len(reader.pages)
            groups = parse_page_ranges(self.range_input.text(), total_pages)
        except ValueError as ve:
            QMessageBox.warning(self, "Invalid Page Range", str(ve))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Error Reading PDF", str(exc))
            return

        prefix = self.prefix_input.text().strip() or "Split"
        self.run_in_background(self._split_task, input_path, groups, out_folder, prefix)

    def _split_task(self, input_path, groups, out_folder, prefix):
        reader = PdfReader(input_path)
        created_files = []
        for idx, group in enumerate(groups, start=1):
            writer = PdfWriter()
            for page_index in group:
                writer.add_page(reader.pages[page_index])
            file_name = f"{prefix}_Part{idx}.pdf"
            out_path = self.unique_output_path(out_folder, file_name)
            with open(out_path, "wb") as out_file:
                writer.write(out_file)
            created_files.append(os.path.basename(out_path))
        files_list = "\n".join(created_files)
        return f"Created {len(created_files)} file(s) in:\n{out_folder}\n\n{files_list}"


# ---- 9.3 Extract Pages -------------------------------------------------------
class ExtractPage(BasePage):
    def __init__(self, parent=None):
        super().__init__(
            "Extract Pages",
            "Upload a PDF and enter the pages/ranges you want to extract into a "
            "single new PDF. Example: 1, 3-5, 8-10 creates one file containing "
            "pages 1, 3, 4, 5, 8, 9, and 10 in that order.",
            parent,
        )

        self.file_panel = FileListPanel(
            title="PDF File to Extract From", file_filter="PDF Files (*.pdf)", allow_multiple=False, allow_reorder=False
        )
        self.body_layout.addWidget(self.file_panel)

        range_row = QVBoxLayout()
        range_label = QLabel("Pages / Ranges to Extract (e.g. 1, 3-5, 8-10)")
        range_label.setObjectName("fieldLabel")
        self.range_input = QLineEdit()
        self.range_input.setPlaceholderText("e.g. 1, 3-5, 8-10")
        range_row.addWidget(range_label)
        range_row.addWidget(self.range_input)
        self.body_layout.addLayout(range_row)

        self.output_picker = OutputFolderPicker()
        self.body_layout.addWidget(self.output_picker)

        name_row = QHBoxLayout()
        name_label = QLabel("Output File Name")
        name_label.setObjectName("fieldLabel")
        self.output_name = QLineEdit("Extracted.pdf")
        name_row.addWidget(name_label)
        name_row.addWidget(self.output_name)
        self.body_layout.addLayout(name_row)

        self.extract_btn = QPushButton("Extract Pages")
        self.extract_btn.setObjectName("primaryAction")
        self.extract_btn.clicked.connect(self.on_extract_clicked)
        self.body_layout.addWidget(self.extract_btn)

    def on_extract_clicked(self):
        files = self.file_panel.get_files()
        out_folder = self.output_picker.get_path()

        if not files:
            QMessageBox.warning(self, "File Required", "Please select a PDF file.")
            return
        if not out_folder:
            QMessageBox.warning(self, "Output Folder Required", "Please choose an output folder.")
            return

        input_path = files[0]

        try:
            reader = PdfReader(input_path)
            total_pages = len(reader.pages)
            groups = parse_page_ranges(self.range_input.text(), total_pages)
            page_indices = flatten_groups(groups)
        except ValueError as ve:
            QMessageBox.warning(self, "Invalid Page Range", str(ve))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Error Reading PDF", str(exc))
            return

        out_name = self.output_name.text().strip() or "Extracted.pdf"
        if not out_name.lower().endswith(".pdf"):
            out_name += ".pdf"
        out_path = self.unique_output_path(out_folder, out_name)

        self.run_in_background(self._extract_task, input_path, page_indices, out_path)

    @staticmethod
    def _extract_task(input_path, page_indices, out_path):
        reader = PdfReader(input_path)
        writer = PdfWriter()
        for page_index in page_indices:
            writer.add_page(reader.pages[page_index])
        with open(out_path, "wb") as out_file:
            writer.write(out_file)
        return f"Extracted {len(page_indices)} page(s) successfully.\nSaved to: {out_path}"


# ---- 9.4 Page Numbering -------------------------------------------------------
class PageNumberPage(BasePage):
    POSITIONS = ["Bottom Center", "Bottom Right", "Bottom Left", "Top Center", "Top Right", "Top Left"]
    FORMATS = ['"1"  (number only)', '"Page 1"', '"Page 1 of N"', '"1 / N"']

    def __init__(self, parent=None):
        super().__init__(
            "Add Page Numbers",
            "Upload a PDF and stamp page numbers on every page. Choose the position, "
            "the starting number, and the display format.",
            parent,
        )

        self.file_panel = FileListPanel(
            title="PDF File", file_filter="PDF Files (*.pdf)", allow_multiple=False, allow_reorder=False
        )
        self.body_layout.addWidget(self.file_panel)

        options_group = QGroupBox("Numbering Options")
        grid = QGridLayout(options_group)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(10)

        pos_label = QLabel("Position")
        pos_label.setObjectName("fieldLabel")
        self.position_combo = QComboBox()
        self.position_combo.addItems(self.POSITIONS)

        start_label = QLabel("Starting Page Number")
        start_label.setObjectName("fieldLabel")
        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 100000)
        self.start_spin.setValue(1)

        format_label = QLabel("Number Format")
        format_label.setObjectName("fieldLabel")
        self.format_combo = QComboBox()
        self.format_combo.addItems(self.FORMATS)

        grid.addWidget(pos_label, 0, 0)
        grid.addWidget(self.position_combo, 0, 1)
        grid.addWidget(start_label, 1, 0)
        grid.addWidget(self.start_spin, 1, 1)
        grid.addWidget(format_label, 2, 0)
        grid.addWidget(self.format_combo, 2, 1)

        self.body_layout.addWidget(options_group)

        self.output_picker = OutputFolderPicker()
        self.body_layout.addWidget(self.output_picker)

        name_row = QHBoxLayout()
        name_label = QLabel("Output File Name")
        name_label.setObjectName("fieldLabel")
        self.output_name = QLineEdit("Numbered.pdf")
        name_row.addWidget(name_label)
        name_row.addWidget(self.output_name)
        self.body_layout.addLayout(name_row)

        self.apply_btn = QPushButton("Add Page Numbers")
        self.apply_btn.setObjectName("primaryAction")
        self.apply_btn.clicked.connect(self.on_apply_clicked)
        self.body_layout.addWidget(self.apply_btn)

    def on_apply_clicked(self):
        files = self.file_panel.get_files()
        out_folder = self.output_picker.get_path()

        if not files:
            QMessageBox.warning(self, "File Required", "Please select a PDF file.")
            return
        if not out_folder:
            QMessageBox.warning(self, "Output Folder Required", "Please choose an output folder.")
            return

        input_path = files[0]
        out_name = self.output_name.text().strip() or "Numbered.pdf"
        if not out_name.lower().endswith(".pdf"):
            out_name += ".pdf"
        out_path = self.unique_output_path(out_folder, out_name)

        position = self.position_combo.currentText()
        start_number = self.start_spin.value()
        format_choice = self.format_combo.currentIndex()

        self.run_in_background(
            self._page_number_task, input_path, out_path, position, start_number, format_choice
        )

    @staticmethod
    def _format_label(format_choice, number, total):
        if format_choice == 0:
            return str(number)
        elif format_choice == 1:
            return f"Page {number}"
        elif format_choice == 2:
            return f"Page {number} of {total}"
        else:
            return f"{number} / {total}"

    @staticmethod
    def _position_coordinates(position, page_width, page_height, text_width, margin=36):
        if position == "Bottom Center":
            return (page_width - text_width) / 2, margin
        elif position == "Bottom Right":
            return page_width - text_width - margin, margin
        elif position == "Bottom Left":
            return margin, margin
        elif position == "Top Center":
            return (page_width - text_width) / 2, page_height - margin
        elif position == "Top Right":
            return page_width - text_width - margin, page_height - margin
        elif position == "Top Left":
            return margin, page_height - margin
        return (page_width - text_width) / 2, margin

    def _page_number_task(self, input_path, out_path, position, start_number, format_choice):
        reader = PdfReader(input_path)
        total_pages = len(reader.pages)
        writer = PdfWriter()

        for i, page in enumerate(reader.pages):
            page_width = float(page.mediabox.width)
            page_height = float(page.mediabox.height)

            current_number = start_number + i
            label_text = self._format_label(format_choice, current_number, total_pages)

            buffer = io.BytesIO()
            c = canvas.Canvas(buffer, pagesize=(page_width, page_height))
            c.setFont("Helvetica", 10)
            text_width = c.stringWidth(label_text, "Helvetica", 10)
            x, y = self._position_coordinates(position, page_width, page_height, text_width)
            c.drawString(x, y, label_text)
            c.save()
            buffer.seek(0)

            overlay_reader = PdfReader(buffer)
            overlay_page = overlay_reader.pages[0]
            page.merge_page(overlay_page)
            writer.add_page(page)

        with open(out_path, "wb") as out_file:
            writer.write(out_file)

        return f"Page numbers added to {total_pages} page(s) successfully.\nSaved to: {out_path}"


# ---- 9.5 Rearrange Pages ------------------------------------------------------
class RearrangePage(BasePage):
    def __init__(self, parent=None):
        super().__init__(
            "Rearrange Pages",
            "Upload a PDF and enter the new page order. Example: for a 10-page PDF, "
            "entering 3, 1, 2, 4-10 will reorder the pages accordingly. Every page "
            "from the original PDF must appear exactly once.",
            parent,
        )

        self.file_panel = FileListPanel(
            title="PDF File to Rearrange", file_filter="PDF Files (*.pdf)", allow_multiple=False, allow_reorder=False
        )
        self.body_layout.addWidget(self.file_panel)

        order_row = QVBoxLayout()
        order_label = QLabel("New Page Order (e.g. 3, 1, 2, 4-10)")
        order_label.setObjectName("fieldLabel")
        self.order_input = QLineEdit()
        self.order_input.setPlaceholderText("e.g. 3, 1, 2, 4-10")
        order_row.addWidget(order_label)
        order_row.addWidget(self.order_input)
        self.body_layout.addLayout(order_row)

        self.output_picker = OutputFolderPicker()
        self.body_layout.addWidget(self.output_picker)

        name_row = QHBoxLayout()
        name_label = QLabel("Output File Name")
        name_label.setObjectName("fieldLabel")
        self.output_name = QLineEdit("Rearranged.pdf")
        name_row.addWidget(name_label)
        name_row.addWidget(self.output_name)
        self.body_layout.addLayout(name_row)

        self.rearrange_btn = QPushButton("Rearrange Pages")
        self.rearrange_btn.setObjectName("primaryAction")
        self.rearrange_btn.clicked.connect(self.on_rearrange_clicked)
        self.body_layout.addWidget(self.rearrange_btn)

    def on_rearrange_clicked(self):
        files = self.file_panel.get_files()
        out_folder = self.output_picker.get_path()

        if not files:
            QMessageBox.warning(self, "File Required", "Please select a PDF file.")
            return
        if not out_folder:
            QMessageBox.warning(self, "Output Folder Required", "Please choose an output folder.")
            return

        input_path = files[0]

        try:
            reader = PdfReader(input_path)
            total_pages = len(reader.pages)
            groups = parse_page_ranges(self.order_input.text(), total_pages)
            new_order = flatten_groups(groups)

            if len(new_order) != total_pages:
                raise ValueError(
                    f"The new order must include all {total_pages} pages exactly once. "
                    f"You provided {len(new_order)} page reference(s)."
                )
            if sorted(new_order) != list(range(total_pages)):
                raise ValueError(
                    "Each page from the original PDF must appear exactly once, with no duplicates or omissions."
                )
        except ValueError as ve:
            QMessageBox.warning(self, "Invalid Page Order", str(ve))
            return
        except Exception as exc:
            QMessageBox.critical(self, "Error Reading PDF", str(exc))
            return

        out_name = self.output_name.text().strip() or "Rearranged.pdf"
        if not out_name.lower().endswith(".pdf"):
            out_name += ".pdf"
        out_path = self.unique_output_path(out_folder, out_name)

        self.run_in_background(self._rearrange_task, input_path, new_order, out_path)

    @staticmethod
    def _rearrange_task(input_path, new_order, out_path):
        reader = PdfReader(input_path)
        writer = PdfWriter()
        for page_index in new_order:
            writer.add_page(reader.pages[page_index])
        with open(out_path, "wb") as out_file:
            writer.write(out_file)
        return f"Pages rearranged successfully.\nSaved to: {out_path}"


# ---- 9.6 PDF <-> Image --------------------------------------------------------
class ConvertPage(BasePage):
    def __init__(self, parent=None):
        super().__init__(
            "PDF <-> Image Conversion",
            "Convert PDF pages into JPG or PNG images, or combine one or more "
            "images into a single PDF.",
            parent,
        )

        mode_group = QGroupBox("Conversion Mode")
        mode_layout = QHBoxLayout(mode_group)
        self.radio_pdf_to_img = QRadioButton("PDF to Images")
        self.radio_img_to_pdf = QRadioButton("Images to PDF")
        self.radio_pdf_to_img.setChecked(True)
        self.mode_button_group = QButtonGroup(self)
        self.mode_button_group.addButton(self.radio_pdf_to_img)
        self.mode_button_group.addButton(self.radio_img_to_pdf)
        mode_layout.addWidget(self.radio_pdf_to_img)
        mode_layout.addWidget(self.radio_img_to_pdf)
        self.body_layout.addWidget(mode_group)

        self.stack = QStackedWidget()

        # -- PDF to Images sub-page --
        pdf_to_img_widget = QWidget()
        pdf_to_img_layout = QVBoxLayout(pdf_to_img_widget)
        pdf_to_img_layout.setContentsMargins(0, 0, 0, 0)

        self.pdf_file_panel = FileListPanel(
            title="PDF File to Convert", file_filter="PDF Files (*.pdf)", allow_multiple=False, allow_reorder=False
        )
        pdf_to_img_layout.addWidget(self.pdf_file_panel)

        format_row = QHBoxLayout()
        format_label = QLabel("Image Format")
        format_label.setObjectName("fieldLabel")
        self.image_format_combo = QComboBox()
        self.image_format_combo.addItems(["PNG", "JPG"])
        format_row.addWidget(format_label)
        format_row.addWidget(self.image_format_combo)
        pdf_to_img_layout.addLayout(format_row)

        self.stack.addWidget(pdf_to_img_widget)

        # -- Images to PDF sub-page --
        img_to_pdf_widget = QWidget()
        img_to_pdf_layout = QVBoxLayout(img_to_pdf_widget)
        img_to_pdf_layout.setContentsMargins(0, 0, 0, 0)

        self.image_file_panel = FileListPanel(
            title="Image Files (in order)",
            file_filter="Image Files (*.png *.jpg *.jpeg *.bmp)",
            allow_multiple=True,
            allow_reorder=True,
        )
        img_to_pdf_layout.addWidget(self.image_file_panel)

        self.stack.addWidget(img_to_pdf_widget)

        self.body_layout.addWidget(self.stack)

        self.radio_pdf_to_img.toggled.connect(
            lambda checked: self.stack.setCurrentIndex(0) if checked else None
        )
        self.radio_img_to_pdf.toggled.connect(
            lambda checked: self.stack.setCurrentIndex(1) if checked else None
        )

        self.output_picker = OutputFolderPicker()
        self.body_layout.addWidget(self.output_picker)

        name_row = QHBoxLayout()
        name_label = QLabel("Output File Name (used only for Images to PDF)")
        name_label.setObjectName("fieldLabel")
        self.output_name = QLineEdit("Combined.pdf")
        name_row.addWidget(name_label)
        name_row.addWidget(self.output_name)
        self.body_layout.addLayout(name_row)

        self.convert_btn = QPushButton("Convert")
        self.convert_btn.setObjectName("primaryAction")
        self.convert_btn.clicked.connect(self.on_convert_clicked)
        self.body_layout.addWidget(self.convert_btn)

    def on_convert_clicked(self):
        out_folder = self.output_picker.get_path()
        if not out_folder:
            QMessageBox.warning(self, "Output Folder Required", "Please choose an output folder.")
            return

        if self.radio_pdf_to_img.isChecked():
            if not HAS_FITZ:
                QMessageBox.critical(
                    self, "Missing Library",
                    "PDF to Image conversion requires the PyMuPDF library (module name 'fitz'), "
                    "which could not be found. Please install it with:\npip install PyMuPDF"
                )
                return

            files = self.pdf_file_panel.get_files()
            if not files:
                QMessageBox.warning(self, "File Required", "Please select a PDF file to convert.")
                return

            image_format = self.image_format_combo.currentText().lower()
            self.run_in_background(self._pdf_to_images_task, files[0], out_folder, image_format)

        else:
            files = self.image_file_panel.get_files()
            if not files:
                QMessageBox.warning(self, "Files Required", "Please select at least one image file.")
                return
            if not HAS_PIL:
                QMessageBox.critical(
                    self, "Missing Library",
                    "Images to PDF conversion requires the Pillow library, which could not be "
                    "found. Please install it with:\npip install Pillow"
                )
                return

            out_name = self.output_name.text().strip() or "Combined.pdf"
            if not out_name.lower().endswith(".pdf"):
                out_name += ".pdf"
            out_path = self.unique_output_path(out_folder, out_name)
            self.run_in_background(self._images_to_pdf_task, files, out_path)

    @staticmethod
    def _pdf_to_images_task(input_path, out_folder, image_format):
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        doc = fitz.open(input_path)
        saved_files = []
        zoom_matrix = fitz.Matrix(2.0, 2.0)  # roughly 144 DPI for clear output

        for page_number in range(len(doc)):
            page = doc.load_page(page_number)
            pix = page.get_pixmap(matrix=zoom_matrix)
            file_name = f"{base_name}_page_{page_number + 1}.{image_format}"
            out_path = os.path.join(out_folder, file_name)
            counter = 1
            while os.path.exists(out_path):
                out_path = os.path.join(out_folder, f"{base_name}_page_{page_number + 1}_({counter}).{image_format}")
                counter += 1
            pix.save(out_path)
            saved_files.append(os.path.basename(out_path))

        doc.close()
        return f"Converted {len(saved_files)} page(s) to {image_format.upper()} images.\nSaved to: {out_folder}"

    @staticmethod
    def _images_to_pdf_task(image_paths, out_path):
        images = []
        for path in image_paths:
            img = Image.open(path)
            if img.mode != "RGB":
                img = img.convert("RGB")
            images.append(img)

        if not images:
            raise ValueError("No valid images were found to convert.")

        first_image, remaining_images = images[0], images[1:]
        first_image.save(out_path, save_all=True, append_images=remaining_images)
        return f"Combined {len(images)} image(s) into a single PDF.\nSaved to: {out_path}"


# ---- 9.7 Password Protect / Remove ---------------------------------------------
class PasswordPage(BasePage):
    def __init__(self, parent=None):
        super().__init__(
            "Password Protect / Remove Password",
            "Add a password to a PDF to restrict opening or editing, or remove an "
            "existing password when you already know it. This tool does not "
            "recover or crack unknown passwords.",
            parent,
        )

        mode_group = QGroupBox("Action")
        mode_layout = QHBoxLayout(mode_group)
        self.radio_add = QRadioButton("Add Password")
        self.radio_remove = QRadioButton("Remove Password")
        self.radio_add.setChecked(True)
        self.action_button_group = QButtonGroup(self)
        self.action_button_group.addButton(self.radio_add)
        self.action_button_group.addButton(self.radio_remove)
        mode_layout.addWidget(self.radio_add)
        mode_layout.addWidget(self.radio_remove)
        self.body_layout.addWidget(mode_group)

        self.file_panel = FileListPanel(
            title="PDF File", file_filter="PDF Files (*.pdf)", allow_multiple=False, allow_reorder=False
        )
        self.body_layout.addWidget(self.file_panel)

        self.stack = QStackedWidget()

        # -- Add password sub-page --
        add_widget = QWidget()
        add_layout = QGridLayout(add_widget)
        add_layout.setHorizontalSpacing(16)
        add_layout.setVerticalSpacing(10)

        user_pw_label = QLabel("New Password (to open the PDF)")
        user_pw_label.setObjectName("fieldLabel")
        self.user_password_input = QLineEdit()
        self.user_password_input.setEchoMode(QLineEdit.Password)

        confirm_pw_label = QLabel("Confirm Password")
        confirm_pw_label.setObjectName("fieldLabel")
        self.confirm_password_input = QLineEdit()
        self.confirm_password_input.setEchoMode(QLineEdit.Password)

        self.show_password_checkbox = QCheckBox("Show password")
        self.show_password_checkbox.toggled.connect(self._toggle_password_visibility)

        add_layout.addWidget(user_pw_label, 0, 0)
        add_layout.addWidget(self.user_password_input, 0, 1)
        add_layout.addWidget(confirm_pw_label, 1, 0)
        add_layout.addWidget(self.confirm_password_input, 1, 1)
        add_layout.addWidget(self.show_password_checkbox, 2, 1)

        self.stack.addWidget(add_widget)

        # -- Remove password sub-page --
        remove_widget = QWidget()
        remove_layout = QGridLayout(remove_widget)
        remove_layout.setHorizontalSpacing(16)
        remove_layout.setVerticalSpacing(10)

        current_pw_label = QLabel("Current Password (required)")
        current_pw_label.setObjectName("fieldLabel")
        self.current_password_input = QLineEdit()
        self.current_password_input.setEchoMode(QLineEdit.Password)

        self.show_current_password_checkbox = QCheckBox("Show password")
        self.show_current_password_checkbox.toggled.connect(
            lambda checked: self.current_password_input.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )

        remove_layout.addWidget(current_pw_label, 0, 0)
        remove_layout.addWidget(self.current_password_input, 0, 1)
        remove_layout.addWidget(self.show_current_password_checkbox, 1, 1)

        self.stack.addWidget(remove_widget)

        self.radio_add.toggled.connect(lambda checked: self.stack.setCurrentIndex(0) if checked else None)
        self.radio_remove.toggled.connect(lambda checked: self.stack.setCurrentIndex(1) if checked else None)

        self.body_layout.addWidget(self.stack)

        self.output_picker = OutputFolderPicker()
        self.body_layout.addWidget(self.output_picker)

        name_row = QHBoxLayout()
        name_label = QLabel("Output File Name")
        name_label.setObjectName("fieldLabel")
        self.output_name = QLineEdit("Output.pdf")
        name_row.addWidget(name_label)
        name_row.addWidget(self.output_name)
        self.body_layout.addLayout(name_row)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setObjectName("primaryAction")
        self.apply_btn.clicked.connect(self.on_apply_clicked)
        self.body_layout.addWidget(self.apply_btn)

    def _toggle_password_visibility(self, checked):
        mode = QLineEdit.Normal if checked else QLineEdit.Password
        self.user_password_input.setEchoMode(mode)
        self.confirm_password_input.setEchoMode(mode)

    def on_apply_clicked(self):
        files = self.file_panel.get_files()
        out_folder = self.output_picker.get_path()

        if not files:
            QMessageBox.warning(self, "File Required", "Please select a PDF file.")
            return
        if not out_folder:
            QMessageBox.warning(self, "Output Folder Required", "Please choose an output folder.")
            return

        input_path = files[0]
        out_name = self.output_name.text().strip() or "Output.pdf"
        if not out_name.lower().endswith(".pdf"):
            out_name += ".pdf"
        out_path = self.unique_output_path(out_folder, out_name)

        if self.radio_add.isChecked():
            password = self.user_password_input.text()
            confirm = self.confirm_password_input.text()
            if not password:
                QMessageBox.warning(self, "Password Required", "Please enter a password.")
                return
            if password != confirm:
                QMessageBox.warning(self, "Password Mismatch", "The password and confirmation do not match.")
                return
            self.run_in_background(self._add_password_task, input_path, out_path, password)
        else:
            current_password = self.current_password_input.text()
            if not current_password:
                QMessageBox.warning(self, "Password Required", "Please enter the current password.")
                return
            self.run_in_background(self._remove_password_task, input_path, out_path, current_password)

    @staticmethod
    def _add_password_task(input_path, out_path, password):
        try:
            reader = PdfReader(input_path)
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            # AES-256 is the modern, strong standard supported by all current
            # PDF readers. This requires the "cryptography" package, which is
            # included in this app's auto-installed dependencies.
            writer.encrypt(password, algorithm="AES-256")
            with open(out_path, "wb") as out_file:
                writer.write(out_file)
        except Exception as exc:
            if "cryptography" in str(exc).lower():
                raise RuntimeError(
                    "The 'cryptography' library is required to add a password and could "
                    "not be found. Please close the app and run:\n"
                    "pip install cryptography\nthen restart the application."
                ) from exc
            raise
        return f"Password protection added successfully.\nSaved to: {out_path}"

    @staticmethod
    def _remove_password_task(input_path, out_path, password):
        try:
            reader = PdfReader(input_path)
            if reader.is_encrypted:
                result = reader.decrypt(password)
                if result == 0:
                    raise ValueError("The password entered is incorrect. Please check and try again.")
            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            with open(out_path, "wb") as out_file:
                writer.write(out_file)
        except ValueError:
            raise
        except Exception as exc:
            if "cryptography" in str(exc).lower():
                raise RuntimeError(
                    "The 'cryptography' library is required to open this password-protected "
                    "PDF and could not be found. Please close the app and run:\n"
                    "pip install cryptography\nthen restart the application."
                ) from exc
            raise
        return f"Password removed successfully.\nSaved to: {out_path}"


# ---- 9.8 Home / Welcome page ----------------------------------------------------
class HomePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(10)

        title = QLabel("Welcome to Ahmedabad PDF Studio Pro")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        subtitle = QLabel(
            "A complete, professional PDF toolkit for merging, splitting, extracting, "
            "numbering, rearranging, converting, securing, and redacting your PDF documents.\n\n"
            "Select a tool from the menu on the left to get started."
        )
        subtitle.setObjectName("pageDescription")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        features_group = QGroupBox("Available Tools")
        features_layout = QVBoxLayout(features_group)
        feature_names = [
            "Merge PDF - combine multiple PDFs into one",
            "Split PDF - split by pages/ranges into separate files",
            "Extract Pages - pull selected pages into one new PDF",
            "Add Page Numbers - stamp page numbers with custom position and format",
            "Rearrange Pages - reorder pages exactly as you specify",
            "PDF <-> Image - convert PDF pages to images, or images into a PDF",
            "Password Protect / Remove - secure or unlock a PDF using a known password",
            "Redaction Studio - manual, find-and-redact, and smart auto-detect redaction "
            "with true content-stream removal",
        ]
        for name in feature_names:
            item_label = QLabel(f"-  {name}")
            item_label.setObjectName("pageDescription")
            features_layout.addWidget(item_label)
        layout.addWidget(features_group)
        layout.addStretch(1)


# ---------------------------------------------------------------------------
# Section 10: Redaction Studio (from PDF Redaction Tool)
# ---------------------------------------------------------------------------
# Verhoeff checksum algorithm (used to validate Aadhaar-like 12-digit numbers
# and reduce false positives versus a plain 12-digit regex)
_VERHOEFF_D = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 2, 3, 4, 0, 6, 7, 8, 9, 5],
    [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
    [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
    [4, 0, 1, 2, 3, 9, 5, 6, 7, 8],
    [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
    [6, 5, 9, 8, 7, 1, 0, 4, 3, 2],
    [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
    [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
    [9, 8, 7, 6, 5, 4, 3, 2, 1, 0],
]
_VERHOEFF_P = [
    [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    [1, 5, 7, 6, 2, 8, 3, 0, 9, 4],
    [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
    [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
    [9, 4, 5, 3, 1, 2, 6, 8, 7, 0],
    [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
    [2, 7, 9, 3, 8, 0, 6, 4, 1, 5],
    [7, 0, 4, 6, 9, 1, 3, 2, 5, 8],
]


def verhoeff_validate(number_str: str) -> bool:
    """Return True if the digit string passes the Verhoeff checksum."""
    if not number_str.isdigit():
        return False
    c = 0
    for i, item in enumerate(reversed(number_str)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(item)]]
    return c == 0


# Pattern definitions for Smart Redaction
PATTERN_PAN = re.compile(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b')
PATTERN_AADHAAR = re.compile(r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b')
PATTERN_EMAIL = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
PATTERN_MOBILE = re.compile(r'(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)')
PATTERN_BANK_ACCOUNT = re.compile(r'\b\d{9,18}\b')

SMART_CATEGORIES = [
    "PAN Number",
    "Aadhaar Number",
    "Email Address",
    "Mobile Number",
    "Bank Account Number",
]


def find_smart_candidates(text: str) -> List[Tuple[str, str, Tuple[int, int]]]:
    """
    Scan raw page text and return a list of (category, matched_string, span)
    tuples for everything that looks like a sensitive structured identifier.
    Aadhaar candidates are Verhoeff-validated to cut down false positives;
    plain 12-digit numbers that fail the checksum are not flagged as
    Aadhaar (they may still be flagged as bank account numbers if they fit
    that length range).
    """
    results = []
    consumed_spans = []

    def overlaps(a, b):
        return not (a[1] <= b[0] or b[1] <= a[0])

    # PAN - highest specificity, check first
    for m in PATTERN_PAN.finditer(text):
        results.append(("PAN Number", m.group(), m.span()))
        consumed_spans.append(m.span())

    # Email
    for m in PATTERN_EMAIL.finditer(text):
        results.append(("Email Address", m.group(), m.span()))
        consumed_spans.append(m.span())

    # Aadhaar (12 digits with optional spacing) - Verhoeff validated
    for m in PATTERN_AADHAAR.finditer(text):
        span = m.span()
        if any(overlaps(span, cs) for cs in consumed_spans):
            continue
        digits_only = re.sub(r'[\s-]', '', m.group())
        if len(digits_only) == 12 and verhoeff_validate(digits_only):
            results.append(("Aadhaar Number", m.group(), span))
            consumed_spans.append(span)

    # Mobile number (10 digits starting 6-9, optional +91)
    for m in PATTERN_MOBILE.finditer(text):
        span = m.span()
        if any(overlaps(span, cs) for cs in consumed_spans):
            continue
        results.append(("Mobile Number", m.group(), span))
        consumed_spans.append(span)

    # Bank account number (9-18 digit run) - only flag if not already
    # claimed by PAN/Aadhaar/mobile and length differs from a validated
    # Aadhaar/mobile so we don't double flag.
    for m in PATTERN_BANK_ACCOUNT.finditer(text):
        span = m.span()
        if any(overlaps(span, cs) for cs in consumed_spans):
            continue
        digits_only = m.group()
        if len(digits_only) == 12 and verhoeff_validate(digits_only):
            continue
        results.append(("Bank Account Number", m.group(), span))
        consumed_spans.append(span)

    return results


@dataclass
class RedactionMark:
    page_index: int
    rect: "fitz.Rect"           # coordinates in PDF point space
    source: str = "manual"      # 'manual' | 'find' | 'smart'
    label: str = ""             # optional description


class RedactionEngine:
    """
    Wraps a PyMuPDF document and provides:
      - page rendering to QPixmap
      - text search
      - true redaction: removes underlying text objects from the content
        stream and rasterizes only the redacted rectangle, leaving the
        rest of the page as live text.
    """

    def __init__(self):
        self.doc: Optional["fitz.Document"] = None
        self.file_path: Optional[str] = None
        self.page_count: int = 0

    def open(self, file_path: str):
        self.close()
        self.doc = fitz.open(file_path)
        if self.doc.needs_pass:
            raise ValueError(
                "This PDF is password protected. Please remove the "
                "password before redacting, then try again."
            )
        self.file_path = file_path
        self.page_count = self.doc.page_count

    def close(self):
        if self.doc is not None:
            try:
                self.doc.close()
            except Exception:
                pass
        self.doc = None
        self.file_path = None
        self.page_count = 0

    def is_open(self) -> bool:
        return self.doc is not None

    def get_page(self, index: int):
        return self.doc[index]

    def render_page(self, index: int, zoom: float) -> QImage:
        page = self.doc[index]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        fmt = QImage.Format_RGB888
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
        return img.copy()  # detach from pix buffer before pix is gc'd

    def search_text(self, index: int, needle: str) -> List["fitz.Rect"]:
        if not needle:
            return []
        page = self.doc[index]
        try:
            return page.search_for(needle, quads=False)
        except Exception:
            return []

    def search_text_all_pages(self, needle: str):
        """Returns dict {page_index: [rects]} across the whole document."""
        results = {}
        if not needle:
            return results
        for i in range(self.page_count):
            rects = self.search_text(i, needle)
            if rects:
                results[i] = rects
        return results

    def get_page_text(self, index: int) -> str:
        return self.doc[index].get_text("text")

    def apply_redactions_to_document(self, marks: List[RedactionMark], output_path: str):
        """
        Applies every mark's rectangle as a true PyMuPDF redaction: the
        underlying text/content within the rect is permanently deleted
        from the content stream, and the area is filled (rasterized as a
        solid black box) so no trace remains. Marks are grouped per page
        for efficiency, then the whole document is saved to a NEW file
        (the original stays untouched).
        """
        if self.doc is None:
            raise RuntimeError("No document is open.")

        by_page = {}
        for m in marks:
            by_page.setdefault(m.page_index, []).append(m.rect)

        for page_index, rects in by_page.items():
            page = self.doc[page_index]
            for rect in rects:
                page.add_redact_annot(rect, fill=(0, 0, 0))
            try:
                page.apply_redactions(
                    images=fitz.PDF_REDACT_IMAGE_REMOVE,
                    graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                )
            except (AttributeError, TypeError):
                # Older PyMuPDF versions: fall back to default behaviour
                page.apply_redactions()

        # Save as a brand new file. garbage=4 fully rebuilds and compacts
        # the PDF, purging orphaned/unreferenced objects (including any
        # leftover text-showing operators) so nothing recoverable is left
        # behind. deflate reduces file size.
        self.doc.save(output_path, garbage=4, deflate=True, clean=True)


class PageCanvas(QLabel):
    """Displays the rendered page and lets the user draw rectangles with
    the mouse to mark manual redactions."""

    rectangleDrawn = pyqtSignal(QRect)  # emits in WIDGET pixel coordinates

    def __init__(self, theme_manager: "ThemeManager", parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.setAlignment(Qt.AlignCenter)
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.base_pixmap: Optional[QPixmap] = None
        self._drawing = False
        self._start_point = QPointF()
        self._current_point = QPointF()
        self.pending_rects: List[QRectF] = []
        self.manual_mode_enabled = True
        self.setStyleSheet("background-color: white;")

    def set_page_pixmap(self, pixmap: QPixmap):
        self.base_pixmap = pixmap
        self.setPixmap(pixmap)
        self.setFixedSize(pixmap.size())
        self.update()

    def set_pending_rects(self, rects: List[QRectF]):
        self.pending_rects = rects
        self.update()

    def mousePressEvent(self, event):
        if not self.manual_mode_enabled or self.base_pixmap is None:
            return
        if event.button() == Qt.LeftButton:
            self._drawing = True
            self._start_point = event.pos()
            self._current_point = event.pos()
            self.update()

    def mouseMoveEvent(self, event):
        if self._drawing:
            self._current_point = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if self._drawing and event.button() == Qt.LeftButton:
            self._drawing = False
            rect = QRect(self._start_point.toPoint(), self._current_point.toPoint()).normalized()
            if rect.width() > 4 and rect.height() > 4:
                self.rectangleDrawn.emit(rect)
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        accent = QColor(self.theme_manager.colors["accent"])
        mark_fill = QColor(accent.red(), accent.green(), accent.blue(), 110)
        mark_border = QColor(accent.darker(120).red(), accent.darker(120).green(),
                              accent.darker(120).blue(), 230)

        pen = QPen(mark_border)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(QBrush(mark_fill))
        for r in self.pending_rects:
            painter.drawRect(r)

        if self._drawing:
            live_rect = QRect(self._start_point.toPoint(), self._current_point.toPoint()).normalized()
            pen2 = QPen(accent)
            pen2.setWidth(2)
            pen2.setStyle(Qt.DashLine)
            painter.setPen(pen2)
            live_fill = QColor(accent.red(), accent.green(), accent.blue(), 60)
            painter.setBrush(QBrush(live_fill))
            painter.drawRect(live_rect)

        painter.end()


class RedactionStudioPage(QWidget):
    """
    Redaction Studio: manual / find-and-redact / smart-redaction, embedded
    as one page in the shared sidebar navigation. Internally organized the
    same way as the original standalone Redaction Tool window (left tool
    tabs + center page viewer + status bar), just adapted to live inside
    a QStackedWidget page instead of owning its own QMainWindow.
    """

    def __init__(self, theme_manager: "ThemeManager", parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.engine = RedactionEngine()
        self.current_page_index = 0
        self.zoom_level = 1.4
        self.base_dpi_zoom = 1.4

        # marks[page_index] = list of RedactionMark (rect in PDF point space)
        self.marks_by_page: Dict[int, List[RedactionMark]] = {}
        self.undo_stack = []
        self.render_scale = self.zoom_level

        self._build_ui()
        self._apply_shortcuts()
        self.setAcceptDrops(True)
        self.theme_manager.themeChanged.connect(self._on_theme_changed)

    # ------------------------------------------------------------------
    def _on_theme_changed(self):
        if self.engine.is_open():
            self.canvas.update()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # ---- Header bar ----
        header = QFrame()
        header.setObjectName("headerBar")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        title_box = QVBoxLayout()
        title_label = QLabel("Redaction Studio")
        title_label.setObjectName("pageTitle")
        sub_label = QLabel("Secure offline PDF redaction — content is permanently removed, not just covered")
        sub_label.setObjectName("pageDescription")
        title_box.addWidget(title_label)
        title_box.addWidget(sub_label)
        header_layout.addLayout(title_box)
        header_layout.addStretch()

        self.open_btn = QPushButton("Open PDF")
        self.open_btn.setObjectName("secondaryAction")
        self.open_btn.clicked.connect(self.open_pdf)
        self.save_btn = QPushButton("Save Redacted PDF")
        self.save_btn.setObjectName("SuccessButton")
        self.save_btn.clicked.connect(self.save_redacted_pdf)
        self.save_btn.setEnabled(False)
        header_layout.addWidget(self.open_btn)
        header_layout.addWidget(self.save_btn)
        outer_layout.addWidget(header)

        # ---- Body splitter ----
        body_splitter = QSplitter(Qt.Horizontal)
        outer_layout.addWidget(body_splitter, 1)

        left_panel = self._build_left_panel()
        left_panel.setMinimumWidth(360)
        left_panel.setMaximumWidth(430)
        body_splitter.addWidget(left_panel)

        center_panel = self._build_center_panel()
        body_splitter.addWidget(center_panel)

        body_splitter.setStretchFactor(0, 0)
        body_splitter.setStretchFactor(1, 1)

        self.status = QStatusBar()
        outer_layout.addWidget(self.status)
        self.status.showMessage("Ready. Open a PDF to begin.")

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # --- Manual tab ---
        manual_tab = QWidget()
        manual_layout = QVBoxLayout(manual_tab)
        manual_group = QGroupBox("Manual Redaction")
        mg_layout = QVBoxLayout(manual_group)
        mg_info = QLabel(
            "Click and drag on the page to mark a region for redaction.\n"
            "Marked regions appear in translucent accent color until applied."
        )
        mg_info.setWordWrap(True)
        mg_info.setObjectName("pageDescription")
        mg_layout.addWidget(mg_info)

        self.manual_marks_list = QListWidget()
        mg_layout.addWidget(QLabel("Marks on current page:"))
        mg_layout.addWidget(self.manual_marks_list)

        btn_row = QHBoxLayout()
        self.undo_btn = QPushButton("Undo Last")
        self.undo_btn.setObjectName("plainAction")
        self.undo_btn.clicked.connect(self.undo_last_action)
        self.clear_page_btn = QPushButton("Clear Page Marks")
        self.clear_page_btn.setObjectName("DangerButton")
        self.clear_page_btn.clicked.connect(self.clear_current_page_marks)
        btn_row.addWidget(self.undo_btn)
        btn_row.addWidget(self.clear_page_btn)
        mg_layout.addLayout(btn_row)

        manual_layout.addWidget(manual_group)
        manual_layout.addStretch()
        self.tabs.addTab(manual_tab, "Manual")

        # --- Find & Redact tab ---
        find_tab = QWidget()
        find_layout = QVBoxLayout(find_tab)
        find_group = QGroupBox("Find and Redact Text")
        fg_layout = QVBoxLayout(find_group)
        fg_layout.addWidget(QLabel("Search text (e.g. a name, PAN, account #):"))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Type text to find across the document...")
        fg_layout.addWidget(self.search_input)

        search_btn_row = QHBoxLayout()
        self.search_btn = QPushButton("Search Document")
        self.search_btn.setObjectName("secondaryAction")
        self.search_btn.clicked.connect(self.run_find_search)
        search_btn_row.addWidget(self.search_btn)
        fg_layout.addLayout(search_btn_row)

        self.find_results_list = QListWidget()
        self.find_results_list.setSelectionMode(QAbstractItemView.NoSelection)
        fg_layout.addWidget(QLabel("Matches found (check to include):"))
        fg_layout.addWidget(self.find_results_list)

        find_action_row = QHBoxLayout()
        self.mark_found_btn = QPushButton("Mark Checked Matches")
        self.mark_found_btn.setObjectName("secondaryAction")
        self.mark_found_btn.clicked.connect(self.mark_checked_find_matches)
        find_action_row.addWidget(self.mark_found_btn)
        fg_layout.addLayout(find_action_row)

        find_layout.addWidget(find_group)
        find_layout.addStretch()
        self.tabs.addTab(find_tab, "Find && Redact")

        # --- Smart Redaction tab ---
        smart_tab = QWidget()
        smart_layout = QVBoxLayout(smart_tab)
        smart_group = QGroupBox("Smart Redaction (Auto-Detect)")
        sg_layout = QVBoxLayout(smart_group)
        sg_info = QLabel(
            "Scans the document for PAN, Aadhaar (Verhoeff validated), "
            "bank account numbers, email addresses and mobile numbers. "
            "Nothing is redacted until you review and confirm below."
        )
        sg_info.setWordWrap(True)
        sg_info.setObjectName("pageDescription")
        sg_layout.addWidget(sg_info)

        cat_grid = QGridLayout()
        self.category_checks = {}
        for i, cat in enumerate(SMART_CATEGORIES):
            cb = QCheckBox(cat)
            cb.setChecked(True)
            self.category_checks[cat] = cb
            cat_grid.addWidget(cb, i // 2, i % 2)
        sg_layout.addLayout(cat_grid)

        self.scan_btn = QPushButton("Scan Document")
        self.scan_btn.setObjectName("secondaryAction")
        self.scan_btn.clicked.connect(self.run_smart_scan)
        sg_layout.addWidget(self.scan_btn)

        sg_layout.addWidget(QLabel("Detected candidates (review before applying):"))
        self.smart_results_list = QListWidget()
        self.smart_results_list.setSelectionMode(QAbstractItemView.NoSelection)
        sg_layout.addWidget(self.smart_results_list)

        smart_action_row = QHBoxLayout()
        self.select_all_smart_btn = QPushButton("Select All")
        self.select_all_smart_btn.setObjectName("plainAction")
        self.select_all_smart_btn.clicked.connect(lambda: self._toggle_all_smart(True))
        self.deselect_all_smart_btn = QPushButton("Deselect All")
        self.deselect_all_smart_btn.setObjectName("plainAction")
        self.deselect_all_smart_btn.clicked.connect(lambda: self._toggle_all_smart(False))
        smart_action_row.addWidget(self.select_all_smart_btn)
        smart_action_row.addWidget(self.deselect_all_smart_btn)
        sg_layout.addLayout(smart_action_row)

        self.mark_smart_btn = QPushButton("Mark Checked Candidates")
        self.mark_smart_btn.setObjectName("secondaryAction")
        self.mark_smart_btn.clicked.connect(self.mark_checked_smart_matches)
        sg_layout.addWidget(self.mark_smart_btn)

        smart_layout.addWidget(smart_group)
        smart_layout.addStretch()
        self.tabs.addTab(smart_tab, "Smart Redaction")

        # --- Apply section (always visible under tabs) ---
        apply_group = QGroupBox("Apply")
        apply_layout = QVBoxLayout(apply_group)
        self.total_marks_label = QLabel("Total pending marks (all pages): 0")
        self.total_marks_label.setObjectName("fieldLabel")
        apply_layout.addWidget(self.total_marks_label)
        self.apply_all_btn = QPushButton("Apply All Redactions and Save New PDF")
        self.apply_all_btn.setObjectName("DangerButton")
        self.apply_all_btn.clicked.connect(self.save_redacted_pdf)
        self.apply_all_btn.setEnabled(False)
        apply_layout.addWidget(self.apply_all_btn)
        layout.addWidget(apply_group)

        return panel

    def _build_center_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        nav_bar = QFrame()
        nav_bar.setObjectName("headerBar")
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(10, 6, 10, 6)

        self.prev_btn = QPushButton("<  Previous")
        self.prev_btn.setObjectName("plainAction")
        self.prev_btn.clicked.connect(self.go_prev_page)
        self.next_btn = QPushButton("Next  >")
        self.next_btn.setObjectName("plainAction")
        self.next_btn.clicked.connect(self.go_next_page)

        self.page_indicator = QLabel("0 / 0")
        self.page_indicator.setObjectName("fieldLabel")
        self.page_indicator.setAlignment(Qt.AlignCenter)
        self.page_indicator.setMinimumWidth(70)

        self.jump_input = QLineEdit()
        self.jump_input.setPlaceholderText("Page #")
        self.jump_input.setFixedWidth(70)
        self.jump_input.returnPressed.connect(self.jump_to_page)
        self.jump_btn = QPushButton("Go")
        self.jump_btn.setObjectName("plainAction")
        self.jump_btn.clicked.connect(self.jump_to_page)

        self.zoom_out_btn = QPushButton("Zoom -")
        self.zoom_out_btn.setObjectName("plainAction")
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        self.zoom_in_btn = QPushButton("Zoom +")
        self.zoom_in_btn.setObjectName("plainAction")
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        self.zoom_label = QLabel("100%")
        self.zoom_label.setObjectName("fieldLabel")

        nav_layout.addWidget(self.prev_btn)
        nav_layout.addWidget(self.page_indicator)
        nav_layout.addWidget(self.next_btn)
        nav_layout.addSpacing(20)
        nav_layout.addWidget(QLabel("Go to:"))
        nav_layout.addWidget(self.jump_input)
        nav_layout.addWidget(self.jump_btn)
        nav_layout.addStretch()
        nav_layout.addWidget(self.zoom_out_btn)
        nav_layout.addWidget(self.zoom_label)
        nav_layout.addWidget(self.zoom_in_btn)

        layout.addWidget(nav_bar)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.canvas = PageCanvas(self.theme_manager)
        self.canvas.rectangleDrawn.connect(self.on_manual_rectangle_drawn)
        self.scroll_area.setWidget(self.canvas)
        layout.addWidget(self.scroll_area, 1)

        return panel

    def _apply_shortcuts(self):
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo_last_action)
        QShortcut(QKeySequence("Ctrl+Shift+O"), self, activated=self.open_pdf)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=self.save_redacted_pdf)

    # ------------------------------------------------------------------
    # File handling
    # ------------------------------------------------------------------
    def open_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF Files (*.pdf)")
        if not path:
            return
        try:
            self.engine.open(path)
        except Exception as exc:
            QMessageBox.critical(self, "Could Not Open PDF", str(exc))
            return

        self.marks_by_page = {}
        self.undo_stack = []
        self.current_page_index = 0
        self.find_results_list.clear()
        self.smart_results_list.clear()
        self.save_btn.setEnabled(True)
        self.apply_all_btn.setEnabled(True)
        self.status.showMessage("Opened: {}".format(os.path.basename(path)))
        self.render_current_page()
        self.update_total_marks_label()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if url.toLocalFile().lower().endswith(".pdf"):
                    event.acceptProposedAction()
                    return

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local.lower().endswith(".pdf"):
                try:
                    self.engine.open(local)
                    self.marks_by_page = {}
                    self.undo_stack = []
                    self.current_page_index = 0
                    self.save_btn.setEnabled(True)
                    self.apply_all_btn.setEnabled(True)
                    self.status.showMessage("Opened: {}".format(os.path.basename(local)))
                    self.render_current_page()
                    self.update_total_marks_label()
                except Exception as exc:
                    QMessageBox.critical(self, "Could Not Open PDF", str(exc))
                break

    # ------------------------------------------------------------------
    # Rendering / navigation
    # ------------------------------------------------------------------
    def render_current_page(self):
        if not self.engine.is_open():
            return
        try:
            img = self.engine.render_page(self.current_page_index, self.zoom_level)
        except Exception as exc:
            QMessageBox.critical(self, "Render Error", str(exc))
            return

        pixmap = QPixmap.fromImage(img)
        self.canvas.set_page_pixmap(pixmap)
        self.render_scale = self.zoom_level
        self._refresh_pending_rects_on_canvas()
        self._refresh_manual_marks_list()

        total = self.engine.page_count
        self.page_indicator.setText("{} / {}".format(self.current_page_index + 1, total))
        self.zoom_label.setText("{}%".format(int(self.zoom_level / self.base_dpi_zoom * 100)))

    def _refresh_pending_rects_on_canvas(self):
        marks = self.marks_by_page.get(self.current_page_index, [])
        widget_rects = []
        for m in marks:
            r = m.rect
            widget_rects.append(QRectF(
                r.x0 * self.render_scale,
                r.y0 * self.render_scale,
                (r.x1 - r.x0) * self.render_scale,
                (r.y1 - r.y0) * self.render_scale,
            ))
        self.canvas.set_pending_rects(widget_rects)

    def _refresh_manual_marks_list(self):
        self.manual_marks_list.clear()
        marks = self.marks_by_page.get(self.current_page_index, [])
        for i, m in enumerate(marks):
            label = m.label if m.label else "Region {}".format(i + 1)
            item = QListWidgetItem("[{}] {}".format(m.source, label))
            self.manual_marks_list.addItem(item)

    def go_next_page(self):
        if not self.engine.is_open():
            return
        if self.current_page_index < self.engine.page_count - 1:
            self.current_page_index += 1
            self.render_current_page()

    def go_prev_page(self):
        if not self.engine.is_open():
            return
        if self.current_page_index > 0:
            self.current_page_index -= 1
            self.render_current_page()

    def jump_to_page(self):
        if not self.engine.is_open():
            return
        text = self.jump_input.text().strip()
        if not text.isdigit():
            QMessageBox.warning(self, "Invalid Page", "Please enter a valid page number.")
            return
        page_num = int(text)
        if page_num < 1 or page_num > self.engine.page_count:
            QMessageBox.warning(
                self, "Invalid Page",
                "Page number must be between 1 and {}.".format(self.engine.page_count)
            )
            return
        self.current_page_index = page_num - 1
        self.render_current_page()

    def zoom_in(self):
        if not self.engine.is_open():
            return
        self.zoom_level = min(self.zoom_level + 0.2, 4.0)
        self.render_current_page()

    def zoom_out(self):
        if not self.engine.is_open():
            return
        self.zoom_level = max(self.zoom_level - 0.2, 0.4)
        self.render_current_page()

    # ------------------------------------------------------------------
    # Manual redaction
    # ------------------------------------------------------------------
    def on_manual_rectangle_drawn(self, widget_rect: QRect):
        if not self.engine.is_open():
            return
        scale = self.render_scale
        pdf_rect = fitz.Rect(
            widget_rect.left() / scale,
            widget_rect.top() / scale,
            widget_rect.right() / scale,
            widget_rect.bottom() / scale,
        )
        mark = RedactionMark(
            page_index=self.current_page_index, rect=pdf_rect,
            source="manual", label="Manual area",
        )
        self.marks_by_page.setdefault(self.current_page_index, []).append(mark)
        self.undo_stack.append(("add", self.current_page_index, mark))
        self._refresh_pending_rects_on_canvas()
        self._refresh_manual_marks_list()
        self.update_total_marks_label()
        self.status.showMessage("Marked 1 region for redaction on page {}.".format(self.current_page_index + 1))

    def undo_last_action(self):
        if not self.undo_stack:
            self.status.showMessage("Nothing to undo.")
            return
        action, page_idx, mark = self.undo_stack.pop()
        if action == "add":
            page_marks = self.marks_by_page.get(page_idx, [])
            if mark in page_marks:
                page_marks.remove(mark)
        elif action == "bulk_add":
            page_marks = self.marks_by_page.get(page_idx, [])
            for m in mark:
                if m in page_marks:
                    page_marks.remove(m)
        if self.current_page_index == page_idx:
            self._refresh_pending_rects_on_canvas()
            self._refresh_manual_marks_list()
        self.update_total_marks_label()
        self.status.showMessage("Undo successful.")

    def clear_current_page_marks(self):
        if self.current_page_index in self.marks_by_page and self.marks_by_page[self.current_page_index]:
            reply = QMessageBox.question(
                self, "Clear Page Marks",
                "Remove all pending redaction marks on this page?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                self.marks_by_page[self.current_page_index] = []
                self._refresh_pending_rects_on_canvas()
                self._refresh_manual_marks_list()
                self.update_total_marks_label()
                self.status.showMessage("Cleared marks on current page.")
        else:
            self.status.showMessage("No marks on this page to clear.")

    def update_total_marks_label(self):
        total = sum(len(v) for v in self.marks_by_page.values())
        self.total_marks_label.setText("Total pending marks (all pages): {}".format(total))
        self.apply_all_btn.setEnabled(total > 0 and self.engine.is_open())

    # ------------------------------------------------------------------
    # Find & Redact
    # ------------------------------------------------------------------
    def run_find_search(self):
        if not self.engine.is_open():
            QMessageBox.information(self, "No Document", "Please open a PDF first.")
            return
        query = self.search_input.text().strip()
        if not query:
            QMessageBox.information(self, "Empty Search", "Please enter text to search for.")
            return

        self.find_results_list.clear()
        results = self.engine.search_text_all_pages(query)
        if not results:
            self.status.showMessage("No matches found for '{}'.".format(query))
            return

        self._find_match_data = []
        for page_idx in sorted(results.keys()):
            for rect in results[page_idx]:
                self._find_match_data.append((page_idx, rect))
                item = QListWidgetItem()
                cb = QCheckBox("Page {} : \"{}\"".format(page_idx + 1, query))
                cb.setChecked(True)
                item.setSizeHint(cb.sizeHint())
                self.find_results_list.addItem(item)
                self.find_results_list.setItemWidget(item, cb)

        total_found = len(self._find_match_data)
        self.status.showMessage(
            "Found {} occurrence(s) of '{}' across {} page(s).".format(total_found, query, len(results))
        )

    def mark_checked_find_matches(self):
        if not hasattr(self, "_find_match_data") or not self._find_match_data:
            self.status.showMessage("No search results to mark.")
            return
        new_marks_by_page = {}
        count = 0
        for row in range(self.find_results_list.count()):
            item = self.find_results_list.item(row)
            cb = self.find_results_list.itemWidget(item)
            if cb and cb.isChecked():
                page_idx, rect = self._find_match_data[row]
                mark = RedactionMark(
                    page_index=page_idx, rect=rect, source="find",
                    label=self.search_input.text().strip()
                )
                self.marks_by_page.setdefault(page_idx, []).append(mark)
                new_marks_by_page.setdefault(page_idx, []).append(mark)
                count += 1

        for page_idx, marks in new_marks_by_page.items():
            self.undo_stack.append(("bulk_add", page_idx, marks))

        self._refresh_pending_rects_on_canvas()
        self._refresh_manual_marks_list()
        self.update_total_marks_label()
        self.status.showMessage("Marked {} match(es) for redaction.".format(count))

    # ------------------------------------------------------------------
    # Smart Redaction
    # ------------------------------------------------------------------
    def run_smart_scan(self):
        if not self.engine.is_open():
            QMessageBox.information(self, "No Document", "Please open a PDF first.")
            return

        active_categories = {c for c, cb in self.category_checks.items() if cb.isChecked()}
        if not active_categories:
            QMessageBox.information(self, "No Categories Selected", "Please select at least one category to scan for.")
            return

        self.smart_results_list.clear()
        self._smart_match_data = []

        progress = QProgressDialog("Scanning document for sensitive data...", "Cancel", 0, self.engine.page_count, self)
        progress.setWindowTitle("Smart Redaction Scan")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)

        try:
            for page_idx in range(self.engine.page_count):
                progress.setValue(page_idx)
                if progress.wasCanceled():
                    break
                text = self.engine.get_page_text(page_idx)
                candidates = find_smart_candidates(text)
                for category, value, span in candidates:
                    if category not in active_categories:
                        continue
                    rects = self.engine.search_text(page_idx, value)
                    if not rects:
                        compact = re.sub(r'[\s-]', '', value)
                        rects = self.engine.search_text(page_idx, compact)
                    for r in rects:
                        self._smart_match_data.append((page_idx, r, category, value))
            progress.setValue(self.engine.page_count)
        except Exception as exc:
            progress.close()
            QMessageBox.critical(self, "Scan Error", "An error occurred while scanning:\n{}".format(exc))
            return

        if not self._smart_match_data:
            self.status.showMessage("Smart scan complete. No candidates found.")
            return

        for page_idx, rect, category, value in self._smart_match_data:
            item = QListWidgetItem()
            display_value = self._mask_preview(category, value)
            cb = QCheckBox("Page {} : [{}] {}".format(page_idx + 1, category, display_value))
            cb.setChecked(True)
            item.setSizeHint(cb.sizeHint())
            self.smart_results_list.addItem(item)
            self.smart_results_list.setItemWidget(item, cb)

        self.status.showMessage(
            "Smart scan complete. {} candidate(s) found across the document. "
            "Please review before applying.".format(len(self._smart_match_data))
        )

    @staticmethod
    def _mask_preview(category: str, value: str) -> str:
        """Show a partially masked preview in the review list for extra safety."""
        v = value
        if len(v) <= 4:
            return v
        visible = 2
        return v[:visible] + "*" * (len(v) - visible * 2) + v[-visible:]

    def _toggle_all_smart(self, checked: bool):
        for row in range(self.smart_results_list.count()):
            item = self.smart_results_list.item(row)
            cb = self.smart_results_list.itemWidget(item)
            if cb:
                cb.setChecked(checked)

    def mark_checked_smart_matches(self):
        if not hasattr(self, "_smart_match_data") or not self._smart_match_data:
            self.status.showMessage("No smart-scan results to mark. Run a scan first.")
            return

        new_marks_by_page = {}
        count = 0
        for row in range(self.smart_results_list.count()):
            item = self.smart_results_list.item(row)
            cb = self.smart_results_list.itemWidget(item)
            if cb and cb.isChecked():
                page_idx, rect, category, value = self._smart_match_data[row]
                mark = RedactionMark(
                    page_index=page_idx, rect=rect, source="smart",
                    label="{}: {}".format(category, self._mask_preview(category, value))
                )
                self.marks_by_page.setdefault(page_idx, []).append(mark)
                new_marks_by_page.setdefault(page_idx, []).append(mark)
                count += 1

        for page_idx, marks in new_marks_by_page.items():
            self.undo_stack.append(("bulk_add", page_idx, marks))

        self._refresh_pending_rects_on_canvas()
        self._refresh_manual_marks_list()
        self.update_total_marks_label()
        self.status.showMessage("Marked {} confirmed candidate(s) for redaction.".format(count))

    # ------------------------------------------------------------------
    # Apply & Save
    # ------------------------------------------------------------------
    def save_redacted_pdf(self):
        if not self.engine.is_open():
            QMessageBox.information(self, "No Document", "Please open a PDF first.")
            return

        all_marks = []
        for page_idx, marks in self.marks_by_page.items():
            all_marks.extend(marks)

        if not all_marks:
            QMessageBox.information(
                self, "No Redactions Marked",
                "You have not marked any regions for redaction yet.\n\n"
                "Use Manual, Find & Redact, or Smart Redaction to mark content first."
            )
            return

        confirm = QMessageBox.question(
            self, "Confirm Redaction",
            "You are about to permanently apply {} redaction(s) and save a "
            "NEW PDF file.\n\nThe original file will not be modified. "
            "This action cannot be undone once saved. Continue?".format(len(all_marks)),
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        default_name = "redacted_output.pdf"
        if self.engine.file_path:
            base, ext = os.path.splitext(os.path.basename(self.engine.file_path))
            default_name = "{}_redacted.pdf".format(base)

        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Redacted PDF As", default_name, "PDF Files (*.pdf)"
        )
        if not out_path:
            return
        if not out_path.lower().endswith(".pdf"):
            out_path += ".pdf"

        if self.engine.file_path and os.path.abspath(out_path) == os.path.abspath(self.engine.file_path):
            QMessageBox.warning(
                self, "Cannot Overwrite Original",
                "For your safety, the redacted PDF cannot overwrite the "
                "original file. Please choose a different file name."
            )
            return

        try:
            self.engine.apply_redactions_to_document(all_marks, out_path)
        except Exception as exc:
            traceback.print_exc()
            QMessageBox.critical(
                self, "Redaction Failed",
                "An error occurred while applying redactions:\n{}".format(exc)
            )
            return

        QMessageBox.information(
            self, "Redaction Complete",
            "Redacted PDF saved successfully to:\n{}\n\n"
            "The redacted regions have been permanently removed from the "
            "document's content stream and rasterized as black boxes. "
            "The original file remains unchanged.".format(out_path)
        )
        self.status.showMessage("Saved redacted PDF: {}".format(out_path))

        self.marks_by_page = {}
        self.undo_stack = []
        self.find_results_list.clear()
        self.smart_results_list.clear()
        self.update_total_marks_label()
        self.render_current_page()

    def shutdown(self):
        """Called by MainWindow on close to release the open document."""
        self.engine.close()


# ---------------------------------------------------------------------------
# Section 11: Main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self, theme_manager: "ThemeManager"):
        super().__init__()
        self.theme_manager = theme_manager
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.resize(1200, 760)
        self.setMinimumSize(960, 640)

        central_widget = QWidget()
        central_widget.setObjectName("CentralWidget")
        self.setCentralWidget(central_widget)
        outer_layout = QHBoxLayout(central_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # --- Sidebar ---
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        app_title = QLabel("Ahmedabad")
        app_title.setObjectName("sidebarTitle")
        app_subtitle = QLabel("PDF STUDIO PRO")
        app_subtitle.setObjectName("sidebarSubtitle")
        sidebar_layout.addWidget(app_title)
        sidebar_layout.addWidget(app_subtitle)

        self.nav_buttons = []

        nav_items = [
            ("Home", HomePage, "plain"),
            ("Merge PDF", MergePage, "plain"),
            ("Split PDF", SplitPage, "plain"),
            ("Extract Pages", ExtractPage, "plain"),
            ("Add Page Numbers", PageNumberPage, "plain"),
            ("Rearrange Pages", RearrangePage, "plain"),
            ("PDF <-> Image", ConvertPage, "plain"),
            ("Password Protect / Remove", PasswordPage, "plain"),
            ("Redaction Studio", RedactionStudioPage, "themed"),
        ]

        self.stack = QStackedWidget()
        self.stack.setObjectName("contentArea")

        self.redaction_page: Optional[RedactionStudioPage] = None

        for index, (label_text, page_class, kind) in enumerate(nav_items):
            if kind == "themed":
                page_instance = page_class(self.theme_manager)
                self.redaction_page = page_instance
            else:
                page_instance = page_class()
            self.stack.addWidget(page_instance)

            nav_btn = QPushButton(label_text)
            nav_btn.setObjectName("navButton")
            nav_btn.setCheckable(True)
            nav_btn.setCursor(Qt.PointingHandCursor)
            nav_btn.clicked.connect(lambda checked, i=index: self._switch_page(i))
            sidebar_layout.addWidget(nav_btn)
            self.nav_buttons.append(nav_btn)

        sidebar_layout.addStretch(1)

        footer_label = QLabel(f"v{APP_VERSION}")
        footer_label.setObjectName("sidebarSubtitle")
        sidebar_layout.addWidget(footer_label)

        outer_layout.addWidget(sidebar)

        # --- Content area (header + stacked pages) ---
        content_container = QWidget()
        self._content_container = content_container
        content_layout = QVBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        header_bar = QFrame()
        header_bar.setObjectName("headerBar")
        header_bar.setFixedHeight(48)
        header_layout = QHBoxLayout(header_bar)
        header_layout.setContentsMargins(24, 0, 24, 0)
        header_caption = QLabel("Professional PDF Tools — Merge — Split — Secure — Redact — Convert")
        header_caption.setObjectName("pageDescription")
        header_layout.addWidget(header_caption)
        header_layout.addStretch(1)

        self.trial_badge = QLabel("Trial Version — 60s")
        self.trial_badge.setObjectName("TrialBadge")
        header_layout.addWidget(self.trial_badge)

        self.theme_button = ThemeMenuButton(self.theme_manager)
        header_layout.addWidget(self.theme_button)

        content_layout.addWidget(header_bar)
        content_layout.addWidget(self.stack)
        outer_layout.addWidget(content_container, 1)

        self._switch_page(0)

        # --- Trial gating overlay, always topmost within the window ---
        self.trial_overlay = TrialExpiredOverlay(central_widget)
        self.trial_overlay.setGeometry(central_widget.rect())

        # Controls that must be locked when the trial ends. Nav buttons and
        # the theme picker stay enabled so the user can still see the app
        # and change appearance, but every functional control is disabled.
        self._protected_widgets = [self.stack]

    def _switch_page(self, index):
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setChecked(i == index)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "trial_overlay") and self.trial_overlay.isVisible():
            self.trial_overlay.setGeometry(self.centralWidget().rect())

    # ------------------------------------------------------------------
    # Trial gating
    # ------------------------------------------------------------------
    def on_trial_tick(self, seconds_remaining: int):
        self.trial_badge.setText(f"Trial Version — {seconds_remaining}s")

    def on_trial_expired(self):
        for widget in self._protected_widgets:
            widget.setEnabled(False)
        self.trial_badge.setText("Trial Expired")
        self.trial_overlay.setGeometry(self.centralWidget().rect())
        self.trial_overlay.show_overlay()

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        if self.redaction_page is not None:
            self.redaction_page.shutdown()
        event.accept()


# ---------------------------------------------------------------------------
# Section 12: Application entry point
# ---------------------------------------------------------------------------
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setApplicationName(APP_NAME)

    theme_manager = ThemeManager(app)

    window = MainWindow(theme_manager)
    window.show()

    trial_manager = TrialManager(window)
    trial_manager.tick.connect(window.on_trial_tick)
    trial_manager.trialExpired.connect(window.on_trial_expired)
    trial_manager.start()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
