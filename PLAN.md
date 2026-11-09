# PLAN — ИИ-агрегатор новостей Беларуси

## 0. Конечная цель
Двухэтапный проект:
- **Этап A (MVP):** агрегатор → дедупликация → категоризация → краткая выкладка + ссылки/картинки/видео.
- **Этап B:** авторский Telegram-канал: авто-публикации, ИИ-диктор (TTS) с субтитрами и видеорядом.

Жёсткое требование: **взаимозаменяемость всех ИИ-компонентов** (LLM, ASR, TTS, vision, эмбеддинги)
через единые интерфейсы + конфиг. Никакого хардкода модели в коде бизнес-логики.

---

## 1. Структура проекта

```
bynews/
├── config/
│   ├── settings.yaml            # уровни моделей, лимиты, пороги, пути
│   ├── sources.yaml             # реестр источников (RSS/API/скрейпер) — расширяется без кода
│   └── prompts/                 # промпты как файлы (версионируются, правятся без кода)
│       ├── classify.txt
│       ├── summarize_brief.txt
│       ├── script_tts.txt        # сценарий для диктора
│       └── media_caption.txt
├── app/
│   ├── core/                    # без зависимостей от конкретных моделей
│   │   ├── interfaces.py        # ABC: ILLM, IEmbedder, ITTS, IASR, IVision, ISource, ISink
│   │   ├── models.py            # dataclass: NewsItem, MediaRef, Category, Brief
│   │   ├── registry.py          # plugin-registry: имя из YAML -> класс (DI без хардкода)
│   │   └── bus.py               # очередь событий (Redis или in-process fallback)
│   ├── ingest/                  # подключение к интернету и источникам
│   │   ├── http.py              # общий aiohttp-клиент: retry, proxy, user-agent, rate-limit
│   │   ├── rss.py               # RSS/Atom (feedparser)
│   │   ├── telegram_reader.py   # Telethon: чтение каналов/чатов (главный источник BY-новостей)
│   │   ├── scraper.py           # playwright: сайты без RSS
│   │   ├── vk_youtube.py        # API-парсеры видео-источников
│   │   └── media_harvest.py     # извлечение картинок/видео из страниц и постов
│   ├── process/                 # очистка и обогащение
│   │   ├── dedup.py             # minhash + эмбеддинги (порог из конфига)
│   │   ├── classify.py          # категории: аварии/политзаявления/репрессии/оппозиция/иное
│   │   ├── geoloc.py            # опционально: город/регион из текста
│   │   ├── lang.py              # определение языка, перевод RU->BY при необходимости
│   │   └── credibility.py       # вес источника, подтверждение из N независимых источников
│   ├── ai/                      # РЕАЛИЗАЦИИ интерфейсов — по одной папке на бэкенд
│   │   ├── llm/
│   │   │   ├── ollama.py        # локальные модели (основной режим для RTX 3060)
│   │   │   ├── openai_compat.py # OpenAI-compatible API (OpenRouter, vLLM, LM Studio)
│   │   │   └── cloud_openai.py  # прямой OpenAI/Anthropic (опционально, через тот же интерфейс)
│   │   ├── embed/
│   │   │   ├── sentence_transformers.py  # локально
│   │   │   └── openai_embed.py           # API
│   │   ├── tts/
│   │   │   ├── piper.py         # локальный быстрый RU TTS
│   │   │   ├── xtts.py          # XTTS-v2 (клонирование голоса, требует VRAM)
│   │   │   └── elevenlabs.py    # API
│   │   ├── asr/
│   │   │   └── faster_whisper.py  # транскрибация видео/аудио из источников
│   │   └── vision/
│   │       ├── moondream.py     # локальный captioning картинок
│   │       └── gpt4o_vision.py  # API-аналог (тот же интерфейс)
│   ├── render/                  # Этап B: видео-новость
│   │   ├── subtitles.py         # word-level тайминги из ASR/TTS -> SRT/ASS
│   │   ├── slideshow.py         # ffmpeg: картинки+видеоряд+текст поверх
│   │   └── compose.py           # сборка финального ролика
│   ├── sinks/                   # куда отдаём результат (тоже плагины)
│   │   ├── console.py / jsonl.py / sqlite.py
│   │   └── telegram_channel.py  # aiogram/Telethon: пост + медиа + видео
│   ├── pipeline/
│   │   ├── dag.py               # оркестратор этапов (in/out контракты)
│   │   └── jobs.py              # cron-циклы: ingest -> process -> brief -> publish
│   └── cli.py                   # `bynews run --once`, `bynews add-source ...`, `bynews preview`
├── storage/                     # SQLite (events, media index), LanceDB/FAISS (векторы)
├── tests/                       # фейковые LLM/Source — контракт-тесты интерфейсов
└── docker-compose.yml           # redis + ollama + postgres(опц.)
```

