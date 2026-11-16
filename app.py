"""Audio Studio T — современный интерфейс на NiceGUI для Fish Audio Drama 3.
Дизайн: Dark Studio (профессиональная тёмная тема, лаконичные элементы Quasar/NiceGUI).
Поддерживает два режима:
1. Длинный клон (Long Clone)
2. Пакетный клон (Batch Clone) с поддержкой вариантов и перевода нумерации.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import soundfile as sf
from nicegui import app, run, ui

import batch_utils as bu
import engine
from waveform_player import WaveformPlayer

# Настройка раздачи статики / медиафайлов
app.add_media_files("/media/output", "output")
app.add_media_files("/media/voices", "voices")
app.add_media_files("/media/temp", "temp")

os.makedirs("temp", exist_ok=True)
os.makedirs("output/NUM", exist_ok=True)

SETTINGS_FILE = Path(__file__).parent / "gui_config.json"
LANG_FILE = Path(__file__).parent / "lang.json"
LANGS = json.loads(LANG_FILE.read_text(encoding="utf-8")) if LANG_FILE.is_file() else {"EN": {}, "RU": {}}

def _(text: str) -> str:
    lang = getattr(state, "lang", "RU")
    return LANGS.get(lang, {}).get(text, text)

def load_settings() -> dict:
    if SETTINGS_FILE.is_file():
        try:
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[Settings] Error loading config: {e}")
    return {}


def save_settings():
    try:
        cfg = {
            "lang": getattr(state, "lang", "RU"),
            "selected_model": getattr(state, "selected_model", ""),
            # Пакетный клон
            "bc_preset": getattr(state, "bc_preset", ""),
            "bc_file_path": getattr(state, "bc_file_path", "output/NUM/ru-en.txt"),
            "bc_lang": getattr(state, "bc_lang", "EN"),
            "bc_temp": float(getattr(state, "bc_temp", 0.8)),
            "bc_top_p": float(getattr(state, "bc_top_p", 0.95)),
            "bc_seed": int(getattr(state, "bc_seed", -1)),
            "bc_use_plus_one": bool(getattr(state, "bc_use_plus_one", False)),
            "bc_num_from": str(getattr(state, "bc_num_from", "01")),
            "bc_num_to": str(getattr(state, "bc_num_to", "10")),
            "bc_to_end": bool(getattr(state, "bc_to_end", False)),
            "bc_skip_existing": bool(getattr(state, "bc_skip_existing", True)),
            # Длинный клон
            "lc_preset": getattr(state, "lc_preset", ""),
            "lc_temp": float(getattr(state, "lc_temp", 0.8)),
            "lc_top_p": float(getattr(state, "lc_top_p", 0.95)),
            "lc_seed": int(getattr(state, "lc_seed", -1)),
            "lc_max_chars": int(getattr(state, "lc_max_chars", 200)),
            "lc_gap": float(getattr(state, "lc_gap", 0.3)),
        }
        SETTINGS_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[Settings] Error saving config: {e}")


def get_available_scripts() -> list[str]:
    scripts = []
    p_num = Path("output/NUM")
    if p_num.is_dir():
        for f in p_num.glob("*.txt"):
            if not f.name.startswith("seed="):
                scripts.append(f"output/NUM/{f.name}")
    if Path("output").is_dir():
        for f in Path("output").glob("*.txt"):
            scripts.append(f"output/{f.name}")
    scripts = sorted(list(set(scripts)))
    if not scripts:
        scripts = ["output/NUM/ru-en.txt"]
    return scripts


class AppState:
    def __init__(self):
        cfg = load_settings()

        # Глобальные настройки
        self.lang = cfg.get("lang", "RU")
        self.models_list = engine.get_available_models()
        self.selected_model = cfg.get("selected_model", self.models_list[0] if self.models_list else engine.DEFAULT_MODEL)
        actual_voices = bu.scan_voices()
        self.voices_list = [bu.OWN_FILE] + actual_voices
        self.voice_selectors: list[Any] = []

        saved_preset = cfg.get("bc_preset")
        if saved_preset and saved_preset in self.voices_list and saved_preset != bu.OWN_FILE:
            self.bc_preset = saved_preset
        elif actual_voices:
            self.bc_preset = actual_voices[0]
        else:
            self.bc_preset = self.voices_list[0] if self.voices_list else ""
        
        # Длинный клон
        saved_lc_preset = cfg.get("lc_preset")
        self.lc_preset = saved_lc_preset if (saved_lc_preset and saved_lc_preset in self.voices_list) else self.bc_preset
        self.lc_ref_audio = ""
        self.lc_ref_text = ""
        if self.lc_preset and self.lc_preset != bu.OWN_FILE:
            p = bu.voice_path(self.lc_preset)
            if p:
                self.lc_ref_audio = p
                self.lc_ref_text = bu.voice_ref_text(self.lc_preset) or ""
        self.lc_text = (
            "Привет! Это новая гибридная студия синтеза речи Audio Studio T на базе NiceGUI и модели Fish Audio Drama 3. "
            "Здесь вы можете генерировать длинные непрерывные аудиокниги или пакетно озвучивать сцены и сценарии с идеальным контролем."
        )
        self.lc_temp = float(cfg.get("lc_temp", 0.8))
        self.lc_top_p = float(cfg.get("lc_top_p", 0.95))
        self.lc_seed = int(cfg.get("lc_seed", -1))
        self.lc_max_chars = int(cfg.get("lc_max_chars", 200))
        self.lc_gap = float(cfg.get("lc_gap", 0.3))
        self.lc_is_running = False
        self.lc_progress = 0.0
        self.lc_status = "Готов к работе"
        self.lc_out_audio = ""
        self.lc_log = ""

        # Пакетный клон
        self.bc_temp = float(cfg.get("bc_temp", 0.8))
        self.bc_top_p = float(cfg.get("bc_top_p", 0.95))
        self.bc_seed = int(cfg.get("bc_seed", -1))
        self.bc_use_plus_one = bool(cfg.get("bc_use_plus_one", False))
        self.bc_file_path = cfg.get("bc_file_path", "output/NUM/ru-en.txt")
        self.bc_lang = cfg.get("bc_lang", "EN")
        self.bc_num_from = str(cfg.get("bc_num_from", "01"))
        self.bc_num_to = str(cfg.get("bc_num_to", "10"))
        self.bc_to_end = bool(cfg.get("bc_to_end", False))
        self.bc_skip_existing = bool(cfg.get("bc_skip_existing", True))
        self.bc_fragment_text = ""
        self.bc_ref_audio = ""
        self.bc_ref_text = ""
        self.bc_is_running = False
        self.bc_progress = 0.0
        self.bc_status = "Готов к запуску"
        self.bc_out_audio = ""
        self.bc_active_badge = "—"
        self.bc_log = ""
        
        # Навигация по десяткам
        self.bc_decades = bu.get_script_decades(self.bc_file_path, self.bc_lang)
        self.bc_current_decade = self.bc_decades[0] if self.bc_decades else "01-10"
        self.bc_decade_data = bu.get_decade_data(self.bc_current_decade, self.bc_file_path, self.bc_lang)
        
        # Варианты выбранного фрагмента
        self.bc_selected_fragment = self.bc_num_from
        self.bc_variants = []
        self.bc_selected_variant = self.bc_num_from

state = AppState()


def refresh_all_voice_selectors(new_val: Optional[str] = None):
    state.voices_list = [bu.OWN_FILE] + bu.scan_voices()
    for sel in list(state.voice_selectors):
        try:
            sel.set_options(state.voices_list)
            if new_val:
                sel.set_value(new_val)
        except Exception:
            pass


# ==============================================================================
# UI Стили и Тема (Dark Studio)
# ==============================================================================
def apply_custom_styles():
    css_file = Path(__file__).parent / "dark-studio.css"
    if css_file.exists():
        ui.add_head_html(f"<style>\n{css_file.read_text(encoding='utf-8')}\n</style>")
    ui.add_head_html("""
    <style>
        /* Дополнительные точечные улучшения для NiceGUI в стилистике Dark Studio */
        .ast-card, .q-card.ast-card, .nicegui-card.ast-card {
            display: flex !important;
            flex-direction: column !important;
            align-items: stretch !important;
            width: 100% !important;
            gap: 0 !important;
            padding: 0 !important;
            box-sizing: border-box !important;
        }
        .ast-card-header {
            width: 100% !important;
            box-sizing: border-box !important;
        }
        .ast-card-body {
            width: 100% !important;
            box-sizing: border-box !important;
            display: flex !important;
            flex-direction: column !important;
            align-items: stretch !important;
        }
        .ast-card-body > * {
            width: 100% !important;
            box-sizing: border-box !important;
        }
        .ast-column {
            display: flex !important;
            flex-direction: column !important;
            align-items: stretch !important;
            gap: 14px !important;
            min-width: 0 !important;
            width: 100% !important;
        }
        nicegui-waveform_player, nicegui-waveform-player, .ast-waveform-player {
            display: block !important;
            width: 100% !important;
            box-sizing: border-box !important;
        }
        .q-field--outlined .q-field__control {
            background: #151d29 !important;
        }
        .q-expansion-item--expanded > .q-expansion-item__container > .q-item {
            border-bottom: 1px solid var(--ast-border-soft);
        }
        .q-expansion-item .q-item__label {
            font-weight: 700;
            color: var(--ast-text);
            font-size: 13.5px;
        }
        .q-slider__pin-value-marker {
            font-family: ui-monospace, monospace;
            font-size: 11px;
        }
        .ast-player {
            width: 100% !important;
        }
        .ast-player audio {
            outline: none;
            width: 100% !important;
            display: block !important;
        }
        /* Скроллбары в тёмном стиле */
        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }
        ::-webkit-scrollbar-track {
            background: #10151e;
        }
        ::-webkit-scrollbar-thumb {
            background: #2a3749;
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #3c4e66;
        }
    </style>
    """)


# ==============================================================================
# Главная страница
# ==============================================================================
@ui.page("/")
def main_page():
    ui.dark_mode().enable()
    apply_custom_styles()

    with ui.element("div").classes("ast-app w-full"):
        with ui.element("main").classes("ast-main"):
            
            # --- ВЕРХНЯЯ ПАНЕЛЬ (TOPBAR) ---
            with ui.element("div").classes("ast-topbar"):
                with ui.element("div").classes("ast-brand"):
                    with ui.element("div").classes("ast-brand-mark"):
                        ui.icon("graphic_eq").classes("text-2xl")
                    with ui.column().classes("gap-0"):
                        ui.label("Audio Studio T").classes("ast-brand-title")
                        ui.label(
                            _("Движок Fish Audio Drama 3 (35B MoE · 44.1 kHz Hi-Fi) · Чистый и быстрый интерфейс на NiceGUI")
                        ).classes("ast-brand-subtitle")
                
                with ui.element("div").classes("ast-model-area"):
                    ui.label(_("Модель:")).classes("text-xs font-semibold text-slate-400")
                    model_select = ui.select(
                        state.models_list,
                        value=state.selected_model,
                        on_change=lambda e: [setattr(state, "selected_model", e.value), save_settings()]
                    ).classes("min-w-[200px]").props("outlined dense options-dense")
                    
                    def on_lang_change(e):
                        if e.value and e.value != state.lang:
                            state.lang = str(e.value)
                            save_settings()
                            ui.run_javascript("window.location.reload(true)")

                    lang_select = ui.select(
                        ["RU", "EN"],
                        value=state.lang,
                        on_change=on_lang_change
                    ).classes("w-20").props("outlined dense options-dense")
                    
                    cuda_text = "CUDA Active" if getattr(engine, "HAS_CUDA", True) else "CPU Mode"
                    with ui.element("div").classes("ast-status"):
                        ui.label(cuda_text)

            # --- ВКЛАДКИ РЕЖИМОВ ---
            state.voice_selectors.clear()
            with ui.tabs().classes("w-full ast-mode-tabs") as tabs:
                tab_long = ui.tab(_("Длинный клон"), icon="edit_note")
                tab_batch = ui.tab(_("Пакетный клон"), icon="layers")

            with ui.tab_panels(tabs, value=tab_batch).classes("w-full bg-transparent p-0"):
                
                # ==============================================================
                # РЕЖИМ: ДЛИННЫЙ КЛОН
                # ==============================================================
                with ui.tab_panel(tab_long).classes("p-0 pt-2"):
                    build_long_clone_view()

                # ==============================================================
                # РЕЖИМ: ПАКЕТНЫЙ КЛОН
                # ==============================================================
                with ui.tab_panel(tab_batch).classes("p-0 pt-2"):
                    build_batch_clone_view()


# ==============================================================================
# КОМПОНЕНТ: ДЛИННЫЙ КЛОН
# ==============================================================================
def build_long_clone_view():
    with ui.column().classes("w-full gap-3"):
        
        # 1. Полноширинная карточка параметров генерации
        with ui.card().classes("ast-card w-full"):
            with ui.element("div").classes("ast-card-header"):
                ui.icon("tune").classes("ast-card-icon")
                ui.label(_("Параметры генерации длинного текста"))
            
            with ui.element("div").classes("ast-card-body"):
                with ui.row().classes("w-full items-center gap-6 flex-wrap"):
                    with ui.column().classes("flex-1 min-w-[170px] gap-1"):
                        ui.label(_("Temperature")).classes("text-xs font-semibold text-slate-400")
                        with ui.row().classes("w-full items-center gap-2"):
                            lc_temp_slider = ui.slider(min=0.0, max=1.5, step=0.05, value=state.lc_temp).classes("flex-1")
                            ui.label().bind_text_from(lc_temp_slider, "value", backward=lambda v: f"{v:.2f}").classes("text-xs font-mono w-10 text-right text-slate-400")
                            lc_temp_slider.on_value_change(lambda e: [setattr(state, "lc_temp", float(e.value)), save_settings()])

                    with ui.column().classes("flex-1 min-w-[170px] gap-1"):
                        ui.label(_("Top-p")).classes("text-xs font-semibold text-slate-400")
                        with ui.row().classes("w-full items-center gap-2"):
                            lc_topp_slider = ui.slider(min=0.1, max=1.0, step=0.01, value=state.lc_top_p).classes("flex-1")
                            ui.label().bind_text_from(lc_topp_slider, "value", backward=lambda v: f"{v:.2f}").classes("text-xs font-mono w-10 text-right text-slate-400")
                            lc_topp_slider.on_value_change(lambda e: [setattr(state, "lc_top_p", float(e.value)), save_settings()])

                    with ui.column().classes("w-48 gap-1"):
                        ui.label(_("Seed (-1 = случ.)")).classes("text-xs font-semibold text-slate-400")
                        lc_seed_input = ui.number(value=state.lc_seed, format="%.0f").classes("w-full").props("outlined dense")
                        lc_seed_input.on_value_change(lambda e: [setattr(state, "lc_seed", int(e.value) if e.value is not None else -1), save_settings()])

                    with ui.column().classes("w-36 gap-1"):
                        ui.label(_("Макс. символов")).classes("text-xs font-semibold text-slate-400")
                        lc_chars_input = ui.number(value=state.lc_max_chars, min=80, max=500, step=10).classes("w-full").props("outlined dense")
                        lc_chars_input.on_value_change(lambda e: [setattr(state, "lc_max_chars", int(e.value) if e.value is not None else 200), save_settings()])

                    with ui.column().classes("flex-1 min-w-[170px] gap-1"):
                        ui.label(_("Пауза между частями (сек)")).classes("text-xs font-semibold text-slate-400")
                        with ui.row().classes("w-full items-center gap-2"):
                            lc_gap_slider = ui.slider(min=0.0, max=2.0, step=0.1, value=state.lc_gap).classes("flex-1")
                            ui.label().bind_text_from(lc_gap_slider, "value", backward=lambda v: f"{v:.1f} с").classes("text-xs font-mono w-12 text-right text-slate-400")
                            lc_gap_slider.on_value_change(lambda e: [setattr(state, "lc_gap", float(e.value)), save_settings()])

        # 2. Две колонки (Ввод и Голос слева / Плеер и Лог справа)
        with ui.element("div").classes("ast-workspace w-full"):
            
            # Левая колонка
            with ui.element("div").classes("ast-column"):
                # Карточка голоса
                with ui.card().classes("ast-card w-full"):
                    with ui.element("div").classes("ast-card-header"):
                        ui.icon("mic").classes("ast-card-icon")
                        ui.label(_("Голосовой референс"))
                    
                    with ui.element("div").classes("ast-card-body w-full gap-3 flex flex-col"):
                        with ui.row().classes("w-full items-center gap-2"):
                            voice_sel = ui.select(state.voices_list, value=state.lc_preset).classes("flex-1").props("outlined dense options-dense")
                            state.voice_selectors.append(voice_sel)
                            with voice_sel.add_slot("append"):
                                ui.button(icon="refresh", on_click=lambda: refresh_all_voice_selectors()).props("flat dense round")
                        
                        def on_voice_change(e):
                            state.lc_preset = e.value
                            p = bu.voice_path(e.value)
                            if p:
                                state.lc_ref_audio = p
                                ref_player.set_source(f"/media/voices/{Path(p).name}")
                                ref_txt = bu.voice_ref_text(e.value)
                                if ref_txt:
                                    state.lc_ref_text = ref_txt
                                    ref_text_area.set_value(ref_txt)
                            save_settings()
                        voice_sel.on_value_change(on_voice_change)

                        async def on_voice_upload(e):
                            await handle_voice_upload(e, ref_player)

                        ref_upload = ui.upload(
                            label=_("Загрузить свой .wav / .mp3"),
                            auto_upload=True,
                            on_upload=on_voice_upload
                        ).classes("ast-upload-btn w-full").props("dense flat bordered dark")

                        initial_audio_src = ""
                        if state.lc_ref_audio and os.path.exists(state.lc_ref_audio):
                            p_obj = Path(state.lc_ref_audio)
                            initial_audio_src = f"/media/voices/{p_obj.name}" if "voices" in str(p_obj) else f"/media/temp/{p_obj.name}"

                        with ui.element("div").classes("ast-player w-full"):
                            ref_player = ui.audio(initial_audio_src).classes("w-full")

                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label(_("Транскрипт референса:")).classes("text-xs text-slate-400 font-medium")
                            ui.button(_("Распознать (ASR)"), icon="mic_none", on_click=lambda: run_asr_on_ref(ref_text_area)).classes("ast-btn-secondary text-xs").props("dense")
                        
                        ref_text_area = ui.textarea(placeholder=_("Что произносится в аудио-референсе...")).classes("w-full ast-textarea").props("outlined rows=3 full-width")
                        ref_text_area.bind_value(state, "lc_ref_text")

                        # Блок сохранения в библиотеку голосов
                        with ui.element("div").classes("w-full p-2.5 bg-[#151d29] rounded-lg border border-[var(--ast-border-soft)] flex flex-col gap-2 mt-1"):
                            ui.label(_("Сохранить в библиотеку")).classes("text-xs font-semibold text-slate-300")
                            with ui.row().classes("w-full items-center gap-2"):
                                save_voice_name_input = ui.input(placeholder=_("Имя нового голоса (напр. MyVoice)...")).classes("flex-1 text-xs").props("outlined dense")
                                ui.button(_("Сохранить"), icon="bookmark_add", on_click=lambda: save_custom_voice(save_voice_name_input)).classes("ast-btn-secondary text-xs").props("dense")
                            
                            voices_dir_abs = str(Path("voices").resolve())
                            with ui.row().classes("w-full items-center gap-1.5 text-[11px] text-slate-400"):
                                ui.icon("folder", size="14px").classes("text-slate-500")
                                ui.label(f"{_('Папка с образцами:')} {voices_dir_abs}").classes("font-mono text-[11px] text-slate-400 break-all select-all")

                # Текст книги / статьи
                with ui.card().classes("ast-card w-full"):
                    with ui.element("div").classes("ast-card-header justify-between"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("article").classes("ast-card-icon")
                            ui.label(_("Текст для озвучки"))
                        with ui.row().classes("items-center gap-2"):
                            async def handle_lc_text_upload(e):
                                try:
                                    raw = b""
                                    if hasattr(e, 'file') and hasattr(e.file, 'read'):
                                        raw = await e.file.read()
                                    elif hasattr(e, 'content'):
                                        raw = e.content.read()
                                    try:
                                        txt = raw.decode("utf-8")
                                    except UnicodeDecodeError:
                                        try:
                                            txt = raw.decode("cp1251")
                                        except Exception:
                                            txt = raw.decode("utf-8", errors="ignore")
                                    if txt.strip():
                                        state.lc_text = txt
                                        text_input.set_value(txt)
                                        fname = getattr(getattr(e, 'file', None), 'name', None) or getattr(e, 'name', 'text.txt')
                                        ui.notify(f"{_('Файл')} {fname} {_('загружен!')}", color="positive")
                                        lc_log_view.push(f"📄 Загружен текст из файла {fname} ({len(txt)} симв.)")
                                except Exception as ex:
                                    ui.notify(f"Ошибка загрузки файла: {ex}", color="negative")
                                    lc_log_view.push(f"❌ Ошибка загрузки файла: {ex}")

                            ui.upload(
                                label=_("Загрузить .txt"),
                                auto_upload=True,
                                on_upload=handle_lc_text_upload
                            ).classes("ast-upload-btn text-xs").props("dense flat bordered dark")
                            ui.button(_("Пример текста"), icon="lightbulb", on_click=lambda: text_input.set_value(state.lc_text)).classes("ast-btn-quiet text-xs").props("dense flat")
                    
                    with ui.element("div").classes("ast-card-body w-full"):
                        text_input = ui.textarea(value=state.lc_text).classes("w-full ast-textarea font-mono text-xs").props("outlined rows=8 full-width")
                        text_input.bind_value(state, "lc_text")

                # Кнопки запуска длинного клона
                with ui.row().classes("w-full gap-3 mt-1"):
                    lc_run_btn = ui.button(_("ЗАПУСТИТЬ ОЗВУЧКУ"), icon="play_arrow", on_click=lambda: start_long_clone()).classes("ast-btn-primary flex-1")
                    lc_stop_btn = ui.button(_("Стоп"), icon="stop", on_click=lambda: engine.request_cancel()).classes("ast-btn-danger w-28")

            # Правая колонка
            with ui.element("div").classes("ast-column"):
                with ui.card().classes("ast-card w-full"):
                    with ui.element("div").classes("ast-card-header justify-between"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("music_note").classes("ast-card-icon")
                            ui.label(_("Результат"))
                        lc_status_label = ui.label(_("Готов к работе")).classes("text-xs text-slate-400")
                    
                    with ui.element("div").classes("ast-card-body w-full gap-2 flex flex-col"):
                        lc_out_player = WaveformPlayer("").classes("w-full")
                        lc_prog_bar = ui.linear_progress(value=0.0).classes("w-full")
                        lc_prog_bar.set_visibility(False)

                with ui.card().classes("ast-card w-full"):
                    with ui.element("div").classes("ast-card-header"):
                        ui.icon("terminal").classes("ast-card-icon")
                        ui.label(_("Лог генерации"))
                    with ui.element("div").classes("ast-card-body w-full"):
                        lc_log_view = ui.log(max_lines=150).classes("w-full h-80 ast-log-panel")

    def save_custom_voice(name_input):
        raw_name = name_input.value.strip() if name_input.value else ""
        if not raw_name:
            ui.notify(_("Введите имя для сохранения голоса"), color="warning")
            return
        clean_name = re.sub(r'[\\/*?:"<>|]', "", raw_name).strip()
        if not clean_name:
            ui.notify(_("Недопустимое имя файла"), color="warning")
            return

        src_audio = state.lc_ref_audio
        if not src_audio or not os.path.exists(src_audio):
            ui.notify(_("Сначала загрузите или выберите аудио-образец"), color="warning")
            return

        ext = Path(src_audio).suffix.lower()
        if not ext or ext not in [".wav", ".mp3", ".flac", ".ogg"]:
            ext = ".wav"

        dest_dir = Path("voices")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_audio = dest_dir / f"{clean_name}{ext}"
        dest_txt = dest_dir / f"{clean_name}.txt"

        try:
            import shutil
            shutil.copy2(src_audio, dest_audio)

            text_to_save = (ref_text_area.value or state.lc_ref_text or "").strip()
            if text_to_save:
                dest_txt.write_text(text_to_save, encoding="utf-8")
            elif dest_txt.exists():
                dest_txt.unlink()

            saved_voice_filename = f"{clean_name}{ext}"
            state.lc_preset = saved_voice_filename
            state.bc_preset = saved_voice_filename
            state.lc_ref_audio = str(dest_audio)
            ref_player.set_source(f"/media/voices/{saved_voice_filename}")

            refresh_all_voice_selectors(saved_voice_filename)
            save_settings()

            name_input.set_value("")
            ui.notify(_("Голос успешно сохранен в библиотеку!"), color="positive")
            lc_log_view.push(f"💾 Голос '{clean_name}' добавлен в библиотеку: {dest_audio.name}")
        except Exception as ex:
            ui.notify(f"Ошибка сохранения: {ex}", color="negative")
            lc_log_view.push(f"❌ Ошибка сохранения голоса: {ex}")

    async def handle_voice_upload(e, player):
        fname = getattr(getattr(e, 'file', None), 'name', None) or getattr(e, 'name', 'upload.wav')
        target = Path("temp") / fname
        target.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(e, 'file') and hasattr(e.file, 'save'):
            await e.file.save(target)
        elif hasattr(e, 'file') and hasattr(e.file, 'read'):
            target.write_bytes(await e.file.read())
        elif hasattr(e, 'content'):
            target.write_bytes(e.content.read())
        state.lc_ref_audio = str(target)
        player.set_source(f"/media/temp/{fname}")
        voice_sel.set_value(bu.OWN_FILE)
        ui.notify(f"{_('Файл')} {fname} {_('загружен!')}", color="positive")
        lc_log_view.push(f"📥 Загружен референс: {fname}")

    async def run_asr_on_ref(text_area):
        if not state.lc_ref_audio or not os.path.exists(state.lc_ref_audio):
            ui.notify(_("Сначала выберите или загрузите аудио-референс"), color="warning")
            return
        ui.notify(_("Распознавание речи через Qwen3-ASR..."), color="info")
        fname = Path(state.lc_ref_audio).name
        lc_log_view.push(f"🎙 Распознавание ASR для: {fname}...")
        res = await run.io_bound(engine.transcribe_audio, state.lc_ref_audio)
        if res:
            state.lc_ref_text = res
            text_area.set_value(res)
            ui.notify(_("Транскрипт готов!"), color="positive")
            lc_log_view.push(f"✅ Распознан текст: {res}")
        else:
            ui.notify(_("Не удалось распознать речь"), color="negative")
            lc_log_view.push("❌ Ошибка ASR распознавания")

    async def start_long_clone():
        if not state.lc_text.strip():
            ui.notify("Введите текст для озвучки", color="warning")
            return
        
        state.lc_is_running = True
        lc_prog_bar.set_visibility(True)
        lc_prog_bar.set_value(0.0)
        lc_log_view.push("🚀 Старт длинного клона...")
        
        raw_paras = [p.strip() for p in re.split(r'\n+', state.lc_text) if p.strip()]
        chunks = []
        for p in raw_paras:
            if len(p) <= state.lc_max_chars:
                chunks.append(p)
            else:
                sub_parts = re.split(r'([.!?…]+(?:\s+|$))', p)
                curr = ""
                for part in sub_parts:
                    if len(curr) + len(part) <= state.lc_max_chars:
                        curr += part
                    else:
                        if curr.strip():
                            chunks.append(curr.strip())
                        curr = part
                if curr.strip():
                    chunks.append(curr.strip())

        lc_log_view.push(f"📊 Всего частей для озвучки: {len(chunks)}")
        
        def on_step(part_idx, total_parts, pct, desc):
            lc_prog_bar.set_value(pct)
            lc_status_label.set_text(desc)
            lc_log_view.push(desc)

        try:
            t0 = time.time()
            sr, wav_data = await run.io_bound(
                engine.synth_longform,
                chunks,
                ref_audio=state.lc_ref_audio or None,
                ref_text=state.lc_ref_text or None,
                gap=state.lc_gap,
                temperature=state.lc_temp,
                top_p=state.lc_top_p,
                seed=state.lc_seed,
                model_name=state.selected_model,
                on_step_progress=on_step
            )

            if wav_data is not None and len(wav_data) > 0:
                out_name = f"longform_{int(time.time())}.wav"
                out_path = Path("output") / out_name
                sf.write(str(out_path), wav_data, sr)
                
                dur = len(wav_data) / sr
                el = time.time() - t0
                lc_log_view.push(f"✅ Готово! Файл: {out_name} (длительность: {dur:.1f} сек за {el:.1f} сек)")
                lc_status_label.set_text(f"Готово: {out_name} ({dur:.1f} с)")
                lc_out_player.set_source(f"/media/output/{out_name}")
                ui.notify(f"Готово! Сохранено в {out_name}", color="positive")
            else:
                lc_log_view.push("❌ Ошибка: пустой аудиопоток.")
                ui.notify("Ошибка синтеза", color="negative")
        except Exception as e:
            lc_log_view.push(f"❌ Ошибка: {e}")
            ui.notify(f"Ошибка: {e}", color="negative")
        finally:
            state.lc_is_running = False
            lc_prog_bar.set_visibility(False)


# ==============================================================================
# КОМПОНЕНТ: ПАКЕТНЫЙ КЛОН
# ==============================================================================
def build_batch_clone_view():
    with ui.column().classes("w-full gap-3"):
        
        # Две рабочие колонки (Dark Studio layout)
        with ui.element("div").classes("ast-workspace w-full"):
            
            # ------------------ ЛЕВАЯ КОЛОНКА ------------------
            with ui.element("div").classes("ast-column"):
                
                # 1. Сценарий и диапазон
                with ui.card().classes("ast-card w-full"):
                    with ui.element("div").classes("ast-card-header"):
                        ui.icon("description").classes("ast-card-icon")
                        ui.label(_("Сценарий и диапазон"))
                    
                    with ui.element("div").classes("ast-card-body gap-3 flex flex-col"):
                        def on_script_selected(e):
                            val = str(e.value or "").strip()
                            if val:
                                state.bc_file_path = val
                                save_settings()
                                refresh_script()
                                bc_log_view.push(f"📖 Загружен сценарий: {state.bc_file_path}")

                        async def handle_script_upload(e):
                            fname = getattr(getattr(e, 'file', None), 'name', None) or getattr(e, 'name', 'script.txt')
                            out_file = Path("output/NUM") / fname
                            out_file.parent.mkdir(parents=True, exist_ok=True)
                            if hasattr(e, 'file') and hasattr(e.file, 'save'):
                                await e.file.save(out_file)
                            elif hasattr(e, 'file') and hasattr(e.file, 'read'):
                                out_file.write_bytes(await e.file.read())
                            elif hasattr(e, 'content'):
                                out_file.write_bytes(e.content.read())
                            new_path = f"output/NUM/{fname}"
                            state.bc_file_path = new_path
                            save_settings()
                            script_select.set_options(get_available_scripts())
                            script_select.set_value(new_path)
                            refresh_script()
                            ui.notify(f"Файл {fname} загружен!", color="positive")
                            bc_log_view.push(f"📥 Загружен новый сценарий: {fname}")

                        with ui.row().classes("w-full gap-2 items-center"):
                            script_select = ui.select(
                                get_available_scripts(),
                                value=state.bc_file_path,
                                label=_("Файл сценария (.txt)"),
                                on_change=on_script_selected,
                                with_input=True,
                                new_value_mode="add-unique",
                            ).classes("flex-1").props("outlined dense options-dense")
                            with script_select.add_slot("append"):
                                ui.button(icon="refresh", on_click=lambda: [script_select.set_options(get_available_scripts()), refresh_script()]).props("flat dense round")
                            
                            ui.upload(
                                label=_("Загрузить .txt"),
                                auto_upload=True,
                                on_upload=handle_script_upload
                            ).classes("ast-upload-btn").props("dense flat bordered dark")
                        
                        with ui.row().classes("w-full gap-3 items-center"):
                            lang_sel = ui.select(["EN", "RU", "ALL"], value=state.bc_lang).classes("w-24").props("outlined dense options-dense")
                            lang_sel.on_value_change(lambda e: [setattr(state, "bc_lang", e.value), save_settings(), refresh_script()])
                            
                            from_inp = ui.input(value=state.bc_num_from, label=_("С номера")).classes("w-20").props("outlined dense")
                            from_inp.on_value_change(lambda e: [setattr(state, "bc_num_from", str(e.value or "")), save_settings()])
                            
                            to_inp = ui.input(value=state.bc_num_to, label=_("По номер")).classes("w-20").props("outlined dense")
                            to_inp.on_value_change(lambda e: [setattr(state, "bc_num_to", str(e.value or "")), save_settings()])
                            
                            to_end_chk = ui.checkbox(_("До конца"), value=state.bc_to_end).classes("text-xs font-medium")
                            to_end_chk.on_value_change(lambda e: [setattr(state, "bc_to_end", bool(e.value)), save_settings()])

                        skip_chk = ui.checkbox(_("Пропускать уже существующие файлы в NUM"), value=state.bc_skip_existing).classes("text-xs text-slate-300 font-medium")
                        skip_chk.on_value_change(lambda e: [setattr(state, "bc_skip_existing", bool(e.value)), save_settings()])

                        stats_label = ui.label(_("💡 Нажмите «Перечитать» для проверки диапазона")).classes("ast-inline-meta text-xs")

                # 2. Параметры генерации
                with ui.card().classes("ast-card w-full"):
                    with ui.element("div").classes("ast-card-header"):
                        ui.icon("tune").classes("ast-card-icon")
                        ui.label(_("Параметры генерации"))
                    
                    with ui.element("div").classes("ast-card-body"):
                        with ui.row().classes("w-full items-center gap-4 flex-wrap"):
                            with ui.column().classes("flex-1 min-w-[140px] gap-1"):
                                ui.label(_("Temperature")).classes("text-xs font-semibold text-slate-400")
                                with ui.row().classes("w-full items-center gap-2"):
                                    bc_temp_sl = ui.slider(min=0.0, max=1.5, step=0.05, value=state.bc_temp).classes("flex-1")
                                    ui.label().bind_text_from(bc_temp_sl, "value", backward=lambda v: f"{v:.2f}").classes("text-xs font-mono w-10 text-right text-slate-400")
                                    bc_temp_sl.on_value_change(lambda e: [setattr(state, "bc_temp", float(e.value)), save_settings()])

                            with ui.column().classes("flex-1 min-w-[140px] gap-1"):
                                ui.label(_("Top-p")).classes("text-xs font-semibold text-slate-400")
                                with ui.row().classes("w-full items-center gap-2"):
                                    bc_topp_sl = ui.slider(min=0.1, max=1.0, step=0.01, value=state.bc_top_p).classes("flex-1")
                                    ui.label().bind_text_from(bc_topp_sl, "value", backward=lambda v: f"{v:.2f}").classes("text-xs font-mono w-10 text-right text-slate-400")
                                    bc_topp_sl.on_value_change(lambda e: [setattr(state, "bc_top_p", float(e.value)), save_settings()])

                            with ui.column().classes("w-48 gap-1"):
                                ui.label(_("Seed (-1 = rand)")).classes("text-xs font-semibold text-slate-400")
                                with ui.row().classes("w-full items-center gap-2"):
                                    bc_seed_inp = ui.number(value=state.bc_seed, format="%.0f").classes("flex-1").props("outlined dense")
                                    bc_seed_inp.on_value_change(lambda e: [setattr(state, "bc_seed", int(e.value) if e.value is not None else -1), save_settings()])
                                    bc_plus_one_chk = ui.checkbox("+1", value=state.bc_use_plus_one).classes("text-xs")
                                    bc_plus_one_chk.on_value_change(lambda e: [setattr(state, "bc_use_plus_one", bool(e.value)), save_settings()])

                # 3. Текст выбранного фрагмента
                with ui.card().classes("ast-card w-full"):
                    with ui.element("div").classes("ast-card-header"):
                        ui.icon("edit").classes("ast-card-icon")
                        ui.label(_("Текст выбранного фрагмента (для озвучки / правки)"))
                    
                    with ui.element("div").classes("ast-card-body w-full"):
                        frag_text = ui.textarea(placeholder=_("Кликните на кнопку слота или укажите номер...")).classes("w-full ast-textarea font-mono text-xs").props("outlined rows=4 full-width")
                        frag_text.bind_value(state, "bc_fragment_text")

                # 4. Пресет голоса для пакета
                with ui.card().classes("ast-card w-full"):
                    with ui.element("div").classes("ast-card-header"):
                        ui.icon("mic").classes("ast-card-icon")
                        ui.label(_("Пресет голоса для пакета"))
                    
                    with ui.element("div").classes("ast-card-body"):
                        def on_bc_voice_change(e):
                            state.bc_preset = e.value
                            save_settings()
                            bc_log_view.push(f"🎙 Выбран голос: {state.bc_preset}")
                            ui.notify(f"Выбран голос: {state.bc_preset}", color="info")

                        async def handle_bc_voice_upload(e):
                            fname = getattr(getattr(e, 'file', None), 'name', None) or getattr(e, 'name', 'voice.wav')
                            target = Path("voices") / fname
                            target.parent.mkdir(parents=True, exist_ok=True)
                            if hasattr(e, 'file') and hasattr(e.file, 'save'):
                                await e.file.save(target)
                            elif hasattr(e, 'file') and hasattr(e.file, 'read'):
                                target.write_bytes(await e.file.read())
                            elif hasattr(e, 'content'):
                                target.write_bytes(e.content.read())
                            refresh_all_voice_selectors(fname)
                            state.bc_preset = fname
                            state.lc_preset = fname
                            save_settings()
                            ui.notify(f"{_('Голос')} {fname} {_('успешно сохранен в библиотеку!')}", color="positive")
                            bc_log_view.push(f"📥 Добавлен новый голос: {fname}")

                        with ui.row().classes("w-full gap-2 items-center"):
                            bc_voice_sel = ui.select(
                                state.voices_list, 
                                value=state.bc_preset,
                                on_change=on_bc_voice_change
                            ).classes("flex-1").props("outlined dense options-dense")
                            state.voice_selectors.append(bc_voice_sel)
                            with bc_voice_sel.add_slot("append"):
                                ui.button(icon="refresh", on_click=lambda: refresh_all_voice_selectors()).props("flat dense round")

                            ui.upload(
                                label=_("Добавить голос"),
                                auto_upload=True,
                                on_upload=handle_bc_voice_upload
                            ).classes("ast-upload-btn").props("dense flat bordered dark")

                        voices_dir_abs = str(Path("voices").resolve())
                        with ui.row().classes("w-full items-center gap-1.5 text-[11px] text-slate-400 mt-2"):
                            ui.icon("folder", size="14px").classes("text-slate-500")
                            ui.label(f"{_('Папка с образцами:')} {voices_dir_abs}").classes("font-mono text-[11px] text-slate-400 break-all select-all")

                # 5. Склеивание фрагментов в папке NUM (Expander)
                with ui.expansion(_("Склеивание фрагментов в папке NUM"), icon="link").classes("w-full ast-card"):
                    with ui.column().classes("w-full p-3 gap-2"):
                        with ui.row().classes("w-full gap-3 items-center"):
                            m_from = ui.input(value="01", label=_("С номера")).classes("w-20").props("outlined dense")
                            m_to = ui.input(value="10", label=_("По номер")).classes("w-20").props("outlined dense")
                            m_gap = ui.number(value=0.3, step=0.1, label=_("Пауза (с)")).classes("w-24").props("outlined dense")
                            ui.button(_("Найти"), icon="search", on_click=lambda: auto_fill_merge_range(m_from, m_to)).classes("ast-btn-secondary text-xs").props("dense")
                        ui.button(_("Склеить фрагменты в один WAV"), icon="merge_type", on_click=lambda: run_merge(m_from.value, m_to.value, m_gap.value)).classes("w-full ast-btn-secondary text-xs mt-1")

                # 6. Перевод нумерации (Expander)
                with ui.expansion(_("Перевод нумерации (01 ⇄ 001)"), icon="pin").classes("w-full ast-card"):
                    with ui.column().classes("w-full p-3 gap-2"):
                        ui.label(_("Быстрый перевод двухзначных номеров (01..99) в трехзначные (001..099) и обратно.")).classes("text-xs text-slate-400")
                        with ui.row().classes("w-full gap-4"):
                            conv_f = ui.checkbox(_("Файлы в output/NUM"), value=True).classes("text-xs font-medium")
                            conv_s = ui.checkbox(_("Метки в сценарии"), value=True).classes("text-xs font-medium")
                        with ui.row().classes("w-full gap-3 mt-1"):
                            ui.button(_("В 3 знака (01 ➔ 001)"), icon="trending_flat", on_click=lambda: run_conversion(3, conv_f.value, conv_s.value)).classes("flex-1 ast-btn-secondary text-xs")
                            ui.button(_("В 2 знака (001 ➔ 01)"), icon="trending_flat", on_click=lambda: run_conversion(2, conv_f.value, conv_s.value)).classes("flex-1 ast-btn-secondary text-xs")

            # ------------------ ПРАВАЯ КОЛОНКА ------------------
            with ui.element("div").classes("ast-column"):
                
                # 1. Результат
                with ui.card().classes("ast-card w-full"):
                    with ui.element("div").classes("ast-card-header justify-between"):
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("music_note").classes("ast-card-icon")
                            ui.label(_("Результат"))
                            badge_label = ui.label("—").classes("ast-badge-pill font-mono")
                        
                        seed_badge_btn = ui.button("🎲 seed: —", on_click=lambda: copy_active_seed_to_gui()).classes("ast-seed-badge").props("flat dense")
                    
                    with ui.element("div").classes("ast-card-body w-full"):
                        bc_player = WaveformPlayer("").classes("w-full")

                # 2. Слоты, варианты и навигация по десяткам
                with ui.card().classes("ast-card w-full"):
                    with ui.element("div").classes("ast-card-header"):
                        ui.icon("grid_view").classes("ast-card-icon")
                        ui.label(_("Слоты и варианты озвучки"))
                    
                    with ui.element("div").classes("ast-card-body gap-3 flex flex-col"):
                        # Блок вариантов (компактная строка - прямо под плеером!)
                        ui.label(_("ВАРИАНТЫ:")).classes("text-white")
                        variants_container = ui.row().classes("w-full items-center justify-between gap-2 p-2 bg-[#151d29] rounded-lg border border-[var(--ast-border-soft)]")

                        # 2. 10 кнопок слотов (2 ряда по 5)
                        slots_grid = ui.element("div").classes("ast-slot-grid w-full")

                        # 3. Навигация по десяткам (ниже кнопок слотов)
                        with ui.element("div").classes("w-full pt-1.5 border-t border-[var(--ast-border-soft)] flex flex-col gap-1.5"):
                            ui.label(_("Навигация по десяткам:")).classes("text-[11px] font-semibold text-slate-400 tracking-wide uppercase")
                            decades_container = ui.row().classes("w-full flex-wrap gap-2")

                # 3. Список реплик десятка
                with ui.card().classes("ast-card w-full"):
                    with ui.element("div").classes("ast-card-header"):
                        ui.icon("format_list_bulleted").classes("ast-card-icon")
                        ui.label(_("Реплики выбранного десятка (клик для проверки / загрузки)"))
                    
                    with ui.element("div").classes("ast-card-body w-full"):
                        phrases_container = ui.column().classes("w-full ast-text-panel gap-1")

                # 4. Лог пакетной обработки (Expander)
                with ui.expansion(_("Лог пакетной обработки"), icon="terminal").classes("w-full ast-card"):
                    bc_log_view = ui.log(max_lines=150).classes("w-full ast-log-panel")

        # --- ФИКСИРОВАННАЯ НИЖНЯЯ ПАНЕЛЬ ДЕЙСТВИЙ (ACTION BAR) ---
        with ui.element("div").classes("ast-actionbar"):
            with ui.element("div").classes("ast-action-group"):
                bc_batch_btn = ui.button(_("ЗАПУСТИТЬ ПАКЕТНУЮ ОЗВУЧКУ"), icon="play_arrow", on_click=lambda: run_batch_clone()).classes("ast-btn-primary")
                with ui.row().classes("gap-1"):
                    ui.button("+1", on_click=lambda: generate_variants_core(1)).classes("ast-btn-secondary px-2")
                    ui.button("+3", on_click=lambda: generate_variants_core(3)).classes("ast-btn-secondary px-2")
                    ui.button("+5", on_click=lambda: generate_variants_core(5)).classes("ast-btn-secondary px-2")
                    ui.button("+7", on_click=lambda: generate_variants_core(7)).classes("ast-btn-secondary px-2")
                    ui.button("+10", on_click=lambda: generate_variants_core(10)).classes("ast-btn-secondary px-2")
                bc_stop_btn = ui.button(_("Стоп"), icon="stop", on_click=lambda: engine.request_cancel()).classes("ast-btn-danger")
            
            with ui.element("div").classes("ast-gen-progress-panel"):
                remaining_badge = ui.badge("Осталось: 00", color="purple").classes(
                    "text-xs font-mono font-bold px-2.5 py-1 rounded shadow-sm border border-purple-400/40 hidden"
                )
                with ui.element("div").classes("flex flex-col gap-0.5 min-w-[200px] max-w-[260px] hidden") as progress_container:
                    with ui.row().classes("w-full justify-between items-center text-[10px] font-mono text-slate-300"):
                        progress_step_label = ui.label("0/0 фреймов").classes("text-slate-300 font-semibold")
                        progress_pct_label = ui.label("0%").classes("text-indigo-400 font-bold")
                    gen_progress_bar = ui.linear_progress(value=0.0, show_value=False).classes("w-full h-2 rounded-full overflow-hidden").props("color=indigo-5 track-color=dark")

            with ui.element("div").classes("ast-action-meta"):
                state_indicator = ui.label("Готов к запуску").classes("ast-state is-ready")
                ui.label("|").classes("opacity-30")
                var_counter = ui.label("Вариантов: 0").classes("text-xs font-medium")

    # --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ПАКЕТНОГО РЕЖИМА ---
    def render_decades():
        decades_container.clear()
        with decades_container:
            for dec in state.bc_decades:
                is_active = (dec == state.bc_current_decade)
                active_cls = "is-active" if is_active else ""
                ui.button(dec, on_click=lambda d=dec: select_decade(d)).classes(f"ast-btn-range {active_cls}").props("dense flat")

    def render_variants():
        variants_container.clear()
        base_f, vars_list, max_idx, pad = bu.get_fragment_variants_info(state.bc_selected_fragment)
        choices = bu.make_variant_choices(base_f, vars_list, pad)
        state.bc_variants = choices
        var_counter.set_text(f"Вариантов: {len(vars_list)}")
        
        with variants_container:
            with ui.row().classes("items-center gap-1 flex-1 flex-wrap"):
                ui.label(f"Варианты {pad}:").classes("text-[11px] font-bold text-slate-300")
                for ch in choices:
                    is_sel = (ch == state.bc_selected_variant)
                    ch_cls = "is-active" if is_sel else ""
                    ui.button(ch, on_click=lambda c=ch: select_variant(c)).classes(f"ast-variant-btn {ch_cls}").props("dense flat")

            with ui.row().classes("items-center gap-1"):
                ui.button(icon="check", on_click=lambda: approve_current_variant()).classes("bg-emerald-700 hover:bg-emerald-600 text-[11px] px-2 py-0.5 rounded").props("dense flat text-white")
                ui.button(icon="delete", on_click=lambda: delete_current_variant()).classes("bg-rose-800 hover:bg-rose-700 text-[11px] px-2 py-0.5 rounded").props("dense flat text-white")

    def render_slots():
        slots_grid.clear()
        phrases_container.clear()
        data = state.bc_decade_data
        
        with slots_grid:
            for s in data["slots"]:
                if s["visible"]:
                    num_str = s["num_str"]
                    is_ready = bool(s.get("ready", False))
                    is_active = (num_str == state.bc_selected_fragment)
                    ready_cls = "is-ready" if is_ready else ""
                    active_cls = "is-active" if is_active else ""
                    icon_name = "check" if is_ready else "radio_button_unchecked"
                    btn_text = f"{num_str}"
                    ui.button(
                        btn_text, 
                        icon=icon_name, 
                        on_click=lambda num=num_str: inspect_fragment(num)
                    ).classes(f"ast-slot {ready_cls} {active_cls}").props("dense flat")

        with phrases_container:
            for ph in data["phrases"]:
                ui.label(ph).classes("p-1 hover:bg-[#1b2533] rounded cursor-pointer transition text-xs font-mono").on("click", lambda e, p=ph: inspect_fragment(p.split()[0]))

    def select_decade(dec: str):
        state.bc_current_decade = dec
        state.bc_decade_data = bu.get_decade_data(dec, state.bc_file_path, state.bc_lang)
        render_decades()
        render_slots()

    def update_active_seed_display(audio_stem: str):
        s = bu.get_audio_seed(audio_stem)
        state.bc_current_audio_seed = s
        if s is not None:
            seed_badge_btn.set_text(f"🎲 Seed: {s}")
            seed_badge_btn.classes(remove="hidden")
            seed_badge_btn.tooltip("Кликните, чтобы скопировать этот seed в параметры генерации")
        else:
            seed_badge_btn.set_text("🎲 Seed: —")

    def copy_active_seed_to_gui():
        s = getattr(state, "bc_current_audio_seed", None)
        if s is not None:
            state.bc_seed = int(s)
            bc_seed_inp.set_value(int(s))
            save_settings()
            ui.notify(f"🌱 Сид {s} записан в параметры генерации!", color="positive")
            bc_log_view.push(f"📋 Сид {s} скопирован в поле Seed")
        else:
            ui.notify("Сид для текущего аудио не найден в метаданных", color="warning")

    def select_variant(choice: str):
        state.bc_selected_variant = choice
        clean = choice.split()[0]
        num_dir = Path("output/NUM")
        for ext in ["wav", "mp3", "flac", "ogg"]:
            cand = num_dir / f"{clean}.{ext}"
            if cand.exists():
                bc_player.set_source(f"/media/output/NUM/{cand.name}")
                badge_label.set_text(f"🎵 {cand.name}")
                update_active_seed_display(cand.name)
                bc_log_view.push(f"🎧 Выбран вариант: {cand.name}")
                bc_player.play()
                break
        render_variants()

    def inspect_fragment(num_str: str):
        clean = str(num_str).split()[0]
        state.bc_selected_fragment = clean
        state.bc_num_from = clean
        state.bc_num_to = clean
        from_inp.set_value(clean)
        to_inp.set_value(clean)
        render_slots()
        
        base_f, vars_list, max_idx, pad = bu.get_fragment_variants_info(clean)
        state.bc_selected_variant = pad
        
        # Загрузка текста
        items = bu.parse_batch_script(state.bc_file_path, lang=state.bc_lang)
        found_txt = ""
        try:
            val_int = int(clean)
            for it in items:
                if it["num"] == val_int:
                    found_txt = it["text"]
                    break
        except Exception:
            pass
        
        if not found_txt:
            meta = Path(f"output/NUM/{pad}.txt")
            if meta.exists():
                for line in meta.read_text(encoding="utf-8", errors="replace").splitlines():
                    if line.startswith("text:"):
                        found_txt = line[5:].strip()
                        break

        frag_text.set_value(found_txt)
        
        # Загрузка аудио
        if base_f and base_f.exists():
            bc_player.set_source(f"/media/output/NUM/{base_f.name}")
            badge_label.set_text(f"🎵 {base_f.name}")
            update_active_seed_display(base_f.name)
            bc_player.play()
        elif vars_list:
            v_audio = vars_list[0]["audio"]
            bc_player.set_source(f"/media/output/NUM/{v_audio.name}")
            badge_label.set_text(f"🎵 {v_audio.name}")
            update_active_seed_display(v_audio.name)
            bc_player.play()
        else:
            badge_label.set_text(f"🎵 {pad} (нет)")
            update_active_seed_display("")

        bc_log_view.push(f"🔍 Выбран фрагмент {clean}: '{found_txt[:60]}...'")
        render_variants()

    def refresh_script():
        items = bu.parse_batch_script(state.bc_file_path, lang=state.bc_lang)
        if items:
            stats_label.set_text(f"📖 Загружено {len(items)} фрагментов (от {items[0]['num_str']} до {items[-1]['num_str']}).")
        else:
            stats_label.set_text("❌ Сценарий пуст или файл не найден.")
        
        state.bc_decades = bu.get_script_decades(state.bc_file_path, state.bc_lang)
        state.bc_current_decade = state.bc_decades[0] if state.bc_decades else "01-10"
        state.bc_decade_data = bu.get_decade_data(state.bc_current_decade, state.bc_file_path, state.bc_lang)
        render_decades()
        render_slots()
        render_variants()

    def approve_current_variant():
        sel = state.bc_selected_variant
        frag = state.bc_selected_fragment
        base_f, vars_list, max_idx, pad = bu.get_fragment_variants_info(frag)
        if not sel:
            ui.notify("Выберите вариант для утверждения", color="warning")
            return
        
        num_dir = Path("output/NUM")
        target_audio = num_dir / f"{pad}.wav"
        target_meta = num_dir / f"{pad}.txt"
        
        if sel == pad:
            cnt = 0
            for v in vars_list:
                if v["audio"].exists():
                    v["audio"].unlink()
                    cnt += 1
                if v["meta"] and v["meta"].exists():
                    v["meta"].unlink()
            bc_log_view.push(f"✅ Исходный {pad} утвержден. Удалено вариантов: {cnt}")
            ui.notify(f"Исходный {pad} утвержден!", color="positive")
        else:
            matched = [v for v in vars_list if v["stem"] == sel]
            if not matched:
                ui.notify("Вариант не найден", color="negative")
                return
            v = matched[0]
            shutil.copy2(str(v["audio"]), str(target_audio))
            if v["meta"] and v["meta"].exists():
                shutil.copy2(str(v["meta"]), str(target_meta))
            
            cnt = 0
            for var_item in vars_list:
                if var_item["audio"].exists():
                    var_item["audio"].unlink()
                    cnt += 1
                if var_item["meta"] and var_item["meta"].exists():
                    var_item["meta"].unlink()
            bc_log_view.push(f"🎉 Вариант {sel} утвержден как {target_audio.name}! Очищено вариантов: {cnt}")
            ui.notify(f"Вариант {sel} утвержден!", color="positive")

        select_decade(state.bc_current_decade)
        inspect_fragment(pad)

    def delete_current_variant():
        sel = state.bc_selected_variant
        frag = state.bc_selected_fragment
        base_f, vars_list, max_idx, pad = bu.get_fragment_variants_info(frag)
        if not sel or sel == pad:
            ui.notify("Исходный файл нельзя удалить через кнопку варианта", color="warning")
            return
        
        matched = [v for v in vars_list if v["stem"] == sel]
        if matched:
            v = matched[0]
            if v["audio"].exists():
                try: v["audio"].unlink()
                except Exception: pass
            if v["meta"] and v["meta"].exists():
                try: v["meta"].unlink()
                except Exception: pass
        
        cand_txt = Path("output/NUM") / f"{sel}.txt"
        if cand_txt.exists():
            try: cand_txt.unlink()
            except Exception: pass

        bc_log_view.push(f"🗑️ Вариант {sel} и служебный лог удалены.")
        ui.notify(f"Вариант {sel} удален", color="info")
        inspect_fragment(frag)

    async def generate_variants_core(count: int = 1):
        frag = state.bc_selected_fragment
        m = re.search(r'(\d+)', str(frag or ""))
        if not m:
            ui.notify("Не указан номер фрагмента", color="warning")
            return
        
        num_val = int(m.group(1))
        txt = state.bc_fragment_text.strip()
        if not txt:
            ui.notify("Текст фрагмента пуст", color="warning")
            return
        
        ref = bu.voice_path(state.bc_preset) if state.bc_preset != bu.OWN_FILE else None
        ref_txt = bu.voice_ref_text(state.bc_preset) if ref else None
        num_dir = Path("output/NUM")
        
        remaining_badge.classes(remove="hidden")
        progress_container.classes(remove="hidden")
        gen_progress_bar.set_value(0.0)
        progress_pct_label.set_text("0%")
        progress_step_label.set_text("Старт...")
        
        state_indicator.classes(remove="is-ready", add="is-running")
        bc_log_view.push(f"➕ Генерация {count} вариант(ов) для фрагмента {frag}...")
        if ref:
            v_name = Path(ref).name
            ref_info = f" (транскрипция: «{ref_txt[:40]}...»)" if ref_txt else " (ASR авто)"
            bc_log_view.push(f"🎙 Голос: {v_name}{ref_info}")
        else:
            bc_log_view.push("⚠️ Пресет голоса не выбран (используется базовый тембр модели)!")
        
        try:
            for step in range(count):
                if engine.cancelled():
                    bc_log_view.push("🛑 Генерация вариантов отменена.")
                    break
                
                remaining = count - step
                remaining_badge.set_text(f"Осталось: {remaining:02d}")
                state_indicator.set_text(f"Генерация {step + 1}/{count} (осталось {remaining:02d})")

                base_f, vars_list, max_idx, pad = bu.get_fragment_variants_info(num_val)
                next_idx = max_idx + 1
                v_stem = f"{pad}_{next_idx:02d}"
                target_p = num_dir / f"{v_stem}.wav"
                
                act_seed = int(state.bc_seed) if state.bc_seed >= 0 else random.randint(10000, 99999999)
                
                # Применяем +1, если включено
                if state.bc_use_plus_one and state.bc_seed >= 0:
                    current_seed = act_seed + step
                else:
                    current_seed = act_seed

                bc_log_view.push(f"[{step + 1}/{count}] Синтез {v_stem} (seed={current_seed})...")
                
                last_ui_t = 0
                def handle_variant_progress(frame_step, max_f, c_idx, total_c, stage):
                    nonlocal last_ui_t
                    now = time.time()
                    if now - last_ui_t < 0.08 and frame_step < max_f:
                        return
                    last_ui_t = now
                    pct = frame_step / max(1, max_f)
                    overall_pct = (step + pct) / count
                    gen_progress_bar.set_value(overall_pct)
                    progress_pct_label.set_text(f"{int(overall_pct * 100)}%")
                    if stage == "decoding":
                        progress_step_label.set_text(f"[{v_stem}] Декодирование WAV...")
                    else:
                        progress_step_label.set_text(f"[{v_stem}] {frame_step}/{max_f} фреймов")

                try:
                    sr, chunk_wav = await run.io_bound(
                        engine.synth,
                        txt,
                        ref_audio=ref,
                        ref_text=ref_txt,
                        temperature=state.bc_temp,
                        top_p=state.bc_top_p,
                        seed=current_seed,
                        model_name=state.selected_model,
                        on_progress=handle_variant_progress
                    )
                    if chunk_wav is not None and len(chunk_wav) > 0:
                        sf.write(str(target_p), chunk_wav, sr)
                        meta_p = num_dir / f"{v_stem}.txt"
                        meta_p.write_text(f"file: {target_p.name}\nvariant_for: {pad}\nseed: {current_seed}\ntext: {txt}\n", encoding="utf-8")
                        bc_log_view.push(f"✓ Сохранен вариант {v_stem}.wav (seed={current_seed})")
                        
                        bc_player.set_source(f"/media/output/NUM/{target_p.name}")
                        badge_label.set_text(f"🎵 {target_p.name}")
                        state.bc_selected_variant = v_stem
                        update_active_seed_display(v_stem)
                        bc_player.play()
                        render_variants()
                except Exception as e:
                    bc_log_view.push(f"❌ Ошибка генерации {v_stem}: {e}")

            ui.notify("Генерация вариантов завершена!", color="positive")
            select_decade(state.bc_current_decade)
        finally:
            remaining_badge.classes(add="hidden")
            progress_container.classes(add="hidden")
            state_indicator.classes(remove="is-running", add="is-ready")
            state_indicator.set_text("Готов к запуску")

    async def run_batch_clone():
        items = bu.parse_batch_script(state.bc_file_path, lang=state.bc_lang)
        if not items:
            ui.notify("Файл сценария пуст", color="warning")
            return
        
        try:
            n_start = int(state.bc_num_from)
            n_end = items[-1]["num"] if state.bc_to_end else int(state.bc_num_to)
        except Exception:
            ui.notify("Неверно указан диапазон", color="warning")
            return

        to_process = [it for it in items if n_start <= it["num"] <= n_end]
        if not to_process:
            ui.notify("Нет фрагментов в указанном диапазоне", color="warning")
            return

        ref = bu.voice_path(state.bc_preset) if state.bc_preset != bu.OWN_FILE else None
        ref_txt = bu.voice_ref_text(state.bc_preset) if ref else None
        num_dir = Path("output/NUM")
        
        total_items = len(to_process)
        remaining_badge.classes(remove="hidden")
        progress_container.classes(remove="hidden")
        gen_progress_bar.set_value(0.0)
        progress_pct_label.set_text("0%")
        progress_step_label.set_text(f"0/{total_items} фрагментов")

        state_indicator.classes(remove="is-ready", add="is-running")
        bc_log_view.push(f"🚀 Старт пакетной озвучки: с {n_start} по {n_end} ({total_items} фрагментов)...")
        if ref:
            v_name = Path(ref).name
            ref_info = f" (транскрипция: «{ref_txt[:40]}...»)" if ref_txt else " (ASR авто)"
            bc_log_view.push(f"🎙 Голос: {v_name}{ref_info}")
        else:
            bc_log_view.push("⚠️ Пресет голоса не выбран (используется базовый тембр модели)!")
        
        try:
            for idx, item in enumerate(to_process):
                if engine.cancelled():
                    bc_log_view.push("🛑 Пакетная озвучка прервана пользователем.")
                    break
                
                remaining = total_items - idx
                remaining_badge.set_text(f"Осталось: {remaining:02d}")
                p_num = item["num_str"]
                target_p = num_dir / f"{p_num}.wav"
                
                if state.bc_skip_existing and target_p.exists():
                    bc_log_view.push(f"⏩ Пропуск {p_num}.wav (уже существует)")
                    continue

                txt = item["text"]
                act_seed = int(state.bc_seed) if state.bc_seed >= 0 else random.randint(10000, 99999999)
                state_indicator.set_text(f"Озвучка {idx + 1}/{total_items} (осталось {remaining:02d})")
                bc_log_view.push(f"[{idx + 1}/{total_items}] Озвучка {p_num}: '{txt[:50]}...'")

                last_ui_t = 0
                def handle_batch_progress(frame_step, max_f, c_idx, total_c, stage):
                    nonlocal last_ui_t
                    now = time.time()
                    if now - last_ui_t < 0.08 and frame_step < max_f:
                        return
                    last_ui_t = now
                    pct = frame_step / max(1, max_f)
                    overall_pct = (idx + pct) / total_items
                    gen_progress_bar.set_value(overall_pct)
                    progress_pct_label.set_text(f"{int(overall_pct * 100)}%")
                    if stage == "decoding":
                        progress_step_label.set_text(f"[{p_num}] Декодирование WAV...")
                    else:
                        progress_step_label.set_text(f"[{p_num}] {frame_step}/{max_f} фреймов")

                try:
                    sr, chunk_wav = await run.io_bound(
                        engine.synth,
                        txt,
                        ref_audio=ref,
                        ref_text=ref_txt,
                        temperature=state.bc_temp,
                        top_p=state.bc_top_p,
                        seed=act_seed,
                        model_name=state.selected_model,
                        on_progress=handle_batch_progress
                    )
                    if chunk_wav is not None and len(chunk_wav) > 0:
                        sf.write(str(target_p), chunk_wav, sr)
                        meta_p = num_dir / f"{p_num}.txt"
                        meta_p.write_text(f"file: {target_p.name}\nseed: {act_seed}\ntext: {txt}\n", encoding="utf-8")
                        bc_log_view.push(f"✓ Сохранен {target_p.name} (seed={act_seed})")
                        bc_player.set_source(f"/media/output/NUM/{target_p.name}")
                        badge_label.set_text(f"🎵 {target_p.name}")
                        update_active_seed_display(p_num)
                        select_decade(state.bc_current_decade)
                except Exception as e:
                    bc_log_view.push(f"❌ Ошибка озвучки {p_num}: {e}")

            ui.notify("Пакетная обработка завершена!", color="positive")
        finally:
            remaining_badge.classes(add="hidden")
            progress_container.classes(add="hidden")
            state_indicator.classes(remove="is-running", add="is-ready")
            state_indicator.set_text("Готов к запуску")

    def auto_fill_merge_range(inp_from, inp_to):
        s_min, s_max = bu.scan_num_folder()
        inp_from.set_value(s_min)
        inp_to.set_value(s_max)
        ui.notify(f"Диапазон определен: {s_min} - {s_max}", color="info")

    async def run_merge(f_str, t_str, gap_val):
        try:
            start_n, end_n = int(f_str), int(t_str)
        except Exception:
            ui.notify("Укажите числа для диапазона склейки", color="warning")
            return
        
        num_dir = Path("output/NUM")
        chunks = []
        for n in range(start_n, end_n + 1):
            base_f, _, _, pad = bu.get_fragment_variants_info(n)
            if base_f and base_f.exists():
                data, in_sr = sf.read(str(base_f), dtype="float32")
                if data.ndim > 1:
                    data = data.mean(axis=1)
                chunks.append(data)

        if not chunks:
            ui.notify("Не найдено аудиофайлов для склейки", color="warning")
            return

        merged = engine.concat_audio(chunks, gap=float(gap_val or 0.3))
        out_name = f"{start_n:02d}-{end_n:02d}_merged.wav"
        out_path = Path("output") / out_name
        sf.write(str(out_path), merged, engine.SR)
        
        bc_player.set_source(f"/media/output/{out_name}")
        badge_label.set_text(f"🎵 {out_name}")
        bc_log_view.push(f"🔗 Склеено {len(chunks)} фрагментов в {out_name} (длительность: {len(merged)/engine.SR:.1f} сек)")
        ui.notify(f"Файл {out_name} готов!", color="positive")

    def run_conversion(target_len: int, do_files: bool, do_script: bool):
        res = bu.convert_numbering(target_len, do_files, do_script, state.bc_file_path)
        bc_log_view.push(res)
        ui.notify(f"Нумерация переведена на {target_len} знака!", color="positive")
        refresh_script()

    # Инициализация первичного рендеринга
    try:
        render_decades()
        render_slots()
        render_variants()
        refresh_script()
        inspect_fragment(state.bc_selected_fragment)
    except Exception as e:
        print(f"[UI] Ошибка первичного рендеринга: {e}", flush=True)
        ui.notify("Ошибка при отрисовке интерфейса", color="negative")


def get_free_port(preferred_port: int = 7860) -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", preferred_port))
            return preferred_port
        except OSError:
            pass
    for p in range(preferred_port + 1, preferred_port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", p))
                return p
            except OSError:
                continue
    return preferred_port


# ==============================================================================
# ЗАПУСК
# ==============================================================================
if __name__ in {"__main__", "__mp_main__"}:
    port = get_free_port(int(os.environ.get("PORT", 7860)))
    print("=" * 60)
    print("  Audio Studio T (NiceGUI + Fish Audio Drama 3)")
    print(f"  Dark Studio Edition: http://127.0.0.1:{port}")
    if port != 7860:
        print(f"  [Внимание] Порт 7860 занят (возможно, запущен HiggsAudio-Studio), выбран свободный порт {port}!")
    print("=" * 60)
    
    # Запуск без автоматического открытия браузера, 
    # чтобы избежать конфликтов при инициализации
    ui.run(
        title="Audio Studio T",
        port=port,
        dark=True,
        reload=False,
        show=False,
    )
