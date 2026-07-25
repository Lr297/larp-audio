"""Central QSS for the approved high-contrast editorial workspace."""

from . import tokens as t

STYLESHEET = f"""
QWidget {{
    background: {t.MAIN_BACKGROUND};
    color: {t.PRIMARY_TEXT};
    font-family: "Helvetica Neue", "Helvetica", "Arial", sans-serif;
    font-size: 13px;
    font-weight: 400;
}}
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
QMainWindow, QDialog {{ background: {t.MAIN_BACKGROUND}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: 0; }}

QFrame#hairline {{ background: {t.SUBTLE_BORDER}; min-height: 1px; max-height: 1px; border: 0; }}
QFrame#surfaceCard {{ background: {t.CARD_SURFACE}; border: 1px solid {t.SUBTLE_BORDER}; border-radius: {t.CARD_RADIUS}px; }}
QFrame#surfaceCard[interactive="true"]:hover {{ background: {t.ELEVATED_SURFACE}; border-color: {t.STRONG_BORDER}; }}
QFrame#surfaceCard[dragActive="true"] {{ background: {t.SOFT_SELECTED}; border: 1px solid {t.PRIMARY_RED}; }}
QFrame#surfaceCard[accepted="true"] {{ border: 1px solid #9BD8B5; }}
QFrame#setupBar {{ background: {t.CARD_SURFACE}; border-top: 1px solid {t.SUBTLE_BORDER}; border-bottom: 1px solid {t.SUBTLE_BORDER}; }}
QFrame#processingCard, QFrame#emptyResult {{ background: {t.CARD_SURFACE}; border: 1px solid {t.SUBTLE_BORDER}; border-radius: {t.CARD_RADIUS}px; }}
QFrame#pauseChoice {{ background: transparent; border-top: 1px solid {t.SUBTLE_BORDER}; border-bottom: 1px solid {t.SUBTLE_BORDER}; }}
QFrame#pauseChoice[selected="true"] {{ border-top: 2px solid {t.PRIMARY_RED}; }}
QFrame#pauseChoice:hover {{ background: {t.ELEVATED_SURFACE}; }}

QLabel#productTitle {{ font-family: "Arial Black", "Arial", sans-serif; font-size: 26px; font-weight: 900; letter-spacing: -0.4px; }}
QLabel#productStatement {{ color: {t.TERTIARY_TEXT}; font-size: 12px; }}
QLabel#sectionTitle {{ font-family: "Arial Black", "Arial", sans-serif; font-size: 18px; font-weight: 900; }}
QLabel#displayTitle {{ font-family: "Arial Black", "Arial", sans-serif; font-size: 27px; font-weight: 900; letter-spacing: -0.3px; }}
QLabel#kicker {{ color: {t.PRIMARY_RED}; font-size: 11px; font-weight: 800; letter-spacing: 1.7px; }}
QLabel#workflowStrip {{ color: #777777; font-size: 10px; font-weight: 700; letter-spacing: 1.8px; padding: 7px 0; }}
QLabel#statusText {{ color: {t.SECONDARY_TEXT}; font-size: 11px; font-weight: 700; letter-spacing: 1.1px; }}
QLabel#muted {{ color: {t.SECONDARY_TEXT}; }}
QLabel#tertiary, QLabel#tiny {{ color: {t.TERTIARY_TEXT}; font-size: 11px; }}
QLabel#audioFileName {{ font-family: "Arial Black", "Arial", sans-serif; font-size: 18px; font-weight: 900; }}
QLabel#readinessReady {{ color: {t.PRIMARY_RED}; font-size: 11px; font-weight: 800; letter-spacing: 1.2px; }}
QLabel#readinessBlocked {{ color: {t.TERTIARY_TEXT}; font-size: 11px; font-weight: 700; letter-spacing: 0.8px; }}
QLabel#pauseNumber {{ color: #343434; font-family: "Arial Black", "Arial", sans-serif; font-size: 30px; font-weight: 900; }}
QLabel#pauseNumber[selected="true"] {{ color: {t.PRIMARY_RED}; }}
QLabel#pauseName {{ color: {t.SECONDARY_TEXT}; font-size: 11px; font-weight: 800; letter-spacing: 1.1px; }}
QLabel#pauseName[selected="true"] {{ color: {t.PRIMARY_RED}; }}
QLabel#pauseDescription {{ color: {t.TERTIARY_TEXT}; }}
QLabel#successBanner {{ color: #9BD8B5; font-size: 11px; font-weight: 800; letter-spacing: 1.1px; padding: 4px 0; }}
QLabel#errorBanner {{ background: rgba(255, 63, 61, 0.08); color: #FFB4BE; border: 1px solid {t.DEEP_RED}; border-radius: 8px; padding: 10px; }}
QScrollArea#subtitleViewport {{ background: transparent; border: 0; }}
QLabel#previewCue {{ font-family: "Arial Black", "Arial", sans-serif; font-size: 27px; font-weight: 900; padding: 8px 18px; background: transparent; }}

QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget, QTableView {{
    background: {t.CARD_SURFACE};
    border: 1px solid {t.SUBTLE_BORDER};
    border-radius: {t.CONTROL_RADIUS}px;
    padding: 7px;
    selection-background-color: {t.DEEP_RED};
    selection-color: {t.PRIMARY_TEXT};
}}
QPlainTextEdit {{ padding: 16px; font-size: 16px; }}
QPlainTextEdit:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QListWidget:focus, QTableView:focus {{ border: 1px solid {t.FOCUS_OUTLINE}; }}

QPushButton {{ background: transparent; border: 1px solid {t.SUBTLE_BORDER}; border-radius: {t.CONTROL_RADIUS}px; padding: 9px 16px; color: {t.PRIMARY_TEXT}; font-weight: 700; }}
QPushButton:hover {{ border-color: {t.PRIMARY_RED}; color: {t.PRIMARY_RED}; }}
QPushButton:pressed {{ background: {t.ELEVATED_SURFACE}; }}
QPushButton:focus {{ border: 1px solid {t.FOCUS_OUTLINE}; }}
QPushButton#primaryAction {{ background: {t.PRIMARY_RED}; color: white; border: 0; min-height: 26px; padding: 8px 28px; font-family: "Arial Black", "Arial", sans-serif; font-size: 14px; }}
QPushButton#primaryAction:hover {{ background: {t.HOVER_RED}; color: white; }}
QPushButton#primaryAction:pressed {{ background: {t.PRESSED_RED}; }}
QPushButton#primaryAction:disabled {{ background: #301313; color: #754545; }}
QPushButton#ghostAction, QPushButton#navAction {{ background: transparent; border-color: transparent; color: {t.TERTIARY_TEXT}; }}
QPushButton#ghostAction:hover, QPushButton#navAction:hover {{ background: transparent; color: {t.PRIMARY_TEXT}; border-color: transparent; }}
QPushButton#setupLabelAction {{ background: transparent; border: 0; color: {t.TERTIARY_TEXT}; font-size: 10px; font-weight: 500; text-align: left; padding: 0; }}
QPushButton#setupLabelAction:hover {{ color: {t.PRIMARY_RED}; }}
QPushButton#pauseOverlay {{ background: transparent; border: 0; border-radius: 0; padding: 0; }}
QPushButton#pauseOverlay:focus {{ border: 1px solid {t.FOCUS_OUTLINE}; }}
QPushButton:disabled, QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{ color: {t.DISABLED_TEXT}; background: {t.SECONDARY_BACKGROUND}; }}

QTabWidget::pane {{ border: 0; border-top: 1px solid {t.SUBTLE_BORDER}; background: transparent; }}
QTabBar::tab {{ background: transparent; color: {t.TERTIARY_TEXT}; border: 0; padding: 11px 18px; font-size: 11px; font-weight: 800; letter-spacing: 1.1px; }}
QTabBar::tab:selected {{ color: {t.PRIMARY_TEXT}; border-bottom: 2px solid {t.PRIMARY_RED}; }}
QTabBar::tab:hover {{ color: {t.SECONDARY_TEXT}; }}
QTabBar::tab:focus {{ border: 1px solid {t.FOCUS_OUTLINE}; }}

QListWidget#processingEvents {{ background: transparent; border: 0; padding: 0; }}
QListWidget#processingEvents::item {{ color: {t.TERTIARY_TEXT}; padding: 4px 14px 4px 0; font-size: 10px; font-weight: 700; }}
QListWidget#processingEvents::item:selected {{ color: {t.PRIMARY_RED}; background: transparent; }}
QListWidget#previewCueList {{ background: transparent; border: 0; border-right: 1px solid {t.SUBTLE_BORDER}; border-radius: 0; padding: 8px 12px 8px 0; }}
QListWidget#previewCueList::item {{ color: {t.TERTIARY_TEXT}; padding: 9px 8px; border: 0; }}
QListWidget#previewCueList::item:hover {{ background: {t.ELEVATED_SURFACE}; color: {t.SECONDARY_TEXT}; }}
QListWidget#previewCueList::item:selected {{ background: {t.SOFT_SELECTED}; color: {t.PRIMARY_TEXT}; border-left: 2px solid {t.PRIMARY_RED}; }}

QHeaderView::section {{ background: {t.CARD_SURFACE}; color: {t.SECONDARY_TEXT}; padding: 8px; border: 0; border-bottom: 1px solid {t.SUBTLE_BORDER}; font-weight: 700; }}
QTableView {{ gridline-color: transparent; alternate-background-color: {t.SECONDARY_BACKGROUND}; border-radius: 0; }}
QProgressBar {{ background: {t.ELEVATED_SURFACE}; border: 0; border-radius: 3px; height: 6px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {t.PRIMARY_RED}; border-radius: 3px; }}
QSlider::groove:horizontal {{ background: {t.ELEVATED_SURFACE}; height: 4px; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t.PRIMARY_RED}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {t.PRIMARY_TEXT}; width: 12px; margin: -4px 0; border-radius: 6px; }}
QCheckBox {{ color: {t.TERTIARY_TEXT}; spacing: 7px; }}
QToolTip {{ background: {t.ELEVATED_SURFACE}; color: {t.PRIMARY_TEXT}; border: 1px solid {t.SUBTLE_BORDER}; padding: 6px; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {t.STRONG_BORDER}; border-radius: 3px; min-height: 28px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 0; }}
"""