### Принцип взаимозаменяемости (ключевой)
1. Бизнес-логика знает только ABC из `core/interfaces.py`.
2. Выбор реализации — **только** в `settings.yaml`:
   ```yaml
   ai:
     llm:      {backend: ollama, model: "qwen2.5:7b-instruct", fallback: {backend: openai_compat, model: "llama-3.1-8b"}}
     embed:    {backend: sentence_transformers, model: "cointegrated/rubert-tiny2"}
     tts:      {backend: piper, voice: "ru_RU-midia-medium"}
     asr:      {backend: faster_whisper, model: "small"}
     vision:   {backend: moondream}
   ```
3. `registry.py` резолвит `backend:` строку в класс; добавление нового бэкенда = один файл + одна строка YAML.
4. Fallback-цепочки: если локальная модель недоступна/перегружена — автоматический переход на резервную.

---

## 2. Как подключиться к интернету

| Задача | Решение |
|---|---|
| HTTP-запросы (RSS, API, страницы) | `aiohttp` в `ingest/http.py`: пул соединений, retry+backoff, ротация User-Agent, таймауты |
| Сайты с JS-рендерингом | Playwright (headless chromium) — только для точечных источников |
| Telegram-каналы (главный поток BY-новостей) | Telethon (MTProto, аккаунт-читатель) — доступ к постам, медиа, историям быстрее и полнее любого RSS |
| Прокси/гео-блокировки | переменные `HTTP(S)_PROXY` / SOCKS5 в конфиге клиента; для BY-ресурсов — зеркала (bycall/presspartisan-практики: use of mirrors & archives) |
| Rate-limit и вежливость | per-source `politeness_delay`, кеш `ETag/Last-Modified` |
| Видеоконтент | yt-dlp (YouTube/Rutube/VK-видео из постов) |

Все сетевые клиенты проходят через **единую точку** (`http.py`), чтобы прокси/ретраи/метрики не дублировались.

## 3. Как подключать источники новостей

Источник = запись в `sources.yaml` + тип плагина. Новый источник не требует кода:

```yaml
sources:
  - id: nexta_live
    type: rss
    url: https://nexta.live/rss.xml
    weight: 0.9          # доверие
    tags: [политические заявления, репрессии]
  - id: si_chainsaw
    type: telegram
    handle: @chainsaw_si
    weight: 0.8
    tags: [аварии]
  - id: reform_by
    type: telegram
    handle: @reformbel
    weight: 0.7
    tags: [оппозиция]
  - id: tut_onliner_incidents
    type: scraper
    url: https://…          # CSS-селекторы тоже в конфиге
```

Кандидаты для старта (проверить живость URL на этапе настройки): NEXTA, Reform.by, Пул Лэнд Бай,
Сайменка/Чейнсо (аварии), Белсат, Navibelay, Onliner/Автобуса (ДТП), архив Nashaniva.
Каждый источник даёт: текст, ссылку-первоисточник, медиа (фото/видео через `media_harvest.py`).

---

## 4. Пайплайн (runtime flow)

```
[cron every 5–15 min]
INGEST ──> NORMALIZE ──> MEDIA HARVEST ──> DEDUP ──> CLASSIFY ──> ENRICH ──> BRIEF ──> SINK
 RSS/TG/   NewsItem     фото/видео        минхэш+   категория    связать    LLM-      JSONL/
 scraper  dataclass     + yt-dlp +        эмбед-    + confidence + дублы    выкладка  SQLite/
 playwr.   (url,ts)     ASR-транскрипт    инги      источника  в один      уровня    Telegram
                                            (ru)               кейс        short/med
```

