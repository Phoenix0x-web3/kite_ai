import random
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from browserforge.fingerprints import (
    Fingerprint,
    FingerprintGenerator,
    NavigatorFingerprint,
    Screen,
    ScreenFingerprint,
    VideoCard,
)

try:
    import orjson as _json

    _USE_ORJSON = True
except ImportError:
    import json as _json

    _USE_ORJSON = False


POPULAR_RESOLUTIONS: Dict[str, Dict[str, float]] = {
    "1920x1080": {"w": 1920, "h": 1080, "weight": 22.0},
    "1366x768": {"w": 1366, "h": 768, "weight": 12.0},
    "1536x864": {"w": 1536, "h": 864, "weight": 8.0},
    "1440x900": {"w": 1440, "h": 900, "weight": 6.0},
    "1280x720": {"w": 1280, "h": 720, "weight": 5.0},
    "1600x900": {"w": 1600, "h": 900, "weight": 5.0},
    "2560x1440": {"w": 2560, "h": 1440, "weight": 7.0},
    "1280x800": {"w": 1280, "h": 800, "weight": 3.0},
    "1680x1050": {"w": 1680, "h": 1050, "weight": 3.0},
    "1280x1024": {"w": 1280, "h": 1024, "weight": 2.0},
    "1920x1200": {"w": 1920, "h": 1200, "weight": 3.0},
    "2560x1600": {"w": 2560, "h": 1600, "weight": 2.0},
    "3840x2160": {"w": 3840, "h": 2160, "weight": 5.0},
    "3440x1440": {"w": 3440, "h": 1440, "weight": 2.0},
    "2560x1080": {"w": 2560, "h": 1080, "weight": 1.5},
    "2736x1824": {"w": 2736, "h": 1824, "weight": 1.0},
    "3200x1800": {"w": 3200, "h": 1800, "weight": 1.5},
    "1024x768": {"w": 1024, "h": 768, "weight": 1.0},
    "1360x768": {"w": 1360, "h": 768, "weight": 2.0},
    "2256x1504": {"w": 2256, "h": 1504, "weight": 1.0},
}


Mic = Dict[str, Union[str, float, List[str]]]
Out = Dict[str, Union[str, float, List[str]]]

MICROPHONES: List[Mic] = [
    {"name": "Microphone (Realtek(R) Audio)", "w": 12, "os": ["windows"]},
    {
        "name": "Microphone Array (Intel® Smart Sound Technology)",
        "w": 9,
        "os": ["windows"],
    },
    {"name": "Microphone Array (Conexant SmartAudio HD)", "w": 6, "os": ["windows"]},
    {"name": "Microsoft LifeChat LX-3000 Microphone", "w": 2, "os": ["windows"]},
    {"name": "Lenovo USB-C Headset Microphone", "w": 2.5, "os": ["windows"]},
    {"name": "Dell USB Audio Microphone", "w": 2.5, "os": ["windows"]},
    {"name": "Logitech C920 Microphone", "w": 2, "os": ["windows"]},
    {"name": "Razer Kiyo Microphone", "w": 1.5, "os": ["windows"]},
    {"name": "Built-in Microphone", "w": 10, "os": ["macos", "linux"]},
    {"name": "MacBook Pro Microphone", "w": 14, "os": ["macos"]},
    {"name": "MacBook Air Microphone", "w": 12, "os": ["macos"]},
    {"name": "iMac Microphone", "w": 8, "os": ["macos"]},
    {"name": "Built-in Audio - Internal Microphone", "w": 8, "os": ["linux"]},
    {"name": "HDA Intel PCH Front Mic", "w": 5, "os": ["linux"]},
    {"name": "HDA Intel PCH Rear Mic", "w": 3, "os": ["linux"]},
    {"name": "USB Audio Device Microphone", "w": 3, "os": ["linux"]},
    {"name": "Logitech USB Microphone", "w": 4, "os": ["windows", "macos", "linux"]},
    {"name": "Blue Yeti", "w": 6, "os": ["windows", "macos", "linux"]},
    {"name": "Blue Snowball iCE", "w": 4, "os": ["windows", "macos", "linux"]},
    {"name": "Shure MV7", "w": 3.5, "os": ["windows", "macos", "linux"]},
    {
        "name": "Shure SM7B (Focusrite Scarlett 2i2)",
        "w": 2.5,
        "os": ["windows", "macos", "linux"],
    },
    {
        "name": "Focusrite USB (Scarlett Solo)",
        "w": 3,
        "os": ["windows", "macos", "linux"],
    },
    {"name": "Behringer UMC22", "w": 2.5, "os": ["windows", "macos", "linux"]},
    {"name": "Elgato Wave:3", "w": 3, "os": ["windows", "macos", "linux"]},
    {"name": "RODE NT-USB", "w": 3, "os": ["windows", "macos", "linux"]},
    {"name": "RODE NT-USB Mini", "w": 2.5, "os": ["windows", "macos", "linux"]},
    {"name": "Razer Seiren X", "w": 2, "os": ["windows", "macos", "linux"]},
    {"name": "HyperX QuadCast", "w": 2.2, "os": ["windows", "macos", "linux"]},
    {
        "name": "Audio-Technica AT2020USB+",
        "w": 2.2,
        "os": ["windows", "macos", "linux"],
    },
    {
        "name": "Audio-Technica ATR2100x-USB",
        "w": 2.0,
        "os": ["windows", "macos", "linux"],
    },
    {"name": "Samson Q2U", "w": 1.8, "os": ["windows", "macos", "linux"]},
    {"name": "FIFINE K669B", "w": 1.6, "os": ["windows", "macos", "linux"]},
    {"name": "Bose QC35 Microphone", "w": 1.2, "os": ["windows", "macos", "linux"]},
    {
        "name": "Jabra Evolve2 65 Microphone",
        "w": 1.4,
        "os": ["windows", "macos", "linux"],
    },
    {
        "name": "Plantronics Blackwire C5220 Microphone",
        "w": 1.3,
        "os": ["windows", "macos", "linux"],
    },
    {
        "name": "Sennheiser SC 60 Microphone",
        "w": 1.3,
        "os": ["windows", "macos", "linux"],
    },
    {"name": "Corsair HS60 Microphone", "w": 1.1, "os": ["windows", "macos", "linux"]},
    {
        "name": "SteelSeries Arctis 7 Chat",
        "w": 1.1,
        "os": ["windows", "macos", "linux"],
    },
    {"name": "Logitech BRIO Microphone", "w": 1.0, "os": ["windows", "macos", "linux"]},
    {"name": "AirPods Microphone", "w": 0.2, "os": ["windows", "macos", "linux"]},
    {"name": "AirPods Pro Microphone", "w": 0.15, "os": ["windows", "macos", "linux"]},
    {
        "name": "USB PnP Sound Device Microphone",
        "w": 1.5,
        "os": ["windows", "macos", "linux"],
    },
]

