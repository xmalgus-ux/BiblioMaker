"""
Модуль для работы с ИИ-агентами
Реализует абстракцию для различных API (YandexGPT, GigaChat)
"""

import os
import base64
import shutil
import requests
import re
import traceback
import uuid
from abc import ABC, abstractmethod
from typing import List, Dict
from datetime import datetime
import json
from pathlib import Path
import certifi
import urllib3
from .source_classifier import classify_entry
from .secrets import unprotect_secret
from .env_loader import load_app_env

# Загрузка переменных окружения из .env
load_app_env()


# ==================== АБСТРАКТНЫЙ БАЗОВЫЙ КЛАСС ====================

class AIProvider(ABC):
    """Общий интерфейс для всех ИИ-агентов приложения.

    GUI работает только с этим интерфейсом, поэтому конкретный агент
    (YandexGPT или GigaChat) можно заменить без изменений в окне обработки.
    """

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
    """ИИ-агент YandexGPT.

    Отвечает за формирование промпта, отправку запроса в API Yandex Cloud
    и приведение ответа модели к формату, который можно показать в GUI.
    """

    def __init__(self, api_key: str = None, folder_id: str = None):
        # Берём из настроек приложения, затем из .env если не переданы
        self.api_key = api_key or os.getenv('YANDEX_API_KEY')
        self.folder_id = folder_id or os.getenv('YANDEX_FOLDER_ID')

        if not self.api_key or not self.folder_id:
            raise ValueError(
                "YANDEX_API_KEY и YANDEX_FOLDER_ID не найдены!\n"
                "Укажи их в настройках ИИ-агента или проверь файл .env в корне проекта"
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
                        "text": "Ты — помощник по приведению библиографических записей к правилам оформления, заданным пользователем. Следуй только правилам из пользовательского запроса. Не используй внешние знания о ГОСТ, если они противоречат указанным правилам."
                    },
                    {
                        "role": "user",
                        "text": prompt
                    }
                ]
            }

            # Запрос синхронный, но выполняется в ProcessingThread,
            # поэтому интерфейс приложения не блокируется.
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
                'fixed_lines': self._parse_response(fixed_text, text_lines),
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
        """Формирование промпта с правилами ГОСТ и типами источников.

        Каждая запись получает служебный префикс TYPE=..., который помогает
        модели выбрать шаблон оформления. В итоговый ответ этот префикс
        попадать не должен.
        """
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

        result_header = {
            "ru_RU": "ИСПРАВЛЕННЫЙ СПИСОК",
            "en_US": "FIXED LIST",
            "zh_CN": "修正列表",
        }.get(ui_language, "ИСПРАВЛЕННЫЙ СПИСОК")
        missing_header = {
            "ru_RU": "НЕ ХВАТАЕТ ДАННЫХ",
            "en_US": "MISSING DATA",
            "zh_CN": "缺少数据",
        }.get(ui_language, "НЕ ХВАТАЕТ ДАННЫХ")

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
9) Для всех источников, которые начинаются с автора, ставь автора в порядке «Фамилия И. О.». Если во входной строке стоит «И. О. Фамилия», переставь в «Фамилия И. О.».
10) После косой черты «/» порядок автора обратный: «И. О. Фамилия». Не применяй правило из пункта 9 к автору после «/».

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
- Обращай внимание на порядок инициалов в шаблонах и выставляй инициалы в ответе соответственно.
- Для TYPE=book, TYPE=journal_article, TYPE=collection_article, TYPE=multi_volume, TYPE=dissertation и TYPE=electronic с автором обязательно исправляй начало записи: «И. О. Фамилия Название...» должно стать «Фамилия И. О. Название...».
- Не изменяй содержание (названия, имена авторов, годы, страницы).
- Для интернет-источников добавь [Электронный ресурс] и дату обращения.
- Для статей добавь разделитель «//» перед названием журнала/сборника.
- Для книг с 4+ авторами НЕ указывай авторов в начале, только после /.
- Каждая строка имеет префикс TYPE=... Используй его как подсказку типа источника.
- Если TYPE=unknown, определи тип по содержимому.
- Если данных не хватает (автор, город, издательство, год, страницы, URL, дата обращения и т. п.), НЕ придумывай.
- Не переводи сами библиографические записи: язык, названия и данные источников должны остаться на языке пользовательского ввода.
- Комментарии, пояснения и блок с недостающими данными пиши на языке интерфейса: {comment_language}.
- Никогда не показывай пользователю служебные префиксы TYPE=... в итоговом ответе.
- Верни ответ строго в двух блоках:
  {result_header}:
  1. исправленная запись первой строки
  2. исправленная запись второй строки
  ...

  {missing_header}:
  1. недостающие данные для первой строки
  2. недостающие данные для второй строки
  ...
- Номера в блоке {missing_header} должны соответствовать номерам строк в блоке {result_header}.
- Если нет недостающих данных, не возвращай блок {missing_header}

ИСХОДНЫЙ СПИСОК:
{bibliography_text}

