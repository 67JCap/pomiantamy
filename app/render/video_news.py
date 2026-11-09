"""Этап B: Brief -> голос диктора (ITTS) -> субтитры -> mp4 с видеорядом.

VideoNewsRenderer получает компоненты ИЗВНЕ (DI): llm/tts/embedder/vision —
сам он не знает ни одной модели. Промпт сценария — config/prompts/script_tts.txt.
Все параметры видео — секция video_render в settings.yaml.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.interfaces import IEmbedder, ILLM, ITTS, IVision
from app.core.models import Brief, MediaType

from .ffmpeg_builder import render_slideshow
from .media_selector import rank_media
from .subtitles import build_cues, to_ass, to_srt


class VideoNewsRenderer:
    def __init__(self, tts: ITTS, params: dict, *, llm: ILLM | None = None,
                 embedder: IEmbedder | None = None, vision: IVision | None = None):
        self.tts = tts
        self.p = params or {}
        self.llm = llm
        self.embedder = embedder
        self.vision = vision
        self.out_dir = Path(self.p.get("output_dir", "data/videos"))
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def make_script(self, brief: Brief) -> str:
        """LLM переписывает выкладку в разговорный сценарий диктора.
        Если LLM нет/отказался — используем саму выкладку (fallback без кода)."""
        if self.llm is None or not self.p.get("rewrite_script", True):
            return brief.text
        try:
            tpl = (Path("config/prompts") / "script_tts.txt").read_text(encoding="utf-8")
            script = self.llm.complete(
                tpl.format(brief=brief.text, language=self.p.get("language", "ru")),
                temperature=0.3).strip()
            return script if len(script) > 20 else brief.text
        except Exception:  # noqa: BLE001
            return brief.text

    def render(self, brief: Brief, *, images: list[str] | None = None) -> dict[str, Any]:
        """images — готовый список локальных путей (для fake-медиа в тестах);
        по умолчанию видеоряд берётся из brief.media и ранжируется."""
        script = self.make_script(brief)
        base = self.out_dir / brief.event_id

        # 1) голоса диктора (backend выбирается YAML-строкой: piper/edge_tts/xtts)
        audio = self.tts.synthesize(script, str(base))
        duration = audio["duration"] or max(len(script) / 15.0, 5.0)

        # 2) субтитры: точные word-тайминги если есть, иначе оценочная раскладка
        cues = build_cues(script, duration, words=audio.get("words"),
                          max_chars=self.p.get("subtitle_max_chars", 42))
        ass_file, srt_file = f"{base}.ass", f"{base}.srt"
        w, h = self.p.get("width", 1280), self.p.get("height", 720)
        Path(ass_file).write_text(to_ass(cues, play_res=(w, h)), encoding="utf-8")
        Path(srt_file).write_text(to_srt(cues), encoding="utf-8")

        # 3) видеоряд по релевантности (IVision+IEmbedder; деградация без них)
        if images is None:
            media = rank_media(brief.media, script, embedder=self.embedder,
                               vision=self.vision, limit=self.p.get("max_frames", 8))
            images = [m.local_path for m in media if m.type == MediaType.IMAGE]
            used_urls = [m.url for m in media]
        else:
            used_urls = list(images)

        # 4) ffmpeg-сборка mp4
        meta = {"event_id": brief.event_id, "script": script, "audio": audio["path"],
                "subtitles_srt": srt_file, "media_used": used_urls}
        if not self.p.get("enabled_video", True):
            meta["video"] = None  # режим «голос+субтитры», картинка не нужна
        else:
            meta.update(render_slideshow(
                images, audio["path"], f"{base}.mp4",
                width=w, height=h, fps=self.p.get("fps", 30),
                subtitle_file=ass_file if self.p.get("burn_subtitles", True) else None))
        Path(f"{base}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
        return meta
