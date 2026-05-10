import re


def classify_entry(entry: str) -> str:
    """Грубая эвристическая классификация типа источника"""
    text = entry.strip()
    norm = text.lower()

    if re.search(r'\bгост\b', norm) or 'гост р' in norm:
        return "gost_standard"

    if re.search(r'\bфедер\.?\s+закон\b', norm) or re.search(r'№\s*\d+\s*[-–]\s*фз\b', norm):
        return "federal_law"

    if re.search(r'\bдис\.\b', norm) or re.search(r'\bавтореф\.\b', norm) or 'канд.' in norm or 'д-ра' in norm:
        return "dissertation"

    archive_hits = sum(bool(re.search(p, norm)) for p in [r'\bф\.\s*\d+', r'\bоп\.\s*\d+', r'\bд\.\s*\d+', r'\bл\.\s*\d+'])
    if archive_hits >= 2:
        return "archive"

    if 'http://' in norm or 'https://' in norm or 'url:' in norm or 'электронный ресурс' in norm:
        return "electronic"

    if re.search(r'\bв\s*\d+\s*т\.', norm) or re.search(r'\bт\.\s*\d+', norm):
        return "multi_volume"

    if '//' in text:
        if re.search(r'журнал|вестник|alma mater|№\s*\d+', norm):
            return "journal_article"
        if re.search(r'сборник|материал|труды|конф|отв\.\s*ред', norm):
            return "collection_article"
        return "article"

    if re.search(r'\bизд-во\b|\bиздательство\b', norm) and re.search(r'\b\d{4}\b', norm):
        return "book"

    if re.search(r'\b\d{4}\b', norm) and re.search(r'\bс\.\b', norm):
        return "book"

    return "unknown"


def analyze_entry(entry: str) -> tuple[str, list[str]]:
    """Определение типа и недостающих данных (грубые эвристики)."""
    entry_type = classify_entry(entry)
    norm = entry.lower()
    missing = []

    def has_author() -> bool:
        return bool(re.search(r'\b[А-ЯЁA-Z][а-яёa-z-]+\s+[А-ЯЁA-Z]\.\s*[А-ЯЁA-Z]\.\b', entry))

    def has_year() -> bool:
        return bool(re.search(r'\b(19|20)\d{2}\b', entry))

    def has_pages() -> bool:
        return bool(re.search(r'\b\d+\s*с\.\b', norm)) or bool(re.search(r'\bс\.\s*\d+', norm))

    def has_url() -> bool:
        return 'http://' in norm or 'https://' in norm or 'url:' in norm

    def has_access_date() -> bool:
        return bool(re.search(r'дата\s+обращения:\s*\d{2}\.\d{2}\.\d{4}', norm))

    def has_publisher() -> bool:
        return 'изд-во' in norm or 'издательство' in norm or re.search(r'\bизд\.\b', norm)

    def has_city() -> bool:
        return bool(re.search(r'\bм\.|москва|спб\.|санкт-петербург|екатеринбург|новосибирск|казань|пермь|уфа|челябинск|самара|омск|краснодар|ростов-на-дону|нижний новгород\b', norm)) \
            or bool(re.search(r'\b[А-ЯЁA-Z][а-яёa-z-]+\s*:\s*', entry))

    def has_journal() -> bool:
        return '//' in entry or bool(re.search(r'журнал|вестник', norm))

    def has_number() -> bool:
        return bool(re.search(r'№\s*\d+', entry))

    if entry_type in ("book", "multi_volume"):
        if not has_author():
            missing.append("автор")
        if not has_city():
            missing.append("город")
        if not has_publisher():
            missing.append("издательство")
        if not has_year():
            missing.append("год")
        if not has_pages():
            missing.append("страницы")

    if entry_type in ("journal_article", "collection_article", "article"):
        if not has_author():
            missing.append("автор")
        if not has_journal():
            missing.append("источник (журнал/сборник)")
        if not has_year():
            missing.append("год")
        if not has_number():
            missing.append("номер")
        if not has_pages():
            missing.append("страницы")

    if entry_type == "gost_standard":
        if not has_year():
            missing.append("год")
        if not has_url():
            missing.append("URL")
        if not has_access_date():
            missing.append("дата обращения")

    if entry_type == "federal_law":
        if not has_year():
            missing.append("год")
        if not has_url():
            missing.append("URL")
        if not has_access_date():
            missing.append("дата обращения")

    if entry_type == "dissertation":
        if not has_author():
            missing.append("автор")
        if not has_year():
            missing.append("год")
        if not has_pages():
            missing.append("страницы")

    if entry_type == "archive":
        if not re.search(r'\bф\.\s*\d+', norm):
            missing.append("фонд (ф.)")
        if not re.search(r'\bоп\.\s*\d+', norm):
            missing.append("опись (оп.)")
        if not re.search(r'\bд\.\s*\d+', norm):
            missing.append("дело (д.)")
        if not re.search(r'\bл\.\s*\d+', norm):
            missing.append("лист (л.)")

    if entry_type == "electronic":
        if not has_url():
            missing.append("URL")
        if not has_access_date():
            missing.append("дата обращения")
        if not has_year():
            missing.append("год")

    return entry_type, missing