AUDIO_OUTPUTS: List[Out] = [
    {"name": "Speakers (Realtek(R) Audio)", "w": 14, "os": ["windows"]},
    {"name": "Headphones (Realtek(R) Audio)", "w": 8, "os": ["windows"]},
    {"name": "Realtek Digital Output (Optical)", "w": 2.5, "os": ["windows"]},
    {"name": "Speakers (High Definition Audio Device)", "w": 4, "os": ["windows"]},
    {"name": "NVIDIA High Definition Audio", "w": 5, "os": ["windows"]},
    {"name": "AMD High Definition Audio Device", "w": 3.5, "os": ["windows"]},
    {"name": "Intel Display Audio", "w": 3.5, "os": ["windows"]},
    {"name": "Dell U2720Q (NVIDIA High Definition Audio)", "w": 1.2, "os": ["windows"]},
    {"name": "Built-in Output", "w": 16, "os": ["macos"]},
    {"name": "MacBook Pro Speakers", "w": 18, "os": ["macos"]},
    {"name": "MacBook Air Speakers", "w": 15, "os": ["macos"]},
    {"name": "iMac Speakers", "w": 12, "os": ["macos"]},
    {"name": "External Headphones", "w": 6, "os": ["macos"]},
    {"name": "Built-in Audio Analog Stereo", "w": 10, "os": ["linux"]},
    {"name": "Built-in Audio Digital Stereo (HDMI)", "w": 6, "os": ["linux"]},
    {"name": "HDA Intel PCH (ALCxxx) Analog", "w": 5, "os": ["linux"]},
    {"name": "HDA NVIDIA HDMI/DP", "w": 3.5, "os": ["linux"]},
    {
        "name": "Logitech USB Headset H390",
        "w": 2.2,
        "os": ["windows", "macos", "linux"],
    },
    {"name": "HyperX Cloud II Wireless", "w": 2.0, "os": ["windows", "macos", "linux"]},
    {"name": "Corsair HS60", "w": 1.5, "os": ["windows", "macos", "linux"]},
    {
        "name": "SteelSeries Arctis 7 Game",
        "w": 1.7,
        "os": ["windows", "macos", "linux"],
    },
    {
        "name": "Creative Sound BlasterX G6",
        "w": 1.3,
        "os": ["windows", "macos", "linux"],
    },
    {"name": "ASUS Xonar", "w": 1.2, "os": ["windows", "linux"]},
    {"name": "Focusrite USB (Line Out)", "w": 1.8, "os": ["windows", "macos", "linux"]},
    {"name": "Behringer UMC22 Output", "w": 1.4, "os": ["windows", "macos", "linux"]},
    {"name": "Elgato Wave:3 Monitor", "w": 1.2, "os": ["windows", "macos", "linux"]},
    {"name": "USB PnP Sound Device", "w": 1.6, "os": ["windows", "macos", "linux"]},
    {"name": "LG TV (Intel Display Audio)", "w": 0.9, "os": ["windows", "linux"]},
    {
        "name": "Samsung TV (AMD High Definition Audio)",
        "w": 0.9,
        "os": ["windows", "linux"],
    },
    {"name": "Yamaha RX-V (HDMI)", "w": 0.8, "os": ["windows", "macos", "linux"]},
    {"name": "Bluetooth Audio Receiver", "w": 1.0, "os": ["windows", "macos", "linux"]},
    {"name": "HDMI Output", "w": 2.0, "os": ["windows", "macos", "linux"]},
    {"name": "DisplayPort Output", "w": 1.5, "os": ["windows", "macos", "linux"]},
    {"name": "Google Cast", "w": 0.6, "os": ["windows", "macos", "linux"]},
    {"name": "AirPods", "w": 0.3, "os": ["windows", "macos", "linux"]},
    {"name": "AirPods Pro", "w": 0.25, "os": ["windows", "macos", "linux"]},
    {"name": "Sony WH-1000XM4 Stereo", "w": 1.2, "os": ["windows", "macos", "linux"]},
    {"name": "Bose QC35 Stereo", "w": 1.1, "os": ["windows", "macos", "linux"]},
    {"name": "Jabra Evolve2 65 Stereo", "w": 1.0, "os": ["windows", "macos", "linux"]},
    {
        "name": "Plantronics Blackwire C5220",
        "w": 0.9,
        "os": ["windows", "macos", "linux"],
    },
    {
        "name": "Sennheiser HD 4.40BT Stereo",
        "w": 0.8,
        "os": ["windows", "macos", "linux"],
    },
    {"name": "CalDigit TS3 Plus Audio", "w": 0.8, "os": ["macos"]},
]


