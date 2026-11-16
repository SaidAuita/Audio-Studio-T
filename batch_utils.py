"""Утилиты для пакетной обработки, навигации по десяткам и конвертации нумерации."""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

OUTPUT_DIR = Path("output")
VOICES_DIR = Path("voices")
OWN_FILE = "— свой файл / own file —"


def scan_voices() -> list[str]:
    """Сканирует папку voices/ на наличие аудиофайлов пресетов."""
    if not VOICES_DIR.exists():
        VOICES_DIR.mkdir(parents=True, exist_ok=True)
        return []
    exts = {".wav", ".mp3", ".flac", ".ogg"}
    files = [f.name for f in VOICES_DIR.iterdir() if f.is_file() and f.suffix.lower() in exts]
    files.sort(key=lambda s: s.lower())
    return files


def voice_path(name: str) -> Optional[str]:
    if not name or name == OWN_FILE:
        return None
    p = VOICES_DIR / name
    return str(p) if p.is_file() else None


def voice_ref_text(name: str) -> Optional[str]:
    """Возвращает сопутствующий текст (транскрипцию) для голоса из .txt или .lab файла."""
    if not name or name == OWN_FILE:
        return None
    p = VOICES_DIR / name
    stem = p.stem
    for ext in [".txt", ".lab"]:
        cand = VOICES_DIR / f"{stem}{ext}"
        if cand.is_file():
            try:
                txt = cand.read_text(encoding="utf-8", errors="replace").strip()
                if txt:
                    return txt
            except Exception:
                pass
    return None


def get_audio_seed(stem_or_filename: str) -> Optional[int]:
    """Извлекает значение seed из сопутствующего .txt файла метаданных в output/NUM/"""
    if not stem_or_filename:
        return None
    clean = Path(stem_or_filename).stem
    candidates = [
        OUTPUT_DIR / "NUM" / f"{clean}.txt",
        Path("output/NUM") / f"{clean}.txt",
        OUTPUT_DIR / f"{clean}.txt",
    ]
    for cand in candidates:
        if cand.is_file():
            try:
                for line in cand.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.strip().lower().startswith("seed:"):
                        val = line.split(":", 1)[1].strip()
                        return int(val)
            except Exception:
                pass
    return None


def parse_batch_script(content_or_path: str | Path, lang: str = "EN") -> list[dict]:
    """
    Разбор файла сценария для пакетного клонирования (напр. output/NUM/ru-en.txt).
    Поддерживает блоки [01.wav] или [01], с тегами RU: / EN: или простым текстом.
    """
    if not content_or_path:
        return []
    path = Path(content_or_path)
    if path.is_file():
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []
    elif isinstance(content_or_path, str) and ("\n" in content_or_path or "[" in content_or_path):
        content = content_or_path
    else:
        alt0 = Path.cwd() / content_or_path
        alt1 = OUTPUT_DIR / content_or_path
        if alt0.is_file():
            content = alt0.read_text(encoding="utf-8", errors="replace")
        elif alt1.is_file():
            content = alt1.read_text(encoding="utf-8", errors="replace")
        else:
            return []

    lines = content.splitlines()
    items = []
    curr_num_str = None
    curr_ru: list[str] = []
    curr_en: list[str] = []
    curr_raw: list[str] = []
    curr_tag = None

    def _flush():
        nonlocal curr_num_str, curr_ru, curr_en, curr_raw, curr_tag
        if curr_num_str is not None:
            try:
                val = int(curr_num_str)
            except ValueError:
                val = 0
            ru_text = " ".join(curr_ru).strip()
            en_text = " ".join(curr_en).strip()
            raw_text = " ".join(curr_raw).strip()

            target_lang = (lang or "EN").upper()
            if target_lang == "EN":
                chosen = en_text or raw_text or ru_text
            elif target_lang == "RU":
                chosen = ru_text or raw_text or en_text
            else:
                chosen = raw_text or (f"{ru_text}\n{en_text}".strip())

            items.append({
                "num_str": curr_num_str,
                "num": val,
                "text": chosen,
                "ru": ru_text,
                "en": en_text,
                "raw": raw_text,
            })

    for line in lines:
        m = re.match(r'^\s*\[(\d+)(?:\.\w+)?\]\s*$', line)
        if m:
            _flush()
            curr_num_str = m.group(1)
            curr_ru = []
            curr_en = []
            curr_raw = []
            curr_tag = None
            continue

        if curr_num_str is None:
            continue

        sline = line.strip()
        if not sline:
            curr_tag = None
            continue

        if sline.startswith("---") or re.match(r'^\d+\.\s+\S+', sline):
            curr_tag = None
            continue

        if re.match(r'^RU\s*:\s*', sline, re.IGNORECASE):
            curr_tag = "RU"
            text_part = re.sub(r'^RU\s*:\s*', '', sline, flags=re.IGNORECASE).strip()
            if text_part:
                curr_ru.append(text_part)
                curr_raw.append(text_part)
        elif re.match(r'^EN\s*:\s*', sline, re.IGNORECASE):
            curr_tag = "EN"
            text_part = re.sub(r'^EN\s*:\s*', '', sline, flags=re.IGNORECASE).strip()
            if text_part:
                curr_en.append(text_part)
                curr_raw.append(text_part)
        elif curr_tag == "RU":
            curr_ru.append(sline)
            curr_raw.append(sline)
        elif curr_tag == "EN":
            curr_en.append(sline)
            curr_raw.append(sline)
        else:
            curr_raw.append(sline)

    _flush()
    return items


