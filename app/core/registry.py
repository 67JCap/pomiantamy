"""Plugin registry: строка `backend:` из YAML -> класс-реализация интерфейса.

Единственное место в проекте, где имена моделей/бэкендов связаны с кодом.
Добавить новый бэкенд = register(...) в его файле + строка в settings.yaml.
"""
from __future__ import annotations

import importlib
from typing import Any, Callable

_REG: dict[str, dict[str, Callable[..., Any]]] = {
    "llm": {}, "embed": {}, "asr": {}, "tts": {}, "vision": {},
    "source": {}, "sink": {},
}


def register(kind: str, name: str):
    """Декоратор: @register('llm', 'ollama') над классом OllamaLLM."""
    def deco(cls):
        _REG[kind][name] = cls
        return cls
    return deco


def resolve(kind: str, cfg: dict) -> Any:
    """Собрать экземпляр по конфигу {backend: имя, ...остальные параметры}.

    Поддерживает fallback: если основной бэкенд не поднимается — пробуем следующий.
    """
    backend = cfg["backend"]
    if backend not in _REG[kind]:
        # ленивая загрузка модуля по соглашению: app/ai/<kind>/<backend>.py
        module_missing = False
        try:
            importlib.import_module(f"app.ai.{kind}.{backend}")
        except ModuleNotFoundError as e:
            # модуль бэкенда отсутствует -> неизвестный backend;
            # но если не найден ЗАВИСИМЫЙ пакет внутри бэкенда — сообщаем явно
            if e.name and (e.name == f"app.ai.{kind}.{backend}" or
                           e.name.startswith(f"app.ai.{kind}.{backend}.")):
                module_missing = True
            else:
                raise RuntimeError(
                    f"Backend '{backend}' ({kind}) требует пакет '{e.name}'. "
                    f"Установите его (requirements-full.txt) или смените backend в YAML"
                ) from e
    if backend not in _REG[kind]:
        hint = "" if module_missing else " (модуль импортирован, но не зарегистрировался)"
        raise KeyError(f"Неизвестный backend '{backend}' для '{kind}'.{hint} "
                       f"Доступны: {sorted(_REG[kind])}")
    return _REG[kind][backend](**{k: v for k, v in cfg.items() if k != "backend"})


def resolve_with_fallback(kind: str, cfg: dict) -> Any:
    try:
        return resolve(kind, cfg)
    except Exception as e:  # noqa: BLE001
        fb = cfg.get("fallback")
        if not fb:
            raise
        print(f"[registry] {kind}/{cfg['backend']} недоступен ({e}); fallback -> {fb['backend']}")
        return resolve(kind, fb)
