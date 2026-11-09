# bynews — ИИ-агрегатор новостей Беларуси (модульный, без привязки к моделям)

Два этапа: **A** — агрегатор с выкладками/ссылками/медиа; **B** — авто-Telegram-канал
с ИИ-диктором, субтитрами и видеорядом. Полные план и архитектура: [PLAN.md](PLAN.md).

## Быстрый старт (offline, без GPU и ключей)
```bash
pip install -r requirements-core.txt
python -m app.cli preview data/fixture.json     # весь пайплайн на FakeLLM/FakeEmbedder
```

## Боевой запуск (RTX 3060)
```bash
# 1. Локальный LLM-сервер (OpenAI-compatible):
ollama pull qwen2.5:7b-instruct && ollama serve

# 2. Зависимости полного контура:
pip install -r requirements-full.txt

# 3. Секреты только в окружении:
export TG_API_ID=... TG_API_HASH=...            # для чтения Telegram-источников
export OPENROUTER_API_KEY=...                    # опциональный облачный fallback

# 4. Цикл агрегации:
python -m app.cli run --once      # один проход ingest->dedup->classify->brief->sinks
python -m app.cli run --loop      # постоянно, интервал из settings.yaml
```

## Как поменять ИИ-модель (главное требование проекта)
Только `config/settings.yaml`, код не трогаем:
```yaml
ai:
  llm: {backend: ollama, model: "qwen2.5:14b-instruct-q4_K_M", ...}   # апгрейд локально
  # или облако: backend: openai_compat, base_url: https://openrouter.ai/api/v1
  tts: {backend: xtts, ...}      # Piper -> XTTS-v2 (клон голоса диктора)
```
Новый бэкенд = один файл-класс, реализующий ABC из `app/core/interfaces.py`,
помеченный `@register(kind, имя)`. Fallback-цепочки работают автоматически.

## Структура
```
config/       settings.yaml, sources.yaml, prompts/*.txt  (всё настраивается здесь)
app/core/     interfaces.py (ABC), models.py, registry.py (DI из YAML)
app/ingest/   http.py (proxy/retry), rss.py, telegram_reader.py (+media harvest)
app/process/  dedup.py (эмбеддинги), classify.py (категории + выкладка)
app/ai/       llm|embed|asr|tts|vision — по файлу на бэкенд, взаимозаменяемые
app/sinks/    console, jsonl, (telegram_channel — Этап B)
app/pipeline/ dag.py (оркестратор), preview.py (offline-тесты)
data/         raw/, media/, audio/, briefs.jsonl
```

## Категории
аварии • политические заявления • политические репрессии • ответы оппозиции • иное

## Безопасность и анонимность (важно для тематики)
- Секреты — только env-переменные; в git не попадают (см. .gitignore).
- Не храните PII; работайте с зеркалами/прокси (`network.proxy` в конфиге).
- Публикуйте канал от имени бота-администратора отдельным аккаунтом.

## Дорожная карта Этапа B
1. `app/render/`: script(LLM) → TTS(Piper/XTTS) → тайминги(ASR word_timestamps) → ASS-субтитры → ffmpeg-ролик из собранных медиа.
2. `app/sinks/telegram_channel.py`: пост + альбом медиа / готовое видео.
3. Настройка стиля подачи через `config/prompts/*` (правятся без кода).