def scan_num_folder() -> tuple[str, str]:
    """Сканирует папку output/NUM и находит минимальный и максимальный номера аудиофайлов."""
    num_dir = OUTPUT_DIR / "NUM"
    if not num_dir.exists():
        num_dir.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(r'^(\d+)\.(wav|mp3|flac|ogg)$', re.IGNORECASE)
    found_nums = []
    for p in num_dir.iterdir():
        if p.is_file():
            m = pattern.match(p.name)
            if m:
                found_nums.append((int(m.group(1)), m.group(1)))

    if not found_nums:
        return "01", "10"
    found_nums.sort(key=lambda x: x[0])
    return found_nums[0][1], found_nums[-1][1]


def get_num_files_list() -> list[str]:
    """Возвращает отсортированный список всех аудиофайлов из output/NUM."""
    num_dir = OUTPUT_DIR / "NUM"
    if not num_dir.exists():
        return []
    exts = {".wav", ".mp3", ".flac", ".ogg"}
    pattern = re.compile(r'^(\d+)(?:_(\d+))?\.', re.IGNORECASE)
    items = []
    for p in num_dir.iterdir():
        if p.is_file() and p.suffix.lower() in exts:
            m = pattern.match(p.name)
            if m:
                main_n = int(m.group(1))
                var_n = int(m.group(2)) if m.group(2) else -1
                items.append((main_n, var_n, str(p)))
            else:
                items.append((999999, 0, str(p)))
    items.sort(key=lambda x: (x[0], x[1]))
    return [x[2] for x in items]


def get_fragment_variants_info(num_val_or_str: int | str) -> tuple[Optional[Path], list[dict], int, str]:
    """
    Возвращает (base_file, variants, max_variant_idx, pad_str) для фрагмента num_val.
    """
    try:
        n = int(str(num_val_or_str).split()[0])
    except Exception:
        return None, [], 0, ""

    num_dir = OUTPUT_DIR / "NUM"
    if not num_dir.exists():
        return None, [], 0, f"{n:02d}"

    base_file = None
    pad_str = ""
    for candidate_str in [f"{n:03d}", f"{n:02d}", str(n)]:
        for ext in ["wav", "mp3", "flac", "ogg"]:
            cand = num_dir / f"{candidate_str}.{ext}"
            if cand.exists():
                base_file = cand
                pad_str = candidate_str
                break
        if base_file:
            break

    if not pad_str:
        has_3_digit = any(len(p.stem.split("_")[0]) >= 3 for p in num_dir.iterdir() if p.is_file() and p.stem.split("_")[0].isdigit())
        pad_str = f"{n:03d}" if (has_3_digit or n > 99) else f"{n:02d}"

    variants = []
    max_idx = 0
    pattern = re.compile(rf'^{re.escape(pad_str)}_(\d+)\.(wav|mp3|flac|ogg)$', re.IGNORECASE)
    for p in num_dir.iterdir():
        if p.is_file():
            m = pattern.match(p.name)
            if m:
                idx = int(m.group(1))
                if idx > max_idx:
                    max_idx = idx
                txt_meta = num_dir / f"{p.stem}.txt"
                variants.append({
                    "idx": idx,
                    "stem": p.stem,
                    "audio": p,
                    "meta": txt_meta if txt_meta.exists() else None,
                })

    variants.sort(key=lambda x: x["idx"])
    return base_file, variants, max_idx, pad_str


def make_variant_choices(base_file: Optional[Path], variants: list[dict], pad_str: str) -> list[str]:
    """Возвращает краткие названия вариантов без лишнего текста: ['81', '81_01', '81_02']."""
    choices = []
    if base_file:
        choices.append(pad_str)
    for v in variants:
        choices.append(v["stem"])
    return choices


def get_script_decades(file_path: str = "output/NUM/ru-en.txt", lang: str = "EN") -> list[str]:
    """Определяет список десятков (01-10, 11-20...) на основе файла сценария."""
    items = parse_batch_script(file_path, lang=lang)
    if not items:
        return ["01-10"]
    total = len(items)
    max_num = items[-1]["num"] if items else total
    use_3 = total > 99 or max_num > 99 or any(len(it.get("num_str", "")) >= 3 for it in items)
    pad_w = 3 if use_3 else 2

    decades = []
    for start in range(1, max_num + 1, 10):
        end = min(start + 9, max_num)
        decades.append(f"{start:0{pad_w}d}-{end:0{pad_w}d}")
    return decades or [f"{1:0{pad_w}d}-{min(10, max_num):0{pad_w}d}"]


