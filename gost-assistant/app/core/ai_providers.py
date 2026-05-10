"""
Модуль для работы с ИИ-провайдерами
Реализует абстракцию для различных API (YandexGPT, Mock)
"""

import os
import requests
import re
import traceback
from dotenv import load_dotenv
from abc import ABC, abstractmethod
from typing import List, Dict
from datetime import datetime
import json
from .source_classifier import classify_entry

# Загрузка переменных окружения из .env
load_dotenv()


# ==================== АБСТРАКТНЫЙ БАЗОВЫЙ КЛАСС ====================

class AIProvider(ABC):
    """Абстрактный базовый класс для провайдеров ИИ"""

    @abstractmethod
    def fix_text(self, text_lines: List[str], rules_context: str = "", ui_language: str = "ru_RU") -> Dict:
        """
        Исправление текста по ГОСТ

        Args:
            text_lines: Список записей литературы
            rules_context: Контекст правил (опционально)

        Returns:
            Словарь с результатами обработки
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Получение названия провайдера"""
        pass


# ==================== YANDEXGPT PROVIDER ====================

class YandexGPTProvider(AIProvider):
    """Провайдер: YandexGPT (использует API-ключ напрямую)"""

    def __init__(self, api_key: str = None, folder_id: str = None):
        # Берём из .env если не переданы
        self.api_key = api_key or os.getenv('YANDEX_API_KEY')
        self.folder_id = folder_id or os.getenv('YANDEX_FOLDER_ID')

        if not self.api_key or not self.folder_id:
            raise ValueError(
                "YANDEX_API_KEY и YANDEX_FOLDER_ID не найдены!\n"
                "Проверь файл .env в корне проекта"
            )

        # URL для YandexGPT
        self.gpt_url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

    def fix_text(self, text_lines: List[str], rules_context: str = "", ui_language: str = "ru_RU") -> Dict:
        """Исправление текста через YandexGPT"""

        try:
            # Формируем промпт
            prompt = self._build_prompt(text_lines, ui_language)

            # Заголовки для запроса к YandexGPT
            headers = {
                "Authorization": f"Api-Key {self.api_key}",
                "Content-Type": "application/json",
                "x-folder-id": self.folder_id
            }

            # Тело запроса
            payload = {
                "modelUri": f"gpt://{self.folder_id}/yandexgpt/latest",
                "completionOptions": {
                    "stream": False,
                    "temperature": 0.1,
                    "maxTokens": 2000
                },
                "messages": [
                    {
                        "role": "system",
                        "text": "Ты — эксперт по оформлению академических работ по ГОСТ Р 7.0.100-2018 для РФ."
                    },
                    {
                        "role": "user",
                        "text": prompt
                    }
                ]
            }

            # Запрос к YandexGPT
            response = requests.post(
                self.gpt_url,
                headers=headers,
                json=payload,
                timeout=60
            )

            if response.status_code != 200:
                self._log_error(f"HTTP {response.status_code}", response.text)
                return {
                    'success': False,
                    'error': f"Ошибка API: {response.status_code}\n{response.text}",
                    'provider': self.get_name(),
                    'timestamp': datetime.now().isoformat()
                }

            result = response.json()
            fixed_text = result['result']['alternatives'][0]['message']['text']
            self._log_raw_response(fixed_text, text_lines)

            return {
                'success': True,
                'fixed_lines': self._parse_response(fixed_text),
                'raw_response': fixed_text,
                'provider': self.get_name(),
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            self._log_error(str(e), traceback.format_exc())
            return {
                'success': False,
                'error': str(e),
                'provider': self.get_name(),
                'timestamp': datetime.now().isoformat()
            }

    def _build_prompt(self, text_lines: List[str], ui_language: str = "ru_RU") -> str:
        """Формирование промпта для модели"""
        lines_with_types = []
        for line in text_lines:
            stripped = line.strip()
            if stripped.startswith("TYPE="):
                lines_with_types.append(line)
            else:
                lines_with_types.append(f"TYPE={classify_entry(line)}: {line}")
        bibliography_text = "\n".join(lines_with_types)
        comment_languages = {
            "ru_RU": "русском языке",
            "en_US": "English",
            "zh_CN": "中文",
        }
        comment_language = comment_languages.get(ui_language, "русском языке")

        return f"""
ТВОЯ ЗАДАЧА: Исправить список литературы согласно правилам ниже.

ОБЩИЕ ПРАВИЛА:
1) Пробел перед двоеточием обязателен (разделяет зоны заглавия и вида издания).
2) Используется длинное тире « — » с пробелами с обеих сторон.
3) После точки и запятой — пробел.
4) В конце каждой записи — точка.
5) 1–3 автора: Фамилия И.О. указывается ДО названия.
6) 4+ автора: авторов в начале НЕТ, только после названия через /.
7) Авторы повторяются после названия через / (И.О. Фамилия).
8) Электронные ресурсы: добавить [Электронный ресурс] после названия; URL после «URL: »; дата обращения: (дата обращения: дд.мм.гггг).

ШАБЛОНЫ ПО ТИПАМ ИСТОЧНИКОВ:

КНИГА (1–3 автора):
Фамилия И. О. Название книги: вид издания. Город: Издательство, год. Количество с.

КНИГА (4+ автора):
Название книги: вид издания / И. О. Фамилия [и др.]. Город: Издательство, год. Количество с.

СТАТЬЯ ИЗ ЖУРНАЛА:
Фамилия И. О. Название статьи // Название журнала. год. № номер. С. страницы.

СТАТЬЯ ИЗ СБОРНИКА:
Фамилия И. О. Название статьи // Название сборника / Отв. ред. И. О. Фамилия. Город: Издательство, год. С. страницы.

МНОГОТОМНОЕ ИЗДАНИЕ:
Фамилия И. О. Название: в N т. Т. номер. Город: Издательство, год. Количество с.

ГОСТ И СТАНДАРТЫ:
ГОСТ Р номер. Название. Город: Издательство, год. URL: ссылка (дата обращения: дд.мм.гггг).

ФЕДЕРАЛЬНЫЕ ЗАКОНЫ РФ:
О название: Федер. закон Рос. Федерации от дата № номер. Источник. URL: ссылка (дата обращения: дд.мм.гггг).

ДИССЕРТАЦИИ И АВТОРЕФЕРАТЫ:
Фамилия И. О. Название: специальность «код»: степень: учреждение. Город, год. Количество с.

АРХИВНЫЕ ДОКУМЕНТЫ:
Использовать сокращения: ф. — фонд, оп. — опись, д. — дело, л. — лист.

ЭЛЕКТРОННЫЕ РЕСУРСЫ (сайты, порталы):
Фамилия И. О. Название [Электронный ресурс]. Год. URL: ссылка (дата обращения: дд.мм.гггг).

ВАЖНЫЕ ИНСТРУКЦИИ:
- Сохрани исходный порядок источников (не сортируй).
- Исправляй только оформление (пунктуацию, сокращения, порядок элементов).
- Не изменяй содержание (названия, имена авторов, годы, страницы).
- Для интернет-источников добавь [Электронный ресурс] и дату обращения.
- Для статей добавь разделитель «//» перед названием журнала/сборника.
- Для книг с 1–3 авторами повтори авторов после названия через /.
- Для книг с 4+ авторами НЕ указывай авторов в начале, только после /.
- Верни исправленный список: каждая запись с новой строки, без нумерации.
- Каждая строка имеет префикс TYPE=... Используй его как подсказку типа источника.
- Если TYPE=unknown, определи тип по содержимому.
- Если данных не хватает (автор, город, издательство, год, страницы, URL, дата обращения и т. п.), НЕ придумывай.
- Не переводи сами библиографические записи: язык, названия и данные источников должны остаться на языке пользовательского ввода.
- Комментарии, пояснения и блок с недостающими данными пиши на языке интерфейса: {comment_language}.
- После списка добавь блок с недостающими данными и перечисли по строкам, чего не хватает.

ИСХОДНЫЙ СПИСОК:
{bibliography_text}

ИСПРАВЛЕННЫЙ СПИСОК:
"""

    def _parse_response(self, text: str) -> List[str]:
        """Парсинг ответа модели в список записей"""
        lines = []
        for line in text.strip().split('\n'):
            line = line.strip()
            # Убираем нумерацию/маркеры перед TYPE
            line = re.sub(r'^[\s\d\.\)\-•—–]+', '', line)
            line = re.sub(r'^TYPE=[^:\s]+(?:\s*[:\-—–]\s*|\s+)', '', line)
            # Убираем нумерацию и маркеры после удаления TYPE
            line = re.sub(r'^[\s\d\.\)\-•—–]+', '', line)
            if line and len(line) > 10:
                lines.append(line)
        return lines

    def _log_raw_response(self, raw_text: str, input_lines: List[str]):
        """Логирование необработанного ответа ИИ"""
        try:
            log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "logs"))
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "ai_raw_responses.log")

            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n" + "=" * 80 + "\n")
                f.write(f"timestamp: {datetime.now().isoformat()}\n")
                f.write(f"provider: {self.get_name()}\n")
                f.write("input:\n")
                for line in input_lines:
                    f.write(f"- {line}\n")
                f.write("raw_response:\n")
                f.write(raw_text.strip() + "\n")
        except Exception:
            # Не ломаем основную логику при проблемах с логированием
            pass

    def _log_error(self, error: str, details: str = ""):
        """Логирование ошибок ИИ"""
        try:
            log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "logs"))
            os.makedirs(log_dir, exist_ok=True)
            log_path = os.path.join(log_dir, "ai_errors.log")

            with open(log_path, "a", encoding="utf-8") as f:
                f.write("\n" + "=" * 80 + "\n")
                f.write(f"timestamp: {datetime.now().isoformat()}\n")
                f.write(f"provider: {self.get_name()}\n")
                f.write(f"error: {error}\n")
                if details:
                    f.write("details:\n")
                    f.write(details.strip() + "\n")
        except Exception:
            pass

    def get_name(self) -> str:
        return "YandexGPT"