{result_header}:
"""

    def _parse_response(self, text: str, fallback_entries: List[str] = None) -> List[str]:
        """Парсинг ответа модели в пользовательский нумерованный результат.

        Модели не всегда строго соблюдают формат, поэтому здесь дополнительно:
        отделяются исправленные записи от блока недостающих данных, удаляются
        служебные TYPE-префиксы и скрывается пустой блок "НЕ ХВАТАЕТ ДАННЫХ".
        """
        fixed_header = "ИСПРАВЛЕННЫЙ СПИСОК:"
        missing_header = "НЕ ХВАТАЕТ ДАННЫХ:"
        fixed_lines = []
        missing_lines = []
        current_section = None

        for raw_line in text.strip().split('\n'):
            line = self._clean_model_line(raw_line)
            if not line:
                continue

            if self._is_fixed_header(line):
                current_section = "fixed"
                continue
            if self._is_missing_header(line):
                current_section = "missing"
                continue

            if current_section == "missing":
                missing_lines.append(line)
            elif current_section == "fixed":
                fixed_lines.append(line)
            elif self._looks_like_missing_line(line):
                missing_lines.append(line)
            else:
                fixed_lines.append(line)

        if not fixed_lines and fallback_entries:
            fixed_lines = [
                f"{i}. {self._clean_source_entry(entry)}"
                for i, entry in enumerate(fallback_entries, start=1)
            ]

        fixed_lines = self._renumber_lines(fixed_lines)
        missing_lines = self._renumber_lines(self._filter_empty_missing_lines(missing_lines))

        result = []
        if fixed_lines:
            result.append(fixed_header)
            result.extend(fixed_lines)
        if missing_lines:
            if result:
                result.append("")
            result.append(missing_header)
            result.extend(missing_lines)
        return result

    @staticmethod
    def _clean_model_line(line: str) -> str:
        """Удаление служебных TYPE-префиксов без потери нумерации ответа."""
        line = line.strip()
        if not line:
            return ""

        line = re.sub(
            r'(^|[\s:;,\-—–])TYPE=[^:\s]+(?:\s*[:\-—–]\s*|\s+)?',
            lambda match: match.group(1),
            line
        )
        line = re.sub(r'\s{2,}', ' ', line).strip()
        line = re.sub(r'^(\d+[\.\)])\s*', r'\1 ', line)

        if re.fullmatch(r'TYPE=[^:\s]+', line, flags=re.IGNORECASE):
            return ""
        return line

    @staticmethod
    def _clean_source_entry(line: str) -> str:
        line = re.sub(r'^TYPE=[^:\s]+(?:\s*[:\-—–]\s*|\s+)', '', line.strip())
        return line.strip()

    @staticmethod
    def _is_fixed_header(line: str) -> bool:
        normalized = line.strip().rstrip(":").lower()
        return normalized in {
            "исправленный список",
            "исправленный список литературы",
            "fixed list",
            "corrected list",
            "修正列表",
        }

    @staticmethod
    def _is_missing_header(line: str) -> bool:
        normalized = line.strip().rstrip(":").lower()
        return normalized in {
            "не хватает данных",
            "недостающие данные",
            "missing data",
            "缺少数据",
        }

    @staticmethod
    def _looks_like_missing_line(line: str) -> bool:
        normalized = line.lower()
        return (
            normalized.startswith("не хватает")
            or normalized.startswith("недоста")
            or "не является библиографическим источником" in normalized
            or normalized.startswith("missing")
        )

    @staticmethod
    def _renumber_lines(lines: List[str]) -> List[str]:
        result = []
        for index, line in enumerate(lines, start=1):
            content = re.sub(r'^\d+[\.\)]\s*', '', line).strip()
            if content:
                result.append(f"{index}. {content}")
        return result

    @staticmethod
    def _filter_empty_missing_lines(lines: List[str]) -> List[str]:
        """Удаление строк, которые означают отсутствие недостающих данных."""
        empty_markers = {
            "",
            "-",
            "—",
            "нет",
            "отсутствуют",
            "не требуется",
            "данных нет",
            "блок отсутствует",
            "отсутствует блок",
        }
        result = []
        for line in lines:
            content = re.sub(r'^\d+[\.\)]\s*', '', line).strip()
            normalized = content.strip(" .;:-—()").lower()
            if normalized in empty_markers:
                continue
            result.append(line)
        return result

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


# ==================== GIGACHAT PROVIDER ====================

class GigaChatProvider(YandexGPTProvider):
    """ИИ-агент GigaChat.

    Наследует правила промпта и постобработку от YandexGPTProvider, но
    использует другой протокол авторизации: сначала получает OAuth-токен,
    затем отправляет chat completion запрос в GigaChat API.
    """

    SCOPE = "GIGACHAT_API_PERS"
    ROOT_CA_URL = "https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt"

    def __init__(self, client_id: str = None):
        self.client_id = client_id or os.getenv("GIGACHAT_CLIENT_ID")
        self.oauth_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        self.chat_url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        self._access_token = None
        self.verify_bundle = self._get_verify_bundle()

        if not self.client_id:
            raise ValueError(
                "GigaChat Authorization Key не найден!\n"
                "Укажи его в настройках ИИ-агента."
            )

    def fix_text(self, text_lines: List[str], rules_context: str = "", ui_language: str = "ru_RU") -> Dict:
        """Исправление текста через GigaChat."""
        try:
            prompt = self._build_prompt(text_lines, ui_language)
            token = self._get_access_token()
            payload = {
                "model": "GigaChat",
                "messages": [
                    {
                        "role": "system",
                        "content": "Ты — помощник по приведению библиографических записей к правилам оформления, заданным пользователем. Следуй только правилам из пользовательского запроса. Не используй внешние знания о ГОСТ, если они противоречат указанным правилам."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.1,
                "stream": False
            }
            response = requests.post(
                self.chat_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                json=payload,
                timeout=60,
                verify=self.verify_bundle
            )

            if response.status_code != 200:
                self._log_error(f"HTTP {response.status_code}", response.text)
                return {
                    'success': False,
                    'error': f"Ошибка API GigaChat: {response.status_code}\n{response.text}",
                    'provider': self.get_name(),
                    'timestamp': datetime.now().isoformat()
                }

            result = response.json()
            fixed_text = result["choices"][0]["message"]["content"]
            self._log_raw_response(fixed_text, text_lines)
            return {
                'success': True,
                'fixed_lines': self._parse_response(fixed_text, text_lines),
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

    def _get_access_token(self) -> str:
        """Получение OAuth-токена GigaChat по Authorization Key."""
        if self._access_token:
            return self._access_token

        response = requests.post(
            self.oauth_url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "RqUID": str(uuid.uuid4()),
                "Authorization": f"Basic {self._normalize_authorization_key(self.client_id)}"
            },
            data={"scope": self.SCOPE},
            timeout=30,
            verify=self.verify_bundle
        )
        if response.status_code != 200:
            self._log_error(f"OAuth HTTP {response.status_code}", response.text)
            raise ValueError(f"Не удалось получить токен GigaChat: {response.status_code}\n{response.text}")

        self._access_token = response.json()["access_token"]
        return self._access_token

    @staticmethod
    def _normalize_authorization_key(value: str) -> str:
        """Приведение пользовательского ввода к формату Basic credentials.

        Пользователь обычно вставляет готовый Authorization Key из кабинета.
        Для удобства также поддерживается строка "Basic ..." и пара
        "client_id:client_secret", которая кодируется в base64 автоматически.
        """
        value = (value or "").strip()
        if value.lower().startswith("basic "):
            value = value[6:].strip()
        if ":" in value and " " not in value:
            return base64.b64encode(value.encode("utf-8")).decode("ascii")
        return value

    def _get_verify_bundle(self) -> str:
        """Подготовка CA-bundle для проверки SSL-сертификатов GigaChat.

        API GigaChat использует цепочку с российским корневым сертификатом,
        которого нет в стандартном certifi. Поэтому приложение один раз
        скачивает корневой сертификат Минцифры и добавляет его к certifi.
        """
        cert_dir = Path.cwd() / "data" / "certs"
        cert_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = cert_dir / "gigachat_ca_bundle.pem"
        root_ca_path = cert_dir / "russian_trusted_root_ca_pem.crt"

        if not root_ca_path.exists():
            self._download_root_ca(root_ca_path)

        if not bundle_path.exists() or root_ca_path.stat().st_mtime > bundle_path.stat().st_mtime:
            shutil.copyfile(certifi.where(), bundle_path)
            with open(root_ca_path, "rb") as src, open(bundle_path, "ab") as dst:
                dst.write(b"\n")
                dst.write(src.read())

        return str(bundle_path)

    def _download_root_ca(self, target_path: Path):
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        response = requests.get(self.ROOT_CA_URL, timeout=30, verify=False)
        response.raise_for_status()
        target_path.write_bytes(response.content)

    def get_name(self) -> str:
        return "GigaChat"


# ==================== FACTORY ====================

class AIProviderFactory:
    """Фабрика для создания ИИ-агентов по строковому идентификатору."""

    @staticmethod
    def create_provider(provider_name: str, settings: Dict[str, str] = None) -> AIProvider:
        """
        Создание провайдера по имени

        Args:
            provider_name: Название ИИ-агента ('yandex' или 'gigachat')

        Returns:
            Экземпляр провайдера
        """
        settings = settings or {}
        if provider_name == "yandex":
            return YandexGPTProvider(
                api_key=unprotect_secret(settings.get("yandex_api_key", "").strip()),
                folder_id=unprotect_secret(settings.get("yandex_folder_id", "").strip())
            )
        if provider_name == "gigachat":
            return GigaChatProvider(
                client_id=unprotect_secret(settings.get("gigachat_client_id", "").strip())
            )
        raise ValueError(f"Неизвестный ИИ-агент: {provider_name}")