def get_decade_data(decade_str: str, file_path_script: str, lang_choice: str = "EN") -> dict:
    """
    Возвращает данные для слотов десятка: кнопки 10 слотов и список реплик.
    """
    m = re.match(r'(\d+)-(\d+)', str(decade_str or ""))
    if not m:
        start_n, end_n = 1, 10
        pad_len = 2
    else:
        start_n = int(m.group(1))
        end_n = int(m.group(2))
        pad_len = max(len(m.group(1)), len(m.group(2)))

    items = parse_batch_script(file_path_script, lang=lang_choice)
    items_by_num = {it["num"]: it for it in items}

    num_dir = OUTPUT_DIR / "NUM"
    existing_nums = set()
    if num_dir.exists():
        ptn = re.compile(r'^(\d+)(?:_\d+)?\.(wav|mp3|flac|ogg)$', re.IGNORECASE)
        for p in num_dir.iterdir():
            if p.is_file():
                m_f = ptn.match(p.name)
                if m_f:
                    existing_nums.add(int(m_f.group(1)))

    slot_data = []
    for idx in range(10):
        curr_num = start_n + idx
        num_str = f"{curr_num:0{pad_len}d}"
        in_script = curr_num in items_by_num
        is_ready = curr_num in existing_nums

        if curr_num <= end_n:
            status_text = "[ready]" if is_ready else "[missing]"
            label = f"{num_str} {status_text}"
            slot_data.append({
                "num": curr_num,
                "num_str": num_str,
                "label": label,
                "ready": is_ready,
                "in_script": in_script,
                "visible": True,
            })
        else:
            slot_data.append({
                "num": curr_num,
                "num_str": num_str,
                "label": "",
                "ready": False,
                "in_script": False,
                "visible": False,
            })

    radio_choices = []
    for curr_num in range(start_n, end_n + 1):
        num_str = f"{curr_num:0{pad_len}d}"
        is_ready = curr_num in existing_nums
        stat = "[ready]" if is_ready else "[missing]"
        it = items_by_num.get(curr_num)
        snippet = it["text"].replace("\n", " ").strip() if it else "—"
        if len(snippet) > 85:
            snippet = snippet[:82] + "..."
        radio_choices.append(f"{num_str} {stat}: {snippet}")

    return {
        "start": start_n,
        "end": end_n,
        "pad_len": pad_len,
        "slots": slot_data,
        "phrases": radio_choices,
    }


def convert_numbering(target_len: int, convert_files: bool = True, convert_script: bool = True,
                      file_path_script: str = "output/NUM/ru-en.txt") -> str:
    """Конвертирует двухзначную нумерацию (01..99) в трехзначную (001..099) или обратно."""
    num_dir = OUTPUT_DIR / "NUM"
    report_lines = []
    renamed_files_count = 0

    if convert_files and num_dir.exists():
        pattern_file = re.compile(r'^(\d+)(_?\d*)\.(wav|mp3|flac|ogg|txt)$', re.IGNORECASE)
        files_to_rename = []
        for p in num_dir.iterdir():
            if p.is_file():
                m = pattern_file.match(p.name)
                if m:
                    orig_num_str = m.group(1)
                    suffix = m.group(2)
                    ext = m.group(3)
                    num_val = int(orig_num_str)
                    new_num_str = f"{num_val:0{target_len}d}"
                    if orig_num_str != new_num_str:
                        new_name = f"{new_num_str}{suffix}.{ext}"
                        files_to_rename.append((p, num_dir / new_name))

        for old_p, new_p in files_to_rename:
            try:
                old_p.rename(new_p)
                renamed_files_count += 1
            except Exception as e:
                print(f"[convert_numbering] rename error {old_p} -> {new_p}: {e}")

        report_lines.append(f"📁 Переименовано файлов в NUM: **{renamed_files_count}** шт.")

    renamed_tags_count = 0
    script_path = Path(file_path_script)
    if convert_script and script_path.exists():
        try:
            content = script_path.read_text(encoding="utf-8", errors="replace")

            def repl_tag(m):
                nonlocal renamed_tags_count
                num_val = int(m.group(1))
                new_num_str = f"{num_val:0{target_len}d}"
                ext_part = m.group(2) or ""
                renamed_tags_count += 1
                return f"[{new_num_str}{ext_part}]"

            new_content = re.sub(r'\[(\d+)(\.\w+)?\]', repl_tag, content)

            def repl_num_dot(m):
                num_val = int(m.group(1))
                new_num_str = f"{num_val:0{target_len}d}"
                return f"\n{new_num_str}. "

            new_content = re.sub(r'(?:^|\n)(\d+)\.\s+', repl_num_dot, new_content)

            if new_content != content:
                script_path.write_text(new_content, encoding="utf-8")
                report_lines.append(f"📄 Обновлено меток в сценарии {script_path.name}: **{renamed_tags_count}** шт.")
        except Exception as e_s:
            report_lines.append(f"⚠️ Ошибка правки сценария: {e_s}")

    return f"✅ Формат переведен на {target_len} знака.\n" + "\n".join(report_lines)