1. **Ingest** — параллельно все активные источники; сырьё пишется в `data/raw` (воспроизводимость).
2. **Normalize** — единый `NewsItem{title, text, url, ts, source_id, media[]}`.
3. **Media harvest** — `<img>`/`og:image`/Telegram-медиа/видео; скачивание + хэш + индекс в SQLite.
4. **Dedup/enrich** — порог сходства из конфига; группировка сообщений об одном событии из разных источников (это и есть «подтверждённость»).
5. **Classify** — zero-shot/few-shot LLM по 4 целевым категориям + «иное»; temperature=0, JSON-schema вывод.
6. **Brief** — генерация выкладки выбранного уровня (`brief_style: terse|standard|detailed` в конфиге) со списком ссылок.
7. **Sink** — консоль/файл/БД; на Этапе B — публикация в Telegram.

**Этап B (видео-выпуск)** дополняет: Script (LLM) → TTS (Piper/XTTS) → ASR-for-timing → Subtitles (ASS) → Slideshow (ffmpeg + собранные медиа) → Telegram video.

---

## 5. Рекомендации моделей под RTX 3060 12GB / 16GB RAM

Правило: всё помещается в 12GB VRAM с KV-cache; 16GB RAM — один большой процесс одновременно.

| Слот | Основная рекомендация | Почему | Альтернативы (swap одной строкой YAML) |
|---|---|---|---|
| **LLM (классификация, выкладки, сценарии)** | **Qwen2.5 7B Instruct, Q4_K_M GGUF через Ollama** (~5–6 GB VRAM) | лучший ru-качество среди 7B, structured JSON output, быстрая на 3060 | Llama-3.1-8B (сильнее reasoning, слабее ru), Mistral-7B-Instruct-v0.3; при нехватке RAM — Phi-3.5-mini / Gemma-2 2B как «light» уровень |
| **LLM heavy (редко, длинные саммари)** | Qwen2.5-14B Q4 (~9 GB) — впритык, но влезает | качество выше 7B | облачный API через `openai_compat` (OpenRouter) как fallback |
| **Embeddings (дедуп)** | `cointegrated/rubert-tiny2` или `paraphrase-multilingual-MiniLM-L12-v2` | ru-специфичные, <1 GB, CPU ok | API-эмбеддинги |
| **ASR (транскрипт видео/голосовых)** | faster-whisper `small` (ru) ~2 GB VRAM; `medium` если качество критично | скорость на 3060 приемлема | large-v3 через облако |
| **TTS (диктор)** | **Piper** (голос `ru_RU`) — мгновенный, CPU, почти без VRAM | для конвейера важнее скорость/стабильность | XTTS-v2 (~5 GB VRAM, клонирование «авторского голоса»), ElevenLabs API (топ-качество) |
| **Vision (описание фото для видеоряда/альтов)** | Moondream2 (~2 GB) | локально, быстро | GPT-4o-mini vision API |
| **Субтитры** | word-timestamps из faster-whisper → ASS | без доп. моделей | — |

Сервисная обвязка: **Ollama** (или llama.cpp server) — LLM как локальный OpenAI-compatible endpoint; это значит, что код приложения вообще не различает «локально/облако».

---

## 6. Дорожная карта

| Неделя | Веха |
|---|---|
| 1 | Каркас, interfaces+registry, `sources.yaml`, RSS-ingest, JSONL-sink. Тесты на фейковых моделях. |
| 2 | Telethon-ingest + media harvest, дедуп (эмбеддинги), SQLite. |
| 3 | Ollama+Qwen2.5: classify+brief, промпты из файлов, CLI `run --once`, превью выкладок. |
| 4 | Credibility/clustering событий, настраиваемые стили выкладки, дашборд-вывод со ссылками/медиа. |
| 5–6 (Этап B) | TTS+субтитры+ffmpeg-ролик, Telegram-канал-бот, авто-расписание, A/B стилей подачи. |

## 7. Риски и меры
- Блокировки BY-ресурсов → Telegram как первичный канал + прокси/зеркала в конфиге.
- Дискриминация фейков → обязательный показатель «N независимых источников» в выкладке.
- Юридика (репрессивное законодательство РБ) → работа вне юрисдикции, анонимизация оператора, отсутствие хранения PII.
- Нехватка RAM при XTTS+LLM одновременно → последовательный конвейер (render-фаза отдельно) или fallback на Piper.