_SCHEMA_KEY = "__schema_version"
_HEADERS_LIST_KEY = "__headers_list"
_SCHEMA_VERSION = 1


@dataclass
class PlaywrightFingerprint(Fingerprint):
    def to_json(self) -> str:
        payload: Dict[str, Any] = asdict(self)
        payload[_SCHEMA_KEY] = _SCHEMA_VERSION
        payload[_HEADERS_LIST_KEY] = list(self.headers.items())
        if _USE_ORJSON:
            return _json.dumps(payload).decode()
        return _json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, blob: Union[str, Dict[str, Any]]) -> "PlaywrightFingerprint":
        data: Dict[str, Any] = (
            _json.loads(blob) if isinstance(blob, str) else dict(blob)
        )
        headers_pairs = data.get(_HEADERS_LIST_KEY)
        headers = (
            dict(headers_pairs) if headers_pairs is not None else dict(data["headers"])
        )
        screen = ScreenFingerprint(**data["screen"])

        nav = dict(data["navigator"])
        if "language" not in nav and nav.get("languages"):
            nav["language"] = nav["languages"][0]
        navigator = NavigatorFingerprint(**nav)

        video_card = VideoCard(**data["videoCard"]) if data.get("videoCard") else None

        return cls(
            screen=screen,
            navigator=navigator,
            headers=headers,
            videoCodecs=data["videoCodecs"],
            audioCodecs=data["audioCodecs"],
            pluginsData=data["pluginsData"],
            battery=data.get("battery"),
            videoCard=video_card,
            multimediaDevices=data.get("multimediaDevices", []),
            fonts=data.get("fonts", []),
            mockWebRTC=data.get("mockWebRTC"),
            slim=data.get("slim"),
        )


def _weighted_choice(items: List[Tuple[int, float]], rng: random.Random) -> int:
    # items: [(index, weight), ...]
    total = sum(w for _, w in items) or 1.0
    r = rng.uniform(0, total)
    acc = 0.0
    for idx, w in items:
        acc += w
        if r <= acc:
            return idx
    return items[-1][0]


def _weighted_sample_without_replacement(
    names: List[str], weights: List[float], k: int, rng: random.Random
) -> List[str]:
    k = max(0, min(k, len(names)))
    selected: List[str] = []
    pool = list(range(len(names)))
    w = weights[:]
    for _ in range(k):
        if not pool:
            break
        choice_idx = _weighted_choice([(i, w[i]) for i in pool], rng)
        selected.append(names[choice_idx])
        pool.remove(choice_idx)
    return selected


