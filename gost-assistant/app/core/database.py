"""
Модуль работы с базой данных SQLite
Реализует таблицы: history (история обработки), settings (настройки)
"""

import sqlite3
from datetime import datetime
from typing import List, Dict, Optional
import os

from .env_loader import load_app_env
from .secrets import protect_secret


class GOSTDatabase:
    """Класс для управления базой данных приложения"""

    def __init__(self, db_path: str = "data/gost_assistant.db"):
        """
        Инициализация базы данных

        Args:
            db_path: Путь к файлу базы данных
        """
        # Создаем директорию для БД если не существует
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

        self.db_path = db_path
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Получение соединения с базой данных"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Для доступа по имени столбца
        return conn

    def _init_database(self):
        """Создание таблиц при первом запуске"""
        conn = self._get_connection()
        cursor = conn.cursor()  # ← Создаём cursor!

        # Таблица 1: История обработки документов
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS history
                       (
                           id INTEGER PRIMARY KEY AUTOINCREMENT,
                           document_name TEXT NOT NULL,
                           document_path TEXT NOT NULL,
                           processed_at DATETIME
                           DEFAULT CURRENT_TIMESTAMP,
                           ai_provider TEXT NOT NULL,
                           sources_count INTEGER NOT NULL,
                           changes_count INTEGER NOT NULL,
                           original_text TEXT NOT NULL,
                           fixed_text TEXT NOT NULL,
                           status TEXT NOT NULL,
                           input_mode TEXT NOT NULL DEFAULT 'file',
                           note TEXT
                       )
                       """)

        # Миграция: добавление колонки input_mode в существующей таблице
        try:
            cursor.execute("ALTER TABLE history ADD COLUMN input_mode TEXT NOT NULL DEFAULT 'file'")
        except sqlite3.OperationalError:
            pass

        # Таблица 2: Конфигурация приложения
        cursor.execute("""
                       CREATE TABLE IF NOT EXISTS settings
                       (
                           id INTEGER PRIMARY KEY AUTOINCREMENT,
                           setting_key TEXT UNIQUE NOT NULL,
                           setting_value TEXT NOT NULL,
                           description TEXT
                       )
                       """)

        cursor.execute("DROP TABLE IF EXISTS cache")

        load_app_env()
        env_yandex_api_key = protect_secret(os.getenv("YANDEX_API_KEY", ""))
        env_yandex_folder_id = protect_secret(os.getenv("YANDEX_FOLDER_ID", ""))

        # Инициализация настроек по умолчанию
        default_settings = [
            ('ui_language', 'ru_RU', 'Язык интерфейса приложения'),
            ('theme', 'light', 'Тема оформления (light/dark)'),
            ('default_provider', 'mock', 'ИИ-агент по умолчанию'),
            ('output_folder', '', 'Папка для сохранения результатов'),
            ('auto_backup', 'true', 'Автоматическое создание резервной копии'),
            ('check_updates', 'true', 'Автоматическая проверка обновлений'),
            ('font_size', '12', 'Размер шрифта в интерфейсе'),
            ('yandex_api_key', env_yandex_api_key, 'API-ключ YandexGPT'),
            ('yandex_folder_id', env_yandex_folder_id, 'Folder ID Yandex Cloud'),
            ('gigachat_client_id', '', 'Authorization Key GigaChat')
        ]

        for key, value, desc in default_settings:
            cursor.execute("""
                           INSERT
                           OR IGNORE INTO settings (setting_key, setting_value, description)
            VALUES (?, ?, ?)
                           """, (key, value, desc))

        # Если БД уже была создана до появления этих настроек, но значения пустые,
        # подтягиваем их из .env и сразу сохраняем в защищенном виде.
        env_secret_settings = {
            "yandex_api_key": env_yandex_api_key,
            "yandex_folder_id": env_yandex_folder_id,
        }
        for key, value in env_secret_settings.items():
            if not value:
                continue
            cursor.execute(
                """
                UPDATE settings
                SET setting_value = ?
                WHERE setting_key = ? AND setting_value = ''
                """,
                (value, key)
            )

        conn.commit()
        conn.close()

    # ==================== Методы для таблицы history ====================

    def add_history_record(self, document_name: str, document_path: str,
                           ai_provider: str, sources_count: int, changes_count: int,
                           original_text: str, fixed_text: str, status: str,
                           note: str = "", input_mode: str = "file") -> int:
        """Добавление записи в историю обработки"""
        conn = self._get_connection()
        cursor = conn.cursor()  # ← Создаём cursor!

        cursor.execute("""
                       INSERT INTO history
                       (document_name, document_path, ai_provider, sources_count,
                        changes_count, original_text, fixed_text, status, note, input_mode)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       """, (document_name, document_path, ai_provider, sources_count,
                             changes_count, original_text, fixed_text, status, note, input_mode))

        record_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return record_id

    def get_history(self, limit: int = 50) -> List[Dict]:
        """Получение истории обработки"""
        conn = self._get_connection()
        cursor = conn.cursor()  # ← Создаём cursor!

        cursor.execute("""
                       SELECT id,
                              document_name,
                              document_path,
                              processed_at,
                              ai_provider,
                              sources_count,
                              changes_count,
                              input_mode,
                              status,
                              note,
                              original_text,
                              fixed_text
                       FROM history
                       ORDER BY processed_at DESC LIMIT ?
                       """, (limit,))

        results = [dict(row) for row in cursor.fetchall()]
        conn.close()

        return results

    def get_history_record(self, record_id: int) -> Optional[Dict]:
        """Получение конкретной записи истории по ID"""
        conn = self._get_connection()
        cursor = conn.cursor()  # ← Создаём cursor!

        cursor.execute("SELECT * FROM history WHERE id = ?", (record_id,))

        row = cursor.fetchone()
        conn.close()

        return dict(row) if row else None

    def delete_history_record(self, record_id: int):
        """Удаление записи из истории"""
        conn = self._get_connection()
        cursor = conn.cursor()  # ← Создаём cursor!

        cursor.execute("DELETE FROM history WHERE id = ?", (record_id,))

        conn.commit()
        conn.close()

    def clear_history(self):
        """Очистка всей истории"""
        conn = self._get_connection()
        cursor = conn.cursor()  # ← Создаём cursor!

        cursor.execute("DELETE FROM history")

        conn.commit()
        conn.close()

    # ==================== Методы для таблицы settings ====================

    def get_setting(self, key: str, default: str = "") -> str:
        """Получение значения настройки"""
        conn = self._get_connection()
        cursor = conn.cursor()  # ← Создаём cursor!

        cursor.execute("""
                       SELECT setting_value
                       FROM settings
                       WHERE setting_key = ?
                       """, (key,))

        row = cursor.fetchone()
        conn.close()

        return row['setting_value'] if row else default

    def set_setting(self, key: str, value: str, description: str = ""):
        """Установка значения настройки"""
        conn = self._get_connection()
        cursor = conn.cursor()  # ← Создаём cursor!

        if description:
            cursor.execute("""
            INSERT OR REPLACE INTO settings (setting_key, setting_value, description)
            VALUES (?, ?, ?)
            """, (key, value, description))
        else:
            cursor.execute("""
                           UPDATE settings
                           SET setting_value = ?
                           WHERE setting_key = ?
                           """, (value, key))

        conn.commit()
        conn.close()

    def get_all_settings(self) -> Dict[str, str]:
        """Получение всех настроек в виде словаря"""
        conn = self._get_connection()
        cursor = conn.cursor()  # ← Создаём cursor!

        cursor.execute("SELECT setting_key, setting_value FROM settings")

        settings = {row['setting_key']: row['setting_value'] for row in cursor.fetchall()}
        conn.close()

        return settings

    # ==================== Статистика ====================

    def get_statistics(self) -> Dict:
        """Получение статистики использования"""
        conn = self._get_connection()
        cursor = conn.cursor()  # ← Создаём cursor!

        # Общее количество обработанных документов
        cursor.execute("SELECT COUNT(*) FROM history")
        total_documents = cursor.fetchone()[0]

        # Количество успешных обработок
        cursor.execute("SELECT COUNT(*) FROM history WHERE status = 'Успешно'")
        successful = cursor.fetchone()[0]

        # Общее количество исправленных источников
        cursor.execute("SELECT SUM(changes_count) FROM history")
        result = cursor.fetchone()
        total_changes = result[0] if result and result[0] else 0

        conn.close()

        return {
            'total_documents': total_documents,
            'successful': successful,
            'total_changes': total_changes,
            'success_rate': (successful / total_documents * 100) if total_documents > 0 else 0
        }
