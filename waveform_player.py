from __future__ import annotations
from pathlib import Path
from typing import Any, Optional
from nicegui.elements.mixins.source_element import SourceElement

class WaveformPlayer(SourceElement, component='waveform_player.js'):
    SOURCE_IS_MEDIA_FILE = True

    def __init__(self, src: str = "", *, title: str = "", autoplay: bool = False) -> None:
        super().__init__(source=src)
        self._props['title'] = title
        self._props['autoplay'] = autoplay

    def play(self) -> None:
        self.run_method('play')

    def pause(self) -> None:
        self.run_method('pause')

    def seek(self, seconds: float) -> None:
        self.run_method('seek', seconds)
