"""Генерация субтитров ASS/SRT из текста + длительности аудио.

Два режима (выбираются конфигом, не кодом):
- точные word-тайминги, если TTS/ASR их отдал (words=[{w,start,end}]);
- оценочная раскладка по символам, если таймингов нет (fallback).
Никаких привязок к модели: вход — обычный dict из ITTS.synthesize()/IASR.transcribe().
"""
from __future__ import annotations

_MIN_DUR = 1.2  # минимальная длительность реплики субтитров, сек


def _ts(t: float) -> tuple[int, int, int, int]:
    ms = int(round(t * 1000))
    h = ms // 3600_000; ms %= 3600_000
    m = ms // 60_000; ms %= 60_000
    s = ms // 1000; ms %= 1000
    return h, m, s, ms


def srt_time(t: float) -> str:
    h, m, s, ms = _ts(t)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_time(t: float) -> str:
    h, m, s, cs = _ts(t)
    return f"{h}:{m:02d}:{s:02d}.{cs // 10:02d}"


def chunks_from_words(words: list[dict], max_chars: int = 42,
                      max_gap: float = 0.8, min_dur: float = 1.2) -> list[tuple[float, float, str]]:
    """Собрать слова в реплики (cue'ы) по границам пунктуации/длины."""
    cues: list[tuple[float, float, str]] = []
    cur: list[str] = []
    start = None
    prev_end = None
    for wd in words:
        w, st, en = wd.get("w", "").strip(), wd.get("start", 0.0), wd.get("end", 0.0)
        if not w:
            continue
        if start is None:
            start = st
        elif prev_end is not None and st - prev_end > max_gap:
            # большой разрыв — закрываем текущую реплику
            cues.append((start, prev_end, " ".join(cur)))
            cur, start = [], st
        cur.append(w)
        prev_end = en
        if len(" ".join(cur)) >= max_chars or w.endswith((".", "?", "!", ",")):
            cues.append((start, en, " ".join(cur)))
            cur, start = [], None
    if cur and start is not None and prev_end is not None:
        cues.append((start, prev_end, " ".join(cur)))
    # нормализация: объединяем слишком короткие реплики с соседями
    fixed: list[tuple[float, float, str]] = []
    for a, b, txt in cues:
        if fixed and (b - a) < min_dur:
            pa, pb, pt = fixed[-1]
            fixed[-1] = (pa, b, f"{pt} {txt}".strip())
        else:
            fixed.append((a, b, txt))
    if len(fixed) == 1 and (fixed[0][1] - fixed[0][0]) < min_dur:
        fixed[0] = (fixed[0][0], max(fixed[0][1], min_dur), fixed[0][2])
    return fixed


def estimate_cues(text: str, duration: float, max_chars: int = 42) -> list[tuple[float, float, str]]:
    """Fallback без таймингов: распределяем реплики пропорционально длине."""
    sentences = [s.strip() for s in text.replace("\n", " ").split(".")]
    parts: list[str] = []
    for sent in sentences:
        while len(sent) > max_chars:
            cut = sent.rfind(" ", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            parts.append(sent[:cut].strip()); sent = sent[cut:].strip()
        if sent:
            parts.append(sent)
    total_chars = sum(len(p) for p in parts) or 1
    cues, t = [], 0.0
    for p in parts:
        dur = duration * len(p) / total_chars
        cues.append((t, t + dur, p))
        t += dur
    return cues


def build_cues(text: str, duration: float, words: list[dict] | None = None,
               max_chars: int = 42) -> list[tuple[float, float, str]]:
    if words:
        cues = chunks_from_words(words, max_chars=max_chars)
        if cues:
            return cues
    return estimate_cues(text, duration, max_chars=max_chars)


def to_srt(cues: list[tuple[float, float, str]]) -> str:
    out = []
    for i, (a, b, txt) in enumerate(cues, 1):
        out.append(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{txt}\n")
    return "\n".join(out)


def to_ass(cues: list[tuple[float, float, str]], *, play_res=(1920, 1080),
           font="DejaVu Sans", size=54) -> str:
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {play_res[0]}\n"
            f"PlayResY: {play_res[1]}\nWrapStyle: 0\n\n[V4+ Styles]\n"
            f"Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, Alignment\n"
            f"Style: Cap,{font},{size},&H00FFFFFF,&H00000000,2\n\n[Events]\n"
            "Format: Layer, Start, End, Style, Text\n")
    lines = []
    for a, b, txt in cues:
        lines.append(f"Dialogue: 0,{ass_time(a)},{ass_time(b)},Cap,{{\\an2}}{txt}")
    return head + "\n".join(lines) + "\n"
