export default {
  template: `
    <div class="ast-waveform-player w-full" ref="playerRoot">
      <!-- Скрытый нативный аудиоплеер для надежного воспроизведения -->
      <audio 
        ref="audioRef" 
        preload="metadata" 
        :src="computed_src" 
        @timeupdate="onTimeUpdate" 
        @loadedmetadata="onLoadedMetadata" 
        @play="syncPlayingState" 
        @playing="syncPlayingState" 
        @pause="syncPlayingState" 
        @ended="onEnded"
        @error="syncPlayingState"
        @abort="syncPlayingState"
        style="display:none;"
      ></audio>

      <!-- Контейнер вейвформа (Canvas на всю ширину) -->
      <div 
        class="ast-wf-canvas-container w-full" 
        ref="wrapRef" 
        @mousedown="startSeek"
        @mousemove="onHover" 
        @mouseleave="hoverTime = null"
      >
        <canvas ref="canvasRef" class="ast-wf-canvas w-full"></canvas>
        <div v-if="hoverTime !== null" class="ast-wf-hover-tip" :style="{ left: hoverX + 'px' }">
          {{ formatTime(hoverTime) }}
        </div>
      </div>

      <!-- Строка времени: 0:01 слева, 0:08 справа -->
      <div class="ast-wf-time-row w-full">
        <span class="ast-wf-time-text">{{ formatTime(currentTime) }}</span>
        <span class="ast-wf-time-text">{{ formatTime(duration) }}</span>
      </div>

      <!-- Панель управления (в стиле HiggsAudio-Studio / скриншот 2) -->
      <div class="ast-wf-controls w-full">
        <!-- Слева: Звук и Скорость -->
        <div class="ast-wf-group ast-wf-left">
          <button class="ast-wf-btn ast-wf-icon-btn" @click="toggleMute" :title="isMuted ? 'Включить звук' : 'Выключить звук'">
            <svg v-if="!isMuted && volume > 0.4" viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
              <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
            </svg>
            <svg v-else-if="!isMuted && volume > 0" viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
              <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/>
            </svg>
            <svg v-else viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
              <path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/>
            </svg>
          </button>
          
          <input 
            type="range" 
            min="0" 
            max="1" 
            step="0.05" 
            :value="isMuted ? 0 : volume" 
            @input="onVolumeInput" 
            class="ast-wf-volume-slider" 
            title="Громкость"
          />

          <button class="ast-wf-btn ast-wf-speed-badge" @click="cycleSpeed" title="Скорость воспроизведения">
            {{ speed }}x
          </button>
        </div>

        <!-- По центру: Назад 5с, Большая фиолетовая кнопка Play, Вперед 5с -->
        <div class="ast-wf-group ast-wf-center">
          <button class="ast-wf-btn ast-wf-icon-btn ast-wf-seek-btn" @click="seekDelta(-5)" title="Назад 5 сек">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
              <path d="M11 18V6l-8.5 6 8.5 6zm.5-6l8.5 6V6l-8.5 6z"/>
            </svg>
          </button>

          <button class="ast-wf-play-btn" @click="togglePlay" :title="isPlaying ? 'Пауза' : 'Воспроизведение'">
            <svg v-if="!isPlaying" viewBox="0 0 24 24" width="28" height="28" fill="currentColor" style="margin-left: 2px;">
              <path d="M8 5v14l11-7z"/>
            </svg>
            <svg v-else viewBox="0 0 24 24" width="28" height="28" fill="currentColor">
              <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>
            </svg>
          </button>

          <button class="ast-wf-btn ast-wf-icon-btn ast-wf-seek-btn" @click="seekDelta(5)" title="Вперед 5 сек">
            <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
              <path d="M4 18l8.5-6L4 6v12zm9-12v12l8.5-6L13 6z"/>
            </svg>
          </button>
        </div>

        <!-- Справа: Скачать файл -->
        <div class="ast-wf-group ast-wf-right">
          <a 
            v-if="computed_src" 
            :href="computed_src" 
            :download="downloadFilename" 
            class="ast-wf-btn ast-wf-icon-btn ast-wf-download-btn" 
            title="Скачать аудиофайл"
          >
            <svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
              <path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/>
            </svg>
          </a>
        </div>
      </div>
    </div>
  `,
  props: {
    src: String,
    title: String,
    autoplay: Boolean,
  },
  data() {
    return {
      computed_src: "",
      isPlaying: false,
      currentTime: 0,
      duration: 0,
      volume: 1.0,
      isMuted: false,
      speed: 1.0,
      speeds: [1.0, 1.25, 1.5, 2.0, 0.75],
      speedIndex: 0,
      rawPeaks: [],
      hoverTime: null,
      hoverX: 0,
      isDragging: false,
      audioCtx: null,
      animFrameId: null,
      resizeObserver: null,
      loadId: 0,
    };
  },
  computed: {
    downloadFilename() {
      if (!this.src) return "audio.wav";
      const parts = this.src.split("/");
      return parts[parts.length - 1] || "audio.wav";
    }
  },
  mounted() {
    setTimeout(() => this.compute_src(), 0);
    this.resizeObserver = new ResizeObserver(() => {
      this.drawWaveform();
    });
    if (this.$refs.wrapRef) {
      this.resizeObserver.observe(this.$refs.wrapRef);
    }
    window.addEventListener("mousemove", this.onWindowMouseMove);
    window.addEventListener("mouseup", this.onWindowMouseUp);
  },
  beforeUnmount() {
    this.stopAnimationLoop();
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
    }
    window.removeEventListener("mousemove", this.onWindowMouseMove);
    window.removeEventListener("mouseup", this.onWindowMouseUp);
  },
  watch: {
    src(newVal) {
      this.compute_src();
    }
  },
  methods: {
    compute_src() {
      const oldSrc = this.computed_src;
      this.computed_src = (this.src && this.src.startsWith("/") ? (window.path_prefix || "") : "") + (this.src || "");
      if (this.computed_src && this.computed_src !== oldSrc) {
        this.stopAnimationLoop();
        this.currentTime = 0;
        this.loadId = (this.loadId || 0) + 1;
        const currentLoadId = this.loadId;

        this.$nextTick(() => {
          const audio = this.$refs.audioRef;
          if (audio) {
            try {
              audio.pause();
            } catch (_) {}
            audio.currentTime = 0;
            audio.src = this.computed_src;
            audio.load();
          }
          this.syncPlayingState();
          this.loadAndDecodeAudio(this.computed_src, currentLoadId);
        });
      }
    },
    async loadAndDecodeAudio(url, currentLoadId) {
      if (!url) {
        this.generateDefaultPeaks();
        this.drawWaveform();
        return;
      }
      try {
        const resp = await fetch(url);
        const arrayBuf = await resp.arrayBuffer();
        if (currentLoadId !== this.loadId) return;

        const AudioCtxClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtxClass) {
          this.generateDefaultPeaks();
          this.drawWaveform();
          return;
        }
        if (!this.audioCtx) {
          this.audioCtx = new AudioCtxClass();
        }
        const audioBuf = await this.audioCtx.decodeAudioData(arrayBuf);
        if (currentLoadId !== this.loadId) return;

        this.extractPeaks(audioBuf);
        this.duration = audioBuf.duration;
        this.drawWaveform();
      } catch (err) {
        if (currentLoadId === this.loadId) {
          this.generateDefaultPeaks();
          this.drawWaveform();
        }
      }
    },
    extractPeaks(buffer) {
      const channelData = buffer.getChannelData(0);
      const totalRaw = 1200;
      const step = Math.max(1, Math.floor(channelData.length / totalRaw));
      const rawPeaks = [];
      let maxPeak = 0.001;

      for (let i = 0; i < totalRaw; i++) {
        const start = i * step;
        let sum = 0;
        const subStep = Math.max(1, Math.floor(step / 6));
        for (let j = 0; j < step; j += subStep) {
          const val = Math.abs(channelData[start + j] || 0);
          if (val > sum) sum = val;
        }
        rawPeaks.push(sum);
        if (sum > maxPeak) maxPeak = sum;
      }

      this.rawPeaks = rawPeaks.map(p => Math.max(0.08, p / maxPeak));
    },
    generateDefaultPeaks() {
      const totalRaw = 600;
      const peaks = [];
      for (let i = 0; i < totalRaw; i++) {
        const val = 0.25 + 0.38 * Math.sin(i * 0.12) * Math.sin(i * 0.04 + 1.1) + 0.18 * Math.cos(i * 0.28);
        peaks.push(Math.max(0.08, Math.min(1.0, Math.abs(val))));
      }
      this.rawPeaks = peaks;
    },
    drawWaveform() {
      const canvas = this.$refs.canvasRef;
      const wrap = this.$refs.wrapRef;
      if (!canvas || !wrap) return;

      const dpr = window.devicePixelRatio || 1;
      const rect = wrap.getBoundingClientRect();
      const w = Math.max(200, rect.width);
      const h = 76;

      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
      }
      canvas.style.width = "100%";
      canvas.style.height = h + "px";

      const ctx = canvas.getContext("2d");
      ctx.save();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, w, h);

      if (!this.rawPeaks || this.rawPeaks.length === 0) {
        this.generateDefaultPeaks();
      }

      const barWidth = 2.2;
      const barGap = 1.6;
      const totalBars = Math.max(30, Math.floor(w / (barWidth + barGap)));
      const step = this.rawPeaks.length / totalBars;
      const centerY = h / 2;
      const maxBarH = (h / 2) - 3;

      const progress = this.duration > 0 ? (this.currentTime / this.duration) : 0;
      const currentX = progress * w;

      for (let i = 0; i < totalBars; i++) {
        const rawIdx = Math.min(this.rawPeaks.length - 1, Math.floor(i * step));
        const val = this.rawPeaks[rawIdx] || 0.1;
        const x = i * (barWidth + barGap);
        const barH = val * maxBarH;
        const isPlayed = (x + barWidth / 2) <= currentX;

        ctx.fillStyle = isPlayed ? "#f97316" : "#6c7f94";

        const topY = centerY - barH;
        const fullH = Math.max(3, barH * 2);
        
        ctx.beginPath();
        const r = Math.min(barWidth / 2, 1.5);
        if (ctx.roundRect) {
          ctx.roundRect(x, topY, barWidth, fullH, r);
        } else {
          ctx.rect(x, topY, barWidth, fullH);
        }
        ctx.fill();
      }

      if (this.duration > 0 && currentX >= 0 && currentX <= w) {
        ctx.fillStyle = "#ffffff";
        ctx.shadowColor = "rgba(255, 255, 255, 0.85)";
        ctx.shadowBlur = 6;
        ctx.fillRect(currentX - 1, 3, 2, h - 6);
        ctx.shadowBlur = 0;
      }

      ctx.restore();
    },
    startAnimationLoop() {
      if (this.animFrameId) cancelAnimationFrame(this.animFrameId);
      const loop = () => {
        if (this.$refs.audioRef && !this.$refs.audioRef.paused) {
          this.currentTime = this.$refs.audioRef.currentTime;
          this.drawWaveform();
          this.animFrameId = requestAnimationFrame(loop);
        } else {
          this.stopAnimationLoop();
        }
      };
      this.animFrameId = requestAnimationFrame(loop);
    },
    stopAnimationLoop() {
      if (this.animFrameId) {
        cancelAnimationFrame(this.animFrameId);
        this.animFrameId = null;
      }
    },
    syncPlayingState() {
      const audio = this.$refs.audioRef;
      if (!audio) {
        this.isPlaying = false;
        this.stopAnimationLoop();
        return;
      }
      const isActuallyPlaying = !audio.paused && !audio.ended && audio.currentTime > 0;
      this.isPlaying = isActuallyPlaying;
      if (isActuallyPlaying) {
        this.startAnimationLoop();
      } else {
        this.stopAnimationLoop();
      }
      this.drawWaveform();
    },
    onTimeUpdate() {
      if (this.$refs.audioRef) {
        this.currentTime = this.$refs.audioRef.currentTime;
        if (!this.duration && this.$refs.audioRef.duration) {
          this.duration = this.$refs.audioRef.duration;
        }
      }
      if (!this.isPlaying) {
        this.drawWaveform();
      }
    },
    onLoadedMetadata() {
      if (this.$refs.audioRef) {
        this.duration = this.$refs.audioRef.duration;
      }
      this.drawWaveform();
    },
    onEnded() {
      this.isPlaying = false;
      this.stopAnimationLoop();
      this.currentTime = 0;
      if (this.$refs.audioRef) {
        this.$refs.audioRef.currentTime = 0;
      }
      this.drawWaveform();
    },
    togglePlay() {
      const audio = this.$refs.audioRef;
      if (!audio) return;
      if (audio.paused) {
        this.play();
      } else {
        audio.pause();
        this.syncPlayingState();
      }
    },
    play() {
      const audio = this.$refs.audioRef;
      if (!audio) return;

      const doPlay = () => {
        const p = audio.play();
        if (p && typeof p.then === "function") {
          p.then(() => {
            this.isPlaying = true;
            this.startAnimationLoop();
          }).catch(err => {
            if (err.name !== "AbortError") {
              console.warn("[Waveform] Play error:", err);
            }
            this.syncPlayingState();
          });
        }
      };

      if (audio.readyState >= 2) {
        doPlay();
      } else {
        const onCanPlay = () => {
          doPlay();
          audio.removeEventListener("canplay", onCanPlay);
        };
        audio.addEventListener("canplay", onCanPlay);
      }
    },
    pause() {
      if (this.$refs.audioRef) {
        this.$refs.audioRef.pause();
        this.syncPlayingState();
      }
    },
    seek(seconds) {
      if (this.$refs.audioRef) {
        this.currentTime = Math.max(0, Math.min(seconds, this.duration || 9999));
        this.$refs.audioRef.currentTime = this.currentTime;
        this.drawWaveform();
      }
    },
    seekDelta(delta) {
      if (this.$refs.audioRef) {
        this.seek(this.$refs.audioRef.currentTime + delta);
      }
    },
    startSeek(e) {
      this.isDragging = true;
      this.applySeekFromEvent(e);
    },
    onWindowMouseMove(e) {
      if (this.isDragging) {
        this.applySeekFromEvent(e);
      }
    },
    onWindowMouseUp() {
      this.isDragging = false;
    },
    applySeekFromEvent(e) {
      const wrap = this.$refs.wrapRef;
      if (!wrap || !this.duration) return;
      const rect = wrap.getBoundingClientRect();
      const clientX = e.clientX;
      const pos = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      this.seek(pos * this.duration);
    },
    onHover(e) {
      const wrap = this.$refs.wrapRef;
      if (!wrap || !this.duration) {
        this.hoverTime = null;
        return;
      }
      const rect = wrap.getBoundingClientRect();
      const pos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      this.hoverX = e.clientX - rect.left;
      this.hoverTime = pos * this.duration;
    },
    toggleMute() {
      const audio = this.$refs.audioRef;
      if (!audio) return;
      audio.muted = !audio.muted;
      this.isMuted = audio.muted;
    },
    onVolumeInput(e) {
      const val = parseFloat(e.target.value);
      this.volume = val;
      if (this.$refs.audioRef) {
        this.$refs.audioRef.volume = val;
        this.$refs.audioRef.muted = (val === 0);
        this.isMuted = (val === 0);
      }
    },
    cycleSpeed() {
      this.speedIndex = (this.speedIndex + 1) % this.speeds.length;
      this.speed = this.speeds[this.speedIndex];
      if (this.$refs.audioRef) {
        this.$refs.audioRef.playbackRate = this.speed;
      }
    },
    formatTime(sec) {
      if (!sec || isNaN(sec) || sec < 0) return "0:00";
      const m = Math.floor(sec / 60);
      const s = Math.floor(sec % 60);
      return `${m}:${s < 10 ? '0' : ''}${s}`;
    }
  }
};
