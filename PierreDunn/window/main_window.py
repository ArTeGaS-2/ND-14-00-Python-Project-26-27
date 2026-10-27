from pathlib import Path

from PyQt6 import uic
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QMainWindow


class MainWindow(QMainWindow):
    """Завантажує розмітку та стилі головного вікна."""

    def __init__(self) -> None:
        super().__init__()
        window_directory = Path(__file__).parent
        uic.loadUi(str(window_directory / "main_window.xml"), self)

        stylesheet_path = window_directory / "styles" / "main_window.css"
        self.setStyleSheet(stylesheet_path.read_text(encoding="utf-8"))

        input_palette = self.inputField.palette()
        input_palette.setColor(
            QPalette.ColorRole.PlaceholderText,
            QColor("#aeb9ca"),
        )
        self.inputField.setPalette(input_palette)
