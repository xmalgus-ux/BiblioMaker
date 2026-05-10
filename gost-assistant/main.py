"""
Точка входа приложения BiblioMaker
"""

import sys
import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtCore import Qt

# Добавляем корень проекта в path
sys.path.insert(0, os.path.dirname(__file__))

from app.gui.main_window import BiblioMakerWindow


def main():
    """Основная функция запуска"""

    # Включение поддержки High DPI
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("BiblioMaker")
    app.setOrganizationName("UrFU")

    # Установка шрифта
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    # Создание и отображение главного окна
    window = BiblioMakerWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