def _detect_os(navigator: NavigatorFingerprint) -> str:
    plat = (navigator.platform or "").lower()
    ua = (navigator.userAgent or "").lower()
    if "mac" in plat or "mac os" in ua or "macintosh" in ua:
        return "macos"
    if "win" in plat or "windows" in ua:
        return "windows"
    if "linux" in plat or "x11" in ua or "ubuntu" in ua:
        return "linux"
    # дефолт — windows (чтоб не попадали mac-only на win случайно)
    return "windows"


def _pool_for_os(
    items: List[Dict[str, Any]], os_key: str
) -> Tuple[List[str], List[float]]:
    names, weights = [], []
    for it in items:
        if os_key in it["os"]:
            names.append(str(it["name"]))
            weights.append(float(it["w"]))
    return names, weights


class PopularProfileFingerprintGenerator(FingerprintGenerator):
    def __init__(
        self,
        *args,
        use_popular_resolution: bool = True,
        fixed_resolution_key: Optional[str] = None,
        num_microphones: int = 1,
        num_audio_outputs: int = 1,
        seed: Optional[Union[int, str]] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.use_popular_resolution = use_popular_resolution
        self.fixed_resolution_key = fixed_resolution_key
        self.num_microphones = num_microphones
        self.num_audio_outputs = num_audio_outputs
        self._rng = random.Random()
        if seed is not None:
            self._rng.seed(seed)

    def _pick_resolution(self) -> Tuple[int, int]:
        if self.fixed_resolution_key:
            r = POPULAR_RESOLUTIONS.get(self.fixed_resolution_key)
            if not r:
                raise ValueError(f"Unknown resolution key: {self.fixed_resolution_key}")
            return int(r["w"]), int(r["h"])
        items = [
            (k, float(v.get("weight", 1.0))) for k, v in POPULAR_RESOLUTIONS.items()
        ]
        keys = list(POPULAR_RESOLUTIONS.keys())
        idx = _weighted_choice([(i, items[i][1]) for i in range(len(items))], self._rng)
        key = keys[idx]
        r = POPULAR_RESOLUTIONS[key]
        return int(r["w"]), int(r["h"])

    def _popular_media_devices_for_os(self, os_key: str) -> dict:
        mic_names, mic_weights = _pool_for_os(MICROPHONES, os_key)
        out_names, out_weights = _pool_for_os(AUDIO_OUTPUTS, os_key)

        # выборка с учётом весов
        mics = _weighted_sample_without_replacement(
            mic_names, mic_weights, self.num_microphones, self._rng
        )
        outs = _weighted_sample_without_replacement(
            out_names, out_weights, self.num_audio_outputs, self._rng
        )

        def _fmt(kind: str, label: str) -> dict:
            return {"deviceId": "", "kind": kind, "label": label, "groupId": ""}

        speakers = [_fmt("audiooutput", name) for name in outs]
        micros = [_fmt("audioinput", name) for name in mics]
        webcams = [_fmt("videoinput", "Integrated HD Camera")]

        return {"speakers": speakers, "micros": micros, "webcams": webcams}

    def generate(
        self,
        *,
        screen: Optional[Screen] = None,
        strict: Optional[bool] = None,
        mock_webrtc: Optional[bool] = None,
        slim: Optional[bool] = None,
        **header_kwargs,
    ) -> PlaywrightFingerprint:
        screen_to_use = screen or self.screen
        if self.use_popular_resolution and screen_to_use is None:
            w, h = self._pick_resolution()
            screen_to_use = Screen(min_width=w, max_width=w, min_height=h, max_height=h)

        base_fp = super().generate(
            screen=screen_to_use,
            strict=strict,
            mock_webrtc=mock_webrtc,
            slim=slim,
            **header_kwargs,
        )

        os_key = _detect_os(base_fp.navigator)

        devices = self._popular_media_devices_for_os(os_key)

        data = asdict(base_fp)
        if devices:
            data["multimediaDevices"] = devices

        return PlaywrightFingerprint(
            screen=ScreenFingerprint(**data["screen"]),
            navigator=NavigatorFingerprint(**data["navigator"]),
            headers=data["headers"],
            videoCodecs=data["videoCodecs"],
            audioCodecs=data["audioCodecs"],
            pluginsData=data["pluginsData"],
            battery=data.get("battery"),
            videoCard=VideoCard(**data["videoCard"]) if data.get("videoCard") else None,
            multimediaDevices=data.get("multimediaDevices", []),
            fonts=data.get("fonts", []),
            mockWebRTC=data.get("mockWebRTC"),
            slim=data.get("slim"),
        )
