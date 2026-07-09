"""Load and validate config.yaml + .env. Import `settings` from here."""
import os
import shutil
import subprocess
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


class Paths(BaseModel):
    music_dir: Path = Path("./music")
    output_dir: Path = Path("./output")
    uploads_dir: Path = Path("./uploads")

    def resolve(self) -> "Paths":
        return Paths(**{k: (PROJECT_ROOT / v).resolve() if not Path(v).is_absolute() else Path(v)
                        for k, v in self.model_dump().items()})


class ColorGrade(BaseModel):
    enabled: bool = True
    saturation: float = 1.15
    contrast: float = 1.05


class Fade(BaseModel):
    in_: float = Field(0.4, alias="in")
    out: float = 0.5

    model_config = {"populate_by_name": True}


class Video(BaseModel):
    target_duration: float = 25
    segment_strategy: str = "energy"   # energy | first
    aspect_strategy: str = "crop"      # crop | pad
    color_grade: ColorGrade = ColorGrade()
    fade: Fade = Fade()
    fps: int = 30
    encoder: str = "h264_videotoolbox"
    bitrate: str = "10M"
    crf: int = 18


class Audio(BaseModel):
    music_mode: str = "duck"           # duck | mix | replace | none
    music_gain_db: float = -14
    loudnorm_target: float = -14


class Captions(BaseModel):
    enabled: bool = True
    font: str = "Avenir Next"
    size: int = 58
    bottom_margin: int = 420


class Hook(BaseModel):
    enabled: bool = True
    duration: float = 2.3
    fallback_text: str = "Wait for it…"


class Whisper(BaseModel):
    model: str = "small"
    compute_type: str = "int8"
    min_speech_seconds: float = 1.5
    max_no_speech_prob: float = 0.6


class Claude(BaseModel):
    model: str = "claude-sonnet-5"
    title_count: int = 3


class Hashtags(BaseModel):
    broad: list[str] = ["#shorts", "#travel"]
    niche_hint: str = "travel"


class Settings(BaseModel):
    paths: Paths = Paths()
    video: Video = Video()
    audio: Audio = Audio()
    captions: Captions = Captions()
    hook: Hook = Hook()
    whisper: Whisper = Whisper()
    claude: Claude = Claude()
    hashtags: Hashtags = Hashtags()

    @property
    def anthropic_api_key(self) -> str | None:
        return os.environ.get("ANTHROPIC_API_KEY") or None


def load_settings() -> Settings:
    cfg_file = PROJECT_ROOT / "config.yaml"
    data = yaml.safe_load(cfg_file.read_text()) if cfg_file.exists() else {}
    s = Settings(**(data or {}))
    s.paths = s.paths.resolve()
    for p in (s.paths.music_dir, s.paths.output_dir, s.paths.uploads_dir):
        p.mkdir(parents=True, exist_ok=True)
    return s


def startup_checks(s: Settings) -> list[str]:
    """Return a list of human-readable warnings; raise only on fatal problems."""
    warnings = []
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg/ffprobe not found. Install with: brew install ffmpeg")
    filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"],
                             capture_output=True, text=True).stdout
    for f in ("overlay", "loudnorm", "sidechaincompress", "amix"):
        if f" {f} " not in filters:
            raise RuntimeError(f"ffmpeg is missing the required '{f}' filter")
    music = list(s.paths.music_dir.glob("*.mp3")) + list(s.paths.music_dir.glob("*.m4a")) \
        + list(s.paths.music_dir.glob("*.wav"))
    if s.audio.music_mode != "none" and not music:
        warnings.append(f"No music files in {s.paths.music_dir} — falling back to music_mode: none")
        s.audio.music_mode = "none"
    if not s.anthropic_api_key:
        warnings.append("ANTHROPIC_API_KEY not set — titles/hashtags will use offline fallback")
    return warnings


settings = load_settings()