# ==================== MOCK PROVIDER ====================

class MockProvider(AIProvider):
    """Тестовый провайдер (без реального API)"""

    def fix_text(self, text_lines: List[str], rules_context: str = "", ui_language: str = "ru_RU") -> Dict:
        """Имитация исправления для тестирования"""

        fixed_lines = []
        for line in text_lines:
            fixed = re.sub(r'^TYPE=[^:\s]+(?:\s*[:\-—–]\s*|\s+)', '', line).strip()
            # Простые замены для демонстрации
            if ', ' in fixed and any(c.isdigit() for c in fixed):
                fixed = fixed.replace(', ', '. — ', 1)
            fixed_lines.append(fixed)

        return {
            'success': True,
            'fixed_lines': fixed_lines,
            'raw_response': '\n'.join(fixed_lines),
            'provider': self.get_name(),
            'timestamp': datetime.now().isoformat()
        }

    def get_name(self) -> str:
        return "Mock (Тестовый)"


# ==================== FACTORY ====================

class AIProviderFactory:
    """Фабрика для создания провайдеров"""

    @staticmethod
    def create_provider(provider_name: str) -> AIProvider:
        """
        Создание провайдера по имени

        Args:
            provider_name: Название провайдера ('yandex' или 'mock')

        Returns:
            Экземпляр провайдера
        """
        if provider_name == "yandex":
            return YandexGPTProvider()
        else:
            return MockProvider()
