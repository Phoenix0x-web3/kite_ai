# base_browser.py
from __future__ import annotations

import asyncio
import hashlib
import json
import textwrap
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from browserforge.headers import Browser
from browserforge.injectors.utils import InjectFunction
from curl_cffi import AsyncSession
from loguru import logger

from ..js.mouse import MouseOverlay
from .fingerprint import (
    PlaywrightFingerprint,
    PopularProfileFingerprintGenerator,
)

_TZ_LOCALE_MAP = {
    "Europe/Amsterdam": "nl-NL",
    "Europe/Berlin": "de-DE",
    "Europe/Paris": "fr-FR",
    "Europe/Madrid": "es-ES",
    "Europe/Rome": "it-IT",
    "Europe/Lisbon": "pt-PT",
    "Europe/London": "en-GB",
    "Europe/Dublin": "en-IE",
    "Europe/Warsaw": "pl-PL",
    "Europe/Prague": "cs-CZ",
    "Europe/Vienna": "de-AT",
    "Europe/Zurich": "de-CH",
    "Europe/Brussels": "fr-BE",
    "Europe/Stockholm": "sv-SE",
    "Europe/Copenhagen": "da-DK",
    "Europe/Helsinki": "fi-FI",
    "Europe/Athens": "el-GR",
    "Europe/Budapest": "hu-HU",
    "Europe/Bucharest": "ro-RO",
    "Europe/Sofia": "bg-BG",
    "Europe/Oslo": "nb-NO",
    "America/New_York": "en-US",
    "America/Chicago": "en-US",
    "America/Los_Angeles": "en-US",
    "America/Toronto": "en-CA",
    "America/Mexico_City": "es-MX",
    "America/Sao_Paulo": "pt-BR",
    "Asia/Singapore": "en-SG",
    "Asia/Tokyo": "ja-JP",
    "Asia/Seoul": "ko-KR",
    "Asia/Hong_Kong": "zh-HK",
    "Asia/Shanghai": "zh-CN",
    "Asia/Taipei": "zh-TW",
    "Asia/Bangkok": "th-TH",
    "Asia/Jakarta": "id-ID",
    "Asia/Ho_Chi_Minh": "vi-VN",
}


def _locale_from_tz(tz: str) -> str:
    if tz in _TZ_LOCALE_MAP:
        return _TZ_LOCALE_MAP[tz]
    if tz.startswith("Europe/"):
        return "en-GB"
    if tz.startswith("America/"):
        return "en-US"
    if tz.startswith("Asia/"):
        return "en-SG"
    return "en-GB"


def _accept_language(langs: List[str]) -> str:
    out, seen = [], set()
    for i, lang in enumerate(langs[:8]):
        if lang in seen:
            continue
        seen.add(lang)
        q = 1.0 if i == 0 else max(0.1, round(1.0 - i * 0.1, 1))
        out.append(lang if i == 0 else f"{lang};q={q}")
    return ",".join(out)


def _as_dict(obj):
    # Поддержка dataclass (VideoCard/Navigator), dict и None
    try:
        from dataclasses import asdict, is_dataclass

        if is_dataclass(obj):
            return asdict(obj)
    except Exception:
        pass
    if isinstance(obj, dict):
        return obj
    # generic: попробуем атрибуты
    try:
        return {k: getattr(obj, k) for k in dir(obj) if not k.startswith("_") and not callable(getattr(obj, k))}
    except Exception:
        return {}


class BrowserBase:
    wallet: Any
    page: Any
    mouse: Optional[MouseOverlay]

    def __init__(self, wallet: Any) -> None:
        self.wallet = wallet
        self.page = None
        self.mouse = None
        self._console_piped = False

    # ---------- PUBLIC API ----------

    async def create_fingerprint(self) -> PlaywrightFingerprint:
        gen = PopularProfileFingerprintGenerator(
            browser=[Browser(name="chrome", min_version=141, max_version=141)],
            os=("windows"),
            device=("desktop"),
            use_popular_resolution=True,
            fixed_resolution_key=None,
            num_microphones=1,
            num_audio_outputs=1,
            seed=f"wallet:{self.wallet.id}",
        )

        fp: PlaywrightFingerprint = gen.generate(strict=False)
        return fp

    async def open_with_fingerprint(
        self,
        pw,
        fingerprint=None,
        *,
        grant_origins: Optional[List[str]] = None,
        headless=False,
        additional_scripts=[],
        cookies=[],
    ):
        proxy = self._parse_proxy_settings(self.wallet.proxy)

        fingerprint = await self.create_fingerprint()

        tz = await self._tz_by_proxy(default="Europe/Amsterdam")
        locale = _locale_from_tz(tz)
        locale = "en-US"
        languages = [locale, locale.split("-")[0], "en-GB", "en"]

        nav = getattr(fingerprint, "navigator", {}) or {}
        headers = getattr(fingerprint, "headers", {}) or {}
        ua = getattr(nav, "userAgent", None) or headers.get("User-Agent") or ""
        uad = getattr(nav, "userAgentData", {}) or {}
        brands = uad.get("fullVersionList") or uad.get("brands") or []

        uach_meta = {
            "brands": brands,
            "fullVersionList": brands,
            "platform": uad.get("platform") or "Windows",
            "platformVersion": uad.get("platformVersion") or "10.0.0",
            "architecture": uad.get("architecture") or "x86",
            "model": uad.get("model") or "",
            "mobile": bool(uad.get("mobile", False)),
            "bitness": uad.get("bitness") or "64",
            "wow64": False,
        }

        sec_ch_ua = self._sec_ch_ua(brands)
        full_version = self._pick_full_version(uach_meta)

        scr = fingerprint.screen
        ow, oh = int(scr.outerWidth or scr.width), int(scr.outerHeight or scr.height)
        iw, ih = (
            int(scr.innerWidth or min(ow, 1280)),
            int(scr.innerHeight or min(oh, 720)),
        )
        dpr = float(scr.devicePixelRatio or 1.0)

        browser = await pw.chromium.launch(
            channel="chrome",
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
                "--no-first-run",
                "--disable-dev-shm-usage",
                "--allow-pre-commit-input",
                "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--webrtc-ip-private-interface=0",
                "--webrtc-ip-handling-policy=disable_non_proxied_udp",
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                f"--lang={locale}",
                "--disable-setuid-sandbox",
                "--no-sandbox",
            ],
            ignore_default_args=[
                "--enable-automation",
                "--disable-blink-features=AutomationControlled",

            ],
        )
        browser_ctx = await browser.new_context(
            user_agent=ua,
            locale=locale,
            timezone_id=tz,
            no_viewport=False,
            viewport={
                "width": fingerprint.screen.width,
                "height": fingerprint.screen.height,
            },
            proxy=proxy,
            permissions=["microphone"],
        )

        try:
            await browser_ctx.set_extra_http_headers(
                {
                    "User-Agent": ua,
                    "Accept-Language": _accept_language(languages),
                    "Sec-CH-UA": sec_ch_ua,
                    "Sec-CH-UA-Platform": f'"{uach_meta["platform"]}"',
                    "Sec-CH-UA-Mobile": "?1" if uach_meta["mobile"] else "?0",
                    "Sec-CH-UA-Platform-Version": f'"{uach_meta["platformVersion"]}"',
                    "Sec-CH-UA-Arch": f'"{uach_meta["architecture"]}"',
                    "Sec-CH-UA-Bitness": f'"{uach_meta["bitness"]}"',
                    "Sec-CH-UA-Full-Version": f'"{full_version}"',
                }
            )

        except Exception as e:
            logger.debug(f"[Base] set_extra_http_headers failed: {e}")

        await browser_ctx.add_cookies(cookies)
        vendor, renderer, gl_params = self._extract_webgl_from_fp(fingerprint)
        salt = self._salt_from_fp(fingerprint, vendor, renderer)

        canvas_js = self._canvas_patch_js(mode="noise", salt=salt)
        webgl_js = self._webgl_patch_js(vendor, renderer, salt, gl_params)

        sn = {
            "#logo": [{"x": 12.345, "y": 20.000, "width": 200.000, "height": 40.000}],
            ".nav-item.kv": [{"x": 100.123, "y": 50.000, "width": 80.000, "height": 20.000}],
        }

        # snapshots = fingerprint.get("snapshots")

        rects = self._clientrects_patch_js_stable(seed=f"wallet:{self.wallet.id}", snapshots=sn, max_jitter_px=0.4)

        audio = self._audio_stable_patch_js(
            seed=f"wallet:{self.wallet.id}",
            params={
                "noise_level": 1e-5,
                "step": 128,
                "channels": "all",
                "tts_voice": {"name": "Milena", "lang": "ru-RU", "default": True},
            },
        )

        # 5.1) патч для <script srcdoc> (sandbox iframes)
        srcdoc_js = self._srcdoc_injector_js(canvas_js + "\n" + webgl_js)

        # 5.2) воркеры: пропатчить Worker/SharedWorker, инжектнуть наш payload
        worker_bootstrap = self._webgl_worker_bootstrap_js(vendor, renderer, salt, gl_params)
        worker_wrapper = self._wrap_worker_loader_js(worker_bootstrap)

        # INJECT FINGER PRINT
        await browser_ctx.add_init_script(
            InjectFunction(fingerprint),
        )

        # ADITION FINGERPRINT INJECT
        await browser_ctx.add_init_script(self.build_nav_init_from_fp(fingerprint))

        if additional_scripts:
            for script in additional_scripts:
                await browser_ctx.add_init_script(script)

        # ADDITION CANVAS WEBGL RECTS AUDIO (not correct)
        await browser_ctx.add_init_script(canvas_js)
        await browser_ctx.add_init_script(webgl_js)

        await browser_ctx.add_init_script(rects)
        await browser_ctx.add_init_script(audio)

        # await browser_ctx.add_init_script(worker_wrapper)
        # await browser_ctx.add_init_script(srcdoc_js)

        async def _apply_cdp(page):
            try:
                cdp = await browser_ctx.new_cdp_session(page)
                await cdp.send(
                    "Network.setUserAgentOverride",
                    {
                        "userAgent": ua,
                        "userAgentMetadata": uach_meta,
                        "platform": uach_meta["platform"],
                    },
                )
                await cdp.send(
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": iw,
                        "height": ih,
                        "deviceScaleFactor": dpr,
                        "mobile": False,
                        "screenWidth": int(scr.width or ow),
                        "screenHeight": int(scr.height or oh),
                        "screenOrientation": {"type": "landscapePrimary", "angle": 0},
                    },
                )

            except Exception as e:
                logger.debug(f"[Base] CDP UA override failed: {e}")

        browser_ctx.on("page", lambda p: asyncio.create_task(_apply_cdp(p)))

        page = await browser_ctx.new_page()

        await page.set_viewport_size({"width": iw, "height": ih})

        await _apply_cdp(page)

        if grant_origins:
            for origin in grant_origins:
                try:
                    await browser_ctx.grant_permissions(["microphone"], origin=origin)
                except Exception as e:
                    logger.debug(f"[Base] grant_permissions({origin}) failed: {e}")

        try:
            self.page = page
            # await self._ensure_mouse()

        except Exception as e:
            logger.debug(f"[mouse] init skipped: {e}")

        return browser_ctx

    async def _tz_by_proxy(self, default: str) -> str:
        try:
            async with AsyncSession() as s:
                r = await s.get(
                    url="https://ipapi.co/timezone/",
                    proxy=self.wallet.proxy,
                    timeout=20,
                )
            tz = (r.text or "").strip()
            return tz if tz else default
        except Exception:
            return default

    @staticmethod
    def _parse_proxy_settings(proxy_str: Optional[str]) -> Optional[Dict[str, str]]:
        if not proxy_str:
            return None
        parsed = urlparse(proxy_str)
        server = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        return {
            "server": server,
            "username": parsed.username or "",
            "password": parsed.password or "",
        }

    @staticmethod
    def _sec_ch_ua(brands: List[Dict[str, str]]) -> str:
        if not brands:
            return '"Chromium";v="141", "Google Chrome";v="141", "Not=A?Brand";v="24"'
        return ", ".join([f'"{b.get("brand", "Chromium")}";v="{b.get("version", "141")}"' for b in brands])

    @staticmethod
    def _pick_full_version(uach_meta: Dict[str, Any]) -> str:
        fl = uach_meta.get("fullVersionList") or []
        if fl and isinstance(fl, list) and isinstance(fl[0], dict):
            return fl[0].get("version", "141.0.0.0")
        return uach_meta.get("uaFullVersion", "141.0.0.0")

    # ---------- console/mouse ----------

    async def _ensure_console_pipe(self):
        if self._console_piped or not self.page:
            return
        self._console_piped = True

        def _pipe_console(msg):
            try:
                txt = msg.text
            except Exception:
                txt = ""
            logger.debug(f"[PAGE {msg.type.upper()}] {txt}")

        self.page.on("console", _pipe_console)
        self.page.on("pageerror", lambda e: logger.error(f"[PAGE ERROR] {e}"))

    async def _ensure_mouse(self):
        if not self.page:
            return
        if not self.mouse:
            self.mouse = MouseOverlay(self.page)
            await self.mouse.install()
            await self.mouse.start_idle()

    def _extract_webgl_from_fp(self, fp):
        vendor = None
        renderer = None

        vc = getattr(fp, "videoCard", None)
        if vc:
            if hasattr(vc, "renderer") and hasattr(vc, "vendor"):
                renderer = getattr(vc, "renderer", None)
                vendor = getattr(vc, "vendor", None)
            elif isinstance(vc, dict):
                renderer = vc.get("renderer")
                vendor = vc.get("vendor")

        def _norm(s):
            if not s:
                return s
            s = str(s)
            s = s.replace("Google Inc. )", "Google Inc.)")
            s = s.replace("Google Inc )", "Google Inc)")
            return s.strip()

        vendor = _norm(vendor)
        renderer = _norm(renderer)

        if not vendor or not renderer:
            nav = getattr(fp, "navigator", {}) or {}
            platform = (getattr(nav, "platform", "") or "").lower()
            if "mac" in platform:
                vendor, renderer = "Google Inc.", "ANGLE (Apple, Apple M2)"
            elif "linux" in platform:
                vendor, renderer = (
                    "Google Inc. (Intel)",
                    "ANGLE (Intel, Mesa Intel(R) UHD Graphics)",
                )
            else:
                vendor, renderer = "Google Inc. (AMD)", "ANGLE (AMD, Radeon RX 6600)"

        params = {
            0x0D33: 16384,
            0x0D3A: [16384, 16384],
        }

        return vendor, renderer, params

    def _salt_from_fp(self, fp, vendor: str, renderer: str) -> int:
        # UA сначала из navigator, потом из headers
        ua = ""
        try:
            nav = getattr(fp, "navigator", None) or {}
            ua = getattr(nav, "userAgent", "") or ""
        except Exception:
            pass
        if not ua:
            ua = (getattr(fp, "headers", {}) or {}).get("User-Agent", "") or ""

        src = f"{ua}|{vendor}|{renderer}"
        return int(hashlib.sha256(src.encode("utf-8")).hexdigest()[:8], 16)

    def _webgl_patch_js(self, vendor: str, renderer: str, salt: int, params: dict) -> str:
        payload = json.dumps(
            {"vendor": vendor, "renderer": renderer, "params": params or {}},
            ensure_ascii=False,
        )
        js = r"""
    (() => {
      if (window.__forge_webgl_patched) return;
      Object.defineProperty(window, "__forge_webgl_patched", { value: true });

      const CFG = __PAYLOAD__;
      const SALT = __SALT__;
      const DEBUG="WEBGL_debug_renderer_info", V=0x9245, R=0x9246;
      const PARAMS = CFG.params || {};

      function h32(a0){ let a=a0|0; a+=0x7ed55d16 + (a<<12); a^=0xc761c23c ^ (a>>>19);
        a+=0x165667b1 + (a<<5); a+=0xd3a2646c ^ (a<<9); a+=0xfd7046c5 + (a<<3);
        a^=0xb55a4f09 ^ (a>>>16); return a>>>0; }

      function apply(proto){
        if (!proto) return;
        const ge   = proto.getExtension;
        const gse  = proto.getSupportedExtensions;
        const gp   = proto.getParameter;
        const gspf = proto.getShaderPrecisionFormat;
        const rp   = proto.readPixels;

        // DEBUG extension видим
        if (gse) try {
          Object.defineProperty(proto, "getSupportedExtensions", {
            value: function(){
              const list = (gse.call(this) || []).slice(0);
              if (list.indexOf(DEBUG) === -1) list.push(DEBUG);
              return list;
            },
            configurable: true, writable: true
          });
        } catch(_){}

        // Возвращаем UNMASKED_* всегда
        if (ge) try {
          Object.defineProperty(proto, "getExtension", {
            value: function(name){
              const r = ge.call(this, name);
              if (name === DEBUG) return r || { UNMASKED_VENDOR_WEBGL: V, UNMASKED_RENDERER_WEBGL: R };
              return r;
            },
            configurable: true, writable: true
          });
        } catch(_){}

        // Часто используемые параметры — стабильные/спуфнутые
        if (gp) try {
          Object.defineProperty(proto, "getParameter", {
            value: function(pname){
              if (pname === V) return CFG.vendor;
              if (pname === R) return CFG.renderer;
              if (Object.prototype.hasOwnProperty.call(PARAMS, pname)) return PARAMS[pname];
              try { return gp.call(this, pname); } catch(_){ return null; }
            },
            configurable: true, writable: true
          });
        } catch(_){}

        // Стабильный precision
        if (gspf) try {
          Object.defineProperty(proto, "getShaderPrecisionFormat", {
            value: function(){ return { rangeMin: 127, rangeMax: 127, precision: 23 }; },
            configurable: true, writable: true
          });
        } catch(_){}

        // Главный трюк: ε-noise в readPixels → меняется WebGLHash, но артефактов нет
        if (rp) try {
          Object.defineProperty(proto, "readPixels", {
            value: function(x, y, w, h, format, type, pixels){
              rp.call(this, x, y, w, h, format, type, pixels);
              try {
                if (!pixels || typeof pixels.length !== "number") return;
                const len = pixels.length|0;
                // разрежённый шаг от размера (убедимся, что не слишком часто)
                const step = Math.max(97, (w|0) > 0 ? Math.floor((w*h)/256) : 127);
                for (let i = 0; i < len; i += step) {
                  const n = h32(SALT ^ (i*2246822519) ^ ((w*31 + h*131)>>>0)) & 3; // 0..3
                  const v = pixels[i] | 0;
                  let nv = v + (n % 2 === 0 ? 1 : -1); // ±1
                  pixels[i] = nv < 0 ? 0 : (nv > 255 ? 255 : nv);
                }
              } catch(_){}
            },
            configurable: true, writable: true
          });
        } catch(_){}
      }

      try { apply(WebGLRenderingContext && WebGLRenderingContext.prototype); } catch(_){}
      try { apply(WebGL2RenderingContext && WebGL2RenderingContext.prototype); } catch(_){}

      // alias experimental-webgl → webgl
      try {
        const rw = (proto) => {
          if (!proto) return;
          const _gc = proto.getContext;
          if (!_gc) return;
          Object.defineProperty(proto, "getContext", {
            value: function(type, attrs){
              if (type === "experimental-webgl") type = "webgl";
              return _gc.call(this, type, attrs);
            },
            configurable: true, writable: true
          });
        };
        rw(HTMLCanvasElement && HTMLCanvasElement.prototype);
        rw(OffscreenCanvas && OffscreenCanvas.prototype);
      } catch(_){}
    })();
    """
        return textwrap.dedent(js).replace("__PAYLOAD__", payload).replace("__SALT__", str(int(salt)))

    def _webgl_worker_bootstrap_js(self, vendor: str, renderer: str, salt: int, params: dict) -> str:
        payload = json.dumps(
            {"vendor": vendor, "renderer": renderer, "params": params or {}},
            ensure_ascii=False,
        )
        js = r"""
    (() => {
      if (self.__forge_worker_webgl_patched) return;
      try { Object.defineProperty(self, "__forge_worker_webgl_patched", { value: true }); } catch(_){}
      const CFG = __PAYLOAD__;
      const SALT = __SALT__;
      const DEBUG="WEBGL_debug_renderer_info", V=0x9245, R=0x9246;
      const PARAMS = CFG.params || {};
      function h32(a0){ let a=a0|0; a+=0x7ed55d16 + (a<<12); a^=0xc761c23c ^ (a>>>19);
        a+=0x165667b1 + (a<<5); a+=0xd3a2646c ^ (a<<9); a+=0xfd7046c5 + (a<<3);
        a^=0xb55a4f09 ^ (a>>>16); return a>>>0; }

      function apply(proto){
        if (!proto) return;
        const ge = proto.getExtension, gse = proto.getSupportedExtensions,
              gp = proto.getParameter, gspf = proto.getShaderPrecisionFormat, rp = proto.readPixels;

        if (gse) try { Object.defineProperty(proto, "getSupportedExtensions", { value: function(){
          const l=(gse.call(this)||[]).slice(0); if(l.indexOf(DEBUG)===-1) l.push(DEBUG); return l; }, configurable:true, writable:true }); } catch(_){}
        if (ge) try { Object.defineProperty(proto, "getExtension", { value: function(n){
          const r=ge.call(this,n); if(n===DEBUG) return r||{UNMASKED_VENDOR_WEBGL:V,UNMASKED_RENDERER_WEBGL:R}; return r; }, configurable:true, writable:true }); } catch(_){}
        if (gp) try { Object.defineProperty(proto, "getParameter", { value: function(pn){
          if (pn===V) return CFG.vendor; if (pn===R) return CFG.renderer;
          if (Object.prototype.hasOwnProperty.call(PARAMS, pn)) return PARAMS[pn];
          try{ return gp.call(this,pn); }catch(_){ return null; } }, configurable:true, writable:true }); } catch(_){}
        if (gspf) try { Object.defineProperty(proto, "getShaderPrecisionFormat", { value: function(){ return {rangeMin:127,rangeMax:127,precision:23}; }, configurable:true, writable:true }); } catch(_){}
        if (rp) try { Object.defineProperty(proto, "readPixels", { value: function(x,y,w,h,fmt,typ,pix){
          rp.call(this,x,y,w,h,fmt,typ,pix);
          try{ if(!pix||typeof pix.length!=="number") return; const len=pix.length|0; const step=Math.max(97,(w|0)>0?Math.floor((w*h)/256):127);
            for(let i=0;i<len;i+=step){ const n=h32(SALT ^ (i*2246822519) ^ ((w*31+h*131)>>>0)) & 3; const v=pix[i]|0; let nv=v + (n%2===0?1:-1); pix[i]=nv<0?0:(nv>255?255:nv); } }catch(_){}
        }, configurable:true, writable:true }); } catch(_){}
      }

      try { apply(self.WebGLRenderingContext && WebGLRenderingContext.prototype); } catch(_){}
      try { apply(self.WebGL2RenderingContext && WebGL2RenderingContext.prototype); } catch(_){}
    })();
    """
        return textwrap.dedent(js).replace("__PAYLOAD__", payload).replace("__SALT__", str(int(salt)))

    def _wrap_worker_loader_js(self, injected_code: str) -> str:
        inj_json = json.dumps(injected_code)  # безопасно встраиваем как JS-строку

        js = r"""
    (() => {
      const OrigWorker = self.Worker;
      if (!OrigWorker) return;

      function wrapURL(url){
        // Собираем итоговый код как обычную JS-строку
        const code = __INJECT_JSON__ + "\n;importScripts(" + JSON.stringify(url) + ");";
        const blob = new Blob([code], {type:"application/javascript"});
        return URL.createObjectURL(blob);
      }

      function W(spec, opts){
        try {
          if (opts && String(opts.type).toLowerCase() === "module") {
            // module workers не трогаем
            return new OrigWorker(spec, opts);
          }
          if (typeof spec === "string") {
            return new OrigWorker(wrapURL(spec), opts);
          }
        } catch(_){}
        return new OrigWorker(spec, opts);
      }

      W.prototype = OrigWorker.prototype;
      Object.defineProperty(self, "Worker", { value: W, configurable: true, writable: true });
    })();
    """
        return textwrap.dedent(js).replace("__INJECT_JSON__", inj_json)

    def _srcdoc_injector_js(self, injected_code: str) -> str:
        """Инжекция inline-скрипта в srcdoc/sandbox iframe (origin-safe, canvas-salt shared)."""
        import base64
        import textwrap

        inj_b64 = base64.b64encode(injected_code.encode()).decode()

        js = f"""
        (() => {{
          if (window.__forge_srcdoc_injector__) return;
          Object.defineProperty(window, "__forge_srcdoc_injector__", {{ value: true }});

          // inline-вариант: разворачиваем код прямо в <script> внутри iframe
          const scriptInline = `<script>(()=>{{try{{eval(atob('{inj_b64}'))}}catch(e){{console.error('[SRC-DOC eval]',e)}}}})();<\\/script>`;

          function injectIntoHtml(html) {{
            try {{
              if (/<\\/head>/i.test(html))
                return html.replace(/<\\/head>/i, scriptInline + "</head>");
              if (/<body/i.test(html))
                return html.replace(/<body([^>]*)>/i, `<body$1>` + scriptInline);
              if (/<html/i.test(html))
                return html.replace(/<html([^>]*)>/i, `<html$1><head>` + scriptInline + `</head>`);
              return scriptInline + html;
            }} catch (e) {{
              console.error('[SRC-DOC inject fail]', e);
              return html;
            }}
          }}

          const desc = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, "srcdoc");
          if (desc && desc.set) {{
            Object.defineProperty(HTMLIFrameElement.prototype, "srcdoc", {{
              set(v) {{
                try {{ return desc.set.call(this, injectIntoHtml(String(v || ""))); }}
                catch(_e) {{ return desc.set.call(this, v); }}
              }},
              get: desc.get,
              configurable: true
            }});
          }}

          const origCreate = Document.prototype.createElement;
          Object.defineProperty(Document.prototype, "createElement", {{
            value(tag, opts) {{
              const el = origCreate.call(this, tag, opts);
              if ((tag + "").toLowerCase() === "iframe") {{
                const _setAttr = el.setAttribute;
                el.setAttribute = function(name, value) {{
                  const lname = String(name).toLowerCase();
                  if (lname === "sandbox") {{
                    let val = String(value || "");
                    if (!val.includes("allow-same-origin"))
                      val += " allow-scripts allow-same-origin";
                    return _setAttr.call(this, name, val.trim());
                  }}
                  if (lname === "srcdoc" && typeof value === "string") {{
                    return _setAttr.call(this, name, injectIntoHtml(value));
                  }}
                  return _setAttr.call(this, name, value);
                }};
              }}
              return el;
            }},
            configurable: true,
            writable: true
          }});
        }})();
        """
        return textwrap.dedent(js)

    def _canvas_patch_js(self, *, mode: str, salt: int, step: int = 127, gain: int = 3) -> str:
        cfg = json.dumps(
            {"mode": mode, "salt": int(salt), "step": int(step), "gain": int(gain)},
            ensure_ascii=False,
        )
        js = r"""
    (() => {
      if (window.__forge_canvas_patched) return;
      Object.defineProperty(window, "__forge_canvas_patched", { value: true });

      const CFG = __CFG__;
      const __nm = new WeakMap();
      const toSrc = Function.prototype.toString;
      Object.defineProperty(Function.prototype, "toString", {
        value: function(){ const f = __nm.get(this); return f || toSrc.call(this); },
        configurable: true
      });
      const natFn = (name, fn) => { try{ Object.defineProperty(fn,"name",{value:name}); }catch(_){}
        __nm.set(fn, `function ${name}() { [native code] }`); return fn; };

      function h32(a0){ let a=a0|0; a+=0x7ed55d16 + (a<<12); a^=0xc761c23c ^ (a>>>19);
        a+=0x165667b1 + (a<<5); a+=0xd3a2646c ^ (a<<9); a+=0xfd7046c5 + (a<<3);
        a^=0xb55a4f09 ^ (a>>>16); return a>>>0; }

      function mutate(img){
        if (CFG.mode !== "noise") return img;
        const { data, width, height } = img;
        const STEP = Math.max(61, CFG.step|0);
        const G = Math.max(1, CFG.gain|0);
        let px = 0;
        for (let y=0; y<height; y++){
          for (let x=0; x<width; x++, px++){
            if ((px % STEP) !== 0) continue;
            const i = (px<<2) >>> 0;
            if (data[i+3] === 0) continue;
            const n = h32((CFG.salt ^ (x*374761393 ^ y*668265263))>>>0);
            data[i  ] = (data[i  ] + (n & 3) * G) & 0xff;
            data[i+1] = (data[i+1] + ((n>>>2)&3) * G) & 0xff;
            data[i+2] = (data[i+2] + ((n>>>4)&3) * G) & 0xff;
          }
        }
        return img;
      }

      // 2D: getImageData (HTMLCanvas / Offscreen)
      try {
        const P = self.CanvasRenderingContext2D && CanvasRenderingContext2D.prototype;
        if (P && P.getImageData) {
          const _gid = P.getImageData;
          Object.defineProperty(P, "getImageData", { value: natFn("getImageData", function(...a){
            const img = _gid.apply(this, a);
            try{ return mutate(img); }catch(_){ return img; }
          }), configurable:true, writable:true });
        }
      } catch(_){}
      try {
        const P = self.OffscreenCanvasRenderingContext2D && OffscreenCanvasRenderingContext2D.prototype;
        if (P && P.getImageData) {
          const _gid = P.getImageData;
          Object.defineProperty(P, "getImageData", { value: natFn("getImageData", function(...a){
            const img = _gid.apply(this, a);
            try{ return mutate(img); }catch(_){ return img; }
          }), configurable:true, writable:true });
        }
      } catch(_){}

      // HTMLCanvas: toDataURL / toBlob
      try {
        const HC = self.HTMLCanvasElement && HTMLCanvasElement.prototype;
        if (HC){
          for (const key of ["toDataURL", "toBlob"]) {
            const orig = HC[key]; if (!orig) continue;
            Object.defineProperty(HC, key, { value: natFn(key, function(...a){
              if (CFG.mode !== "noise") return orig.apply(this,a);
              try{
                const w=this.width|0, h=this.height|0;
                const c2=this.ownerDocument?.createElement("canvas"); if(!c2) return orig.apply(this,a);
                c2.width=w; c2.height=h;
                const ctx2=c2.getContext("2d"); ctx2.drawImage(this,0,0);
                const img = ctx2.getImageData(0,0,w,h); mutate(img); ctx2.putImageData(img,0,0);
                return orig.apply(c2,a);
              }catch(_){ return orig.apply(this,a); }
            }), configurable:true, writable:true });
          }
        }
      } catch(_){}

      // OffscreenCanvas: convertToBlob
      try {
        const OC = self.OffscreenCanvas && OffscreenCanvas.prototype;
        if (OC && OC.convertToBlob) {
          const _ctb = OC.convertToBlob;
          Object.defineProperty(OC, "convertToBlob", { value: natFn("convertToBlob", function(...a){
            if (CFG.mode !== "noise") return _ctb.apply(this,a);
            try{
              const w=this.width|0, h=this.height|0;
              const c2=new OffscreenCanvas(w,h);
              const ctx2=c2.getContext("2d"); ctx2.drawImage(this,0,0);
              const img = ctx2.getImageData(0,0,w,h); mutate(img); ctx2.putImageData(img,0,0);
              return _ctb.apply(c2,a);
            }catch(_){ return _ctb.apply(this,a); }
          }), configurable:true, writable:true });
        }
      } catch(_){}

      // ImageBitmapRenderingContext: transferFromImageBitmap
      try {
        const IB = self.ImageBitmapRenderingContext && ImageBitmapRenderingContext.prototype;
        if (IB && IB.transferFromImageBitmap) {
          const orig = IB.transferFromImageBitmap;
          Object.defineProperty(IB, "transferFromImageBitmap", { value: natFn("transferFromImageBitmap", function(bitmap){
            try{
              if (CFG.mode === "noise" && bitmap && self.createImageBitmap && self.OffscreenCanvas) {
                // скопируем bitmap в оффскрин, слегка «пошумим», вернём как обычно
                const w = bitmap.width|0, h = bitmap.height|0;
                const oc = new OffscreenCanvas(w,h);
                const ctx = oc.getContext("2d");
                ctx.drawImage(bitmap,0,0);
                const img = ctx.getImageData(0,0,w,h); mutate(img); ctx.putImageData(img,0,0);
              }
            }catch(_){}
            return orig.call(this, bitmap);
          }), configurable:true, writable:true });
        }
      } catch(_){}
    })();
    """
        return textwrap.dedent(js).replace("__CFG__", cfg)

    def build_nav_init_from_fp(self, fp) -> str:
        """
        Подгружает из fingerprint только мультимедиа-девайсы и батарею.
        """
        import json
        import textwrap

        # --- mediaDevices counts ---
        md = getattr(fp, "multimediaDevices", {}) or {}
        speakers = len(md.get("speakers", []) or [])
        mics = len(md.get("micros", []) or [])
        cams = len(md.get("webcams", []) or [])

        # --- battery ---
        bat = getattr(fp, "battery", None) or {}
        battery_payload = {
            "charging": bool(bat.get("charging", True)),
            "chargingTime": bat.get("chargingTime", 0),
            "dischargingTime": bat.get("dischargingTime"),
            "level": float(bat.get("level", 1.0)),
        }

        payload = {
            "mediaCounts": {"speakers": speakers, "micros": mics, "webcams": cams},
            "battery": battery_payload,
        }

        payload_json = json.dumps(payload, ensure_ascii=False)

        js = r"""
    (() => {
      if (window.__media_battery_patched__) return;
      Object.defineProperty(window, "__media_battery_patched__", { value: true });

      const P = __PAYLOAD__;

      // ---- helpers ----
      const __nm = new WeakMap();
      const __toStr = Function.prototype.toString;
      try {
        Object.defineProperty(Function.prototype, "toString", {
          value: function(){ const f = __nm.get(this); return f || __toStr.call(this); },
          configurable: true
        });
      } catch(_) {}
      const nat = (name, fn) => { try{Object.defineProperty(fn,"name",{value:name})}catch(_){}; __nm.set(fn,`function ${name}() { [native code] }`); return fn; };

      // ---- mediaDevices.enumerateDevices ----
      try {
        const MD = navigator.mediaDevices;
        if (MD) {
          const proto = Object.getPrototypeOf(MD);
          const fake = () => {
            const out = [];
            for (let i=0;i<P.mediaCounts.speakers;i++) out.push({ deviceId:"", kind:"audiooutput", label:"", groupId:"" });
            for (let i=0;i<P.mediaCounts.micros;i++)   out.push({ deviceId:"", kind:"audioinput",  label:"", groupId:"" });
            for (let i=0;i<P.mediaCounts.webcams;i++)  out.push({ deviceId:"", kind:"videoinput",  label:"", groupId:"" });
            return out;
          };
          Object.defineProperty(proto, "enumerateDevices", {
            value: nat("enumerateDevices", function(){ return Promise.resolve(fake()); }),
            configurable:true, writable:true
          });
        }
      } catch(_){}

      // ---- navigator.getBattery ----
      try {
        if (navigator && !navigator.getBatteryPatched) {
          Object.defineProperty(navigator, "getBatteryPatched", { value: true, configurable: false });
          const battery = P.battery || {};
          navigator.getBattery = nat("getBattery", function() {
            return Promise.resolve({
              charging: !!battery.charging,
              chargingTime: battery.chargingTime ?? 0,
              dischargingTime: battery.dischargingTime ?? null,
              level: battery.level ?? 1.0,
              addEventListener(){}, removeEventListener(){}, onchargingchange:null
            });
          });
        }
      } catch(_){}
    })();
    """
        return textwrap.dedent(js).replace("__PAYLOAD__", payload_json)

    def _clientrects_patch_js_stable(self, seed: str, snapshots: dict | None = None, max_jitter_px: float = 0.6) -> str:
        """
        Возвращает JS-инжект, который:
          - deterministic-патчит Element.prototype.getClientRects и getBoundingClientRect;
          - если для селектора есть snapshot в `snapshots` — включает режим replay (возвращает сохранённые rect'ы);
          - иначе — применяет детерминированный, воспроизводимый джиттер (mulberry32) на базе `seed`;
          - делает строгую округлённость до 3 знаков (stability);
          - экспортирует API window.__clientrects_patch_api__ с функцией computeRectsHash(selectors[]) для проверки.

        Аргументы:
          - seed: str — детерминирующий seed (например "wallet:1234").
          - snapshots: dict | None — map selector -> [{x:, y:, width:, height:}, ...]
          - max_jitter_px: float — максимальная амплитуда джиттера в пикселях.

        Использование:
          js = _clientrects_patch_js_stable(self, seed="wallet:42", snapshots={"#logo":[{...}]})
          await page.add_init_script(source=js)  # MUST be before goto
        """
        import json
        import textwrap

        payload = json.dumps(
            {
                "seed": seed or "",
                "snapshots": snapshots or {},
                "max_jitter_px": float(max_jitter_px),
            },
            ensure_ascii=False,
        )
        salt = abs(hash(seed or "")) & 0xFFFFFFFF

        js = r"""
    (() => {
      if (window.__clientrects_patched_stable__) return;
      Object.defineProperty(window, "__clientrects_patched_stable__", { value: true });

      const CFG = __PAYLOAD__;
      const SALT = __SALT__ >>> 0;
      const MAX_JITTER = Number(CFG.max_jitter_px) || 0.6;
      const SNAPSHOTS = CFG.snapshots || {};
      const SEED = String(CFG.seed || "");

      // --- native-looking helpers ---
      const __nm = new WeakMap();
      const __toStr = Function.prototype.toString;
      try {
        Object.defineProperty(Function.prototype, "toString", {
          value: function(){ const f = __nm.get(this); return f || __toStr.call(this); },
          configurable: true
        });
      } catch(_) {}
      const nat = (name, fn) => { try{ Object.defineProperty(fn,"name",{value:name}) }catch(_){}; __nm.set(fn,`function ${name}() { [native code] }`); return fn; };

      // --- stable 32-bit hash (fnv-like) ---
      function h32_str(s) {
        let h = 2166136261 >>> 0;
        for (let i = 0; i < s.length; i++) {
          h ^= s.charCodeAt(i);
          h = Math.imul(h, 16777619) >>> 0;
        }
        return h >>> 0;
      }

      // mulberry32 PRNG seeded by 32-bit int
      function mulberry32(a) {
        return function() {
          a |= 0;
          a = (a + 0x6D2B79F5) | 0;
          let t = Math.imul(a ^ (a >>> 15), 1 | a);
          t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
          return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
      }

      // deterministic jitter in [-max_px, +max_px] using seed+key
      function deterministic_jitter(seed, key, max_px) {
        const h = h32_str(seed + '|' + key + '|' + String(SALT));
        const rnd = mulberry32(h)();
        return (rnd * 2 - 1) * max_px;
      }

      // make DOMRect with consistent fields & rounding to 3 decimals
      function makeRect(x, y, w, h) {
        const rx = Math.round(x * 1000) / 1000;
        const ry = Math.round(y * 1000) / 1000;
        const rw = Math.round(w * 1000) / 1000;
        const rh = Math.round(h * 1000) / 1000;
        try {
          return new DOMRect(rx, ry, rw, rh);
        } catch(_) {
          return { x: rx, y: ry, width: rw, height: rh, top: ry, left: rx, right: rx + rw, bottom: ry + rh };
        }
      }

      // find snapshot by matching element to any provided selector (first match)
      function findSnapshotForElement(el) {
        try {
          for (const sel in SNAPSHOTS) {
            if (!sel) continue;
            try {
              if (el.matches && el.matches(sel)) return SNAPSHOTS[sel];
            } catch(_) { /* skip invalid selector */ }
          }
        } catch(_) {}
        return null;
      }

      // helpers to convert snapshot entries to DOMRect-like
      function rectFromSnapshotEntry(s) {
        const x = Number(s.x || s.left || 0) || 0;
        const y = Number(s.y || s.top || 0) || 0;
        const w = Number(s.width || s.w || (s.right - s.left) || 0) || 0;
        const h = Number(s.height || s.h || (s.bottom - s.top) || 0) || 0;
        return makeRect(x, y, w, h);
      }

      // save originals
      const _orig_getCR = Element.prototype.getClientRects;
      const _orig_getBB = Element.prototype.getBoundingClientRect;

      // override getClientRects
      Element.prototype.getClientRects = nat("getClientRects", function() {
        try {
          const snap = findSnapshotForElement(this);
          if (snap && Array.isArray(snap) && snap.length > 0) {
            const out = [];
            for (let i = 0; i < snap.length; i++) {
              out.push(rectFromSnapshotEntry(snap[i]));
            }
            // make array-like
            const arr = Object.create(Array.prototype);
            out.forEach((v, idx) => Object.defineProperty(arr, String(idx), { value: v, enumerable: true }));
            Object.defineProperty(arr, "length", { value: out.length, enumerable: false });
            arr.item = function(i){ return this[String(i)] || null; };
            return arr;
          }

          const rects = _orig_getCR.apply(this, arguments);
          if (!rects || rects.length === 0) return rects;

          // Prefer explicit stable key attribute, else fallback to tag+class (no innerText)
          const elKey = (this.getAttribute && this.getAttribute('data-fp-key')) ?
            this.getAttribute('data-fp-key') :
            ((this.tagName || '') + '::' + (this.className || '').toString().split(/\s+/).slice(0,3).join('.'));

          const baseSeed = (SEED || '') + '::' + elKey;

          const out = [];
          for (let i = 0; i < rects.length; i++) {
            const r = rects[i];
            const ox = Number(r.x || r.left || 0);
            const oy = Number(r.y || r.top || 0);
            const ow = Number(r.width || (r.right - r.left) || 0);
            const oh = Number(r.height || (r.bottom - r.top) || 0);

            const jw = deterministic_jitter(baseSeed, 'w:' + i, MAX_JITTER);
            const jh = deterministic_jitter(baseSeed, 'h:' + i, MAX_JITTER / 2);
            const jx = deterministic_jitter(baseSeed, 'x:' + i, MAX_JITTER / 3);
            const jy = deterministic_jitter(baseSeed, 'y:' + i, MAX_JITTER / 3);

            const nx = Math.max(0, ox + jx);
            const ny = Math.max(0, oy + jy);
            const nw = Math.max(0, ow + jw);
            const nh = Math.max(0, oh + jh);

            out.push(makeRect(nx, ny, nw, nh));
          }

          const arr = Object.create(rects.__proto__ || Array.prototype);
          out.forEach((v, idx) => Object.defineProperty(arr, String(idx), { value: v, enumerable: true }));
          Object.defineProperty(arr, "length", { value: out.length, enumerable: false });
          arr.item = function(i){ return this[String(i)] || null; };
          return arr;
        } catch (e) {
          try { return _orig_getCR.apply(this, arguments); } catch(_) { return []; }
        }
      });

      // override getBoundingClientRect
      Element.prototype.getBoundingClientRect = nat("getBoundingClientRect", function() {
        try {
          const snap = findSnapshotForElement(this);
          if (snap && Array.isArray(snap) && snap.length > 0) {
            const s = snap[0];
            return rectFromSnapshotEntry(s);
          }

          const r = _orig_getBB.apply(this, arguments);

          const elKey = (this.getAttribute && this.getAttribute('data-fp-key')) ?
            this.getAttribute('data-fp-key') :
            ((this.tagName || '') + '::' + (this.className || '').toString().split(/\s+/).slice(0,3).join('.'));

          const baseSeed = (SEED || '') + '::' + elKey + '::bb';

          const ox = Number(r.x || r.left || 0);
          const oy = Number(r.y || r.top || 0);
          const ow = Number(r.width || (r.right - r.left) || 0);
          const oh = Number(r.height || (r.bottom - r.top) || 0);

          const jw = deterministic_jitter(baseSeed, 'w', MAX_JITTER);
          const jh = deterministic_jitter(baseSeed, 'h', MAX_JITTER / 2);
          const jx = deterministic_jitter(baseSeed, 'x', MAX_JITTER / 3);
          const jy = deterministic_jitter(baseSeed, 'y', MAX_JITTER / 3);

          const nx = Math.max(0, ox + jx);
          const ny = Math.max(0, oy + jy);
          const nw = Math.max(0, ow + jw);
          const nh = Math.max(0, oh + jh);

          return makeRect(nx, ny, nw, nh);
        } catch (e) {
          try { return _orig_getBB.apply(this, arguments); } catch(_) { return makeRect(0,0,0,0); }
        }
      });

      // compute simple fnv-like hash for given selectors (returns hex string)
      function computeRectsHash(selectors) {
        try {
          let h = 2166136261 >>> 0;
          const sels = Array.isArray(selectors) ? selectors : [String(selectors || '')];
          for (const sel of sels) {
            try {
              const el = document.querySelector(sel);
              if (!el) continue;
              const rects = el.getClientRects();
              for (let i = 0; i < (rects.length || 0); i++) {
                const r = rects[i];
                const s = `${sel}|${i}|${(r.x||r.left||0).toFixed(3)}|${(r.y||r.top||0).toFixed(3)}|${(r.width||r.width||0).toFixed(3)}|${(r.height||r.height||0).toFixed(3)}`;
                for (let j = 0; j < s.length; j++) {
                  h ^= s.charCodeAt(j);
                  h = Math.imul(h, 16777619) >>> 0;
                }
              }
            } catch(_) {}
          }
          return ('00000000' + (h >>> 0).toString(16)).slice(-8);
        } catch(e) {
          return null;
        }
      }

      // expose runtime API
      try {
        Object.defineProperty(window, "__clientrects_patch_api__", {
          value: {
            seed: SEED,
            salt: SALT >>> 0,
            max_jitter_px: MAX_JITTER,
            snapshots: SNAPSHOTS,
            computeRectsHash: computeRectsHash
          },
          configurable: false
        });
      } catch(_) {}

    })();
    """
        return textwrap.dedent(js).replace("__PAYLOAD__", payload).replace("__SALT__", str(int(salt)))

    def _audio_stable_patch_js(self, seed: str | None = None, params: dict | None = None) -> str:
        """
        JS-инжект:
          1) Детерминированный ε-noise для аудио-хеша (OfflineAudioContext, AnalyserNode, decodeAudioData, createBuffer).
          2) SpeechSynthesis "unblock": getVoices() возвращает стабильный набор, dispatchEvent('voiceschanged'),
             speak() делает no-op с корректными событиями; speaking/pending флаги ведут себя правдоподобно.
          3) Безошибочный resume(): AudioContext/OfflineAudioContext.resume отрабатывает даже без user gesture.
        """
        import json
        import textwrap

        p = params or {}
        payload = {
            "seed": seed or "",
            "params": {
                "noise_level": float(p.get("noise_level", 1e-5)),
                "step": int(p.get("step", 128)),
                "channels": p.get("channels", "all"),
            },
            # голоса, которые отдаст speechSynthesis.getVoices()
            "voices": p.get("voices")
            or [
                {
                    "name": "Milena",
                    "lang": "ru-RU",
                    "default": True,
                    "localService": True,
                    "voiceURI": "Milena_ru-RU",
                },
                {
                    "name": "Google US English",
                    "lang": "en-US",
                    "default": False,
                    "localService": True,
                    "voiceURI": "en-US",
                },
            ],
            # длительность синтеза (фиктивная), мс
            "speak_duration_ms": int(p.get("speak_duration_ms", 80)),
        }
        payload_json = json.dumps(payload, ensure_ascii=False)
        salt = abs(hash(seed or "")) & 0xFFFFFFFF

        js = r"""
    (() => {
      if (window.__audio_stable_patch__) return;
      Object.defineProperty(window, "__audio_stable_patch__", { value: true });

      const CFG = __PAYLOAD__;
      const SALT = (__SALT__>>>0);
      const PARAMS = CFG.params || {};
      const NOISE_LEVEL = Number(PARAMS.noise_level) || 1e-5;
      const STEP = Math.max(1, parseInt(PARAMS.step) || 128);
      const CHANNELS = (PARAMS.channels || "all").toLowerCase();
      const SEED = String(CFG.seed || "");
      const VOICES = Array.isArray(CFG.voices) ? CFG.voices.slice() : [];
      const SPEAK_MS = Math.max(20, (CFG.speak_duration_ms|0) || 80);

      // ----- native-looking helpers -----
      const __nm = new WeakMap();
      const __toStr = Function.prototype.toString;
      try { Object.defineProperty(Function.prototype, "toString", {
        value: function(){ const f = __nm.get(this); return f || __toStr.call(this); }, configurable:true
      }); } catch(_) {}
      const nat = (name, fn) => { try{Object.defineProperty(fn,"name",{value:name})}catch(_){}; __nm.set(fn,`function ${name}() { [native code] }`); return fn; };

      // --- deterministic PRNG ---
      function h32str(s) {
        let h = 2166136261 >>> 0;
        for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
        return h >>> 0;
      }
      function mulberry32(a){ return function(){ a|=0; a=(a+0x6D2B79F5)|0; let t=Math.imul(a^(a>>>15),1|a); t=(t+Math.imul(t^(t>>>7),61|t))^t; return ((t^(t>>>14))>>>0)/4294967296; } }
      function detUnit(seed, idx){ const h=h32str(seed+'|'+idx+'|'+SALT); return mulberry32(h)()*2-1; }

      // --- ε-noise applicator ---
      function applyNoiseToChannel(f32, baseSeed, chIndex){
        try{
          const len = f32.length|0;
          for (let i=0;i<len;i+=STEP){
            const jitter = detUnit(baseSeed+'|c'+chIndex, i) * NOISE_LEVEL;
            let nv = f32[i] + jitter;
            if (nv > 1.0) nv = 1.0; else if (nv < -1.0) nv = -1.0;
            f32[i] = nv;
          }
        }catch(_){}
      }

      // --- Patch AudioContext.resume(): resolve even if NotAllowedError ---
      (function patchResume(){
        for (const Ctor of [window.AudioContext, window.webkitAudioContext, window.OfflineAudioContext, window.webkitOfflineAudioContext]) {
          try{
            if (!Ctor || !Ctor.prototype || !Ctor.prototype.resume) continue;
            const orig = Ctor.prototype.resume;
            Object.defineProperty(Ctor.prototype, "resume", {
              value: nat("resume", function(){
                try {
                  const p = orig.apply(this, arguments);
                  if (p && typeof p.then === "function") {
                    return p.catch(() => Promise.resolve()); // сгладить NotAllowedError без жеста
                  }
                } catch(_) {}
                return Promise.resolve();
              }),
              configurable: true, writable: true
            });
          }catch(_){}
        }
      })();

      // --- Patch: deterministic noise on rendered/decoded buffers & analyser reads ---
      (function patchAudioNoise(){
        // OfflineAudioContext.startRendering
        try{
          const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
          if (OAC && OAC.prototype && OAC.prototype.startRendering) {
            const orig = OAC.prototype.startRendering;
            Object.defineProperty(OAC.prototype, "startRendering", {
              value: nat("startRendering", function(){
                const pr = orig.apply(this, arguments);
                return pr.then((buf) => {
                  try {
                    const base = (SEED||"")+"::offline::"+String(buf.length||0)+"::"+String(buf.sampleRate||44100);
                    const channels = (CHANNELS === "first") ? [0] : Array.from({length: buf.numberOfChannels}, (_,i)=>i);
                    for (const ch of channels) {
                      try { applyNoiseToChannel(buf.getChannelData(ch), base, ch); } catch(_){}
                    }
                  }catch(_){}
                  return buf;
                });
              }),
              configurable:true, writable:true
            });
          }
        }catch(_){}

        // AudioContext.decodeAudioData
        try{
          const AC = window.AudioContext || window.webkitAudioContext;
          if (AC && AC.prototype && AC.prototype.decodeAudioData) {
            const orig = AC.prototype.decodeAudioData;
            Object.defineProperty(AC.prototype, "decodeAudioData", {
              value: nat("decodeAudioData", function(){
                const res = orig.apply(this, arguments);
                if (res && typeof res.then === "function") {
                  return res.then((buf) => {
                    try {
                      const base = (SEED||"")+"::decode::"+String(buf.length||0)+"::"+String(buf.sampleRate||44100);
                      const channels = (CHANNELS === "first") ? [0] : Array.from({length: buf.numberOfChannels}, (_,i)=>i);
                      for (const ch of channels) {
                        try { applyNoiseToChannel(buf.getChannelData(ch), base, ch); } catch(_){}
                      }
                    }catch(_){}
                    return buf;
                  });
                }
                return res;
              }),
              configurable:true, writable:true
            });
          }
        }catch(_){}

        // AnalyserNode getFloatTimeDomainData / getByteTimeDomainData (ε-noise на выдачу)
        try{
          const ANP = window.AnalyserNode && AnalyserNode.prototype;
          if (ANP && ANP.getFloatTimeDomainData) {
            const origF = ANP.getFloatTimeDomainData;
            ANP.getFloatTimeDomainData = nat("getFloatTimeDomainData", function(arr){
              const rv = origF.apply(this, arguments);
              try {
                const base = (SEED||"")+"::analyser::"+String(arr.length||0);
                applyNoiseToChannel(arr, base, 0);
              } catch(_) {}
              return rv;
            });
          }
          if (ANP && ANP.getByteTimeDomainData) {
            const origB = ANP.getByteTimeDomainData;
            ANP.getByteTimeDomainData = nat("getByteTimeDomainData", function(arr){
              const rv = origB.apply(this, arguments);
              try {
                const tmp = new Float32Array(arr.length);
                for (let i=0;i<arr.length;i++) tmp[i] = (arr[i]-128)/128;
                const base = (SEED||"")+"::analyser_byte::"+String(arr.length||0);
                applyNoiseToChannel(tmp, base, 0);
                for (let i=0;i<arr.length;i++) {
                  let v = Math.round(tmp[i]*128 + 128);
                  if (v<0) v=0; else if (v>255) v=255;
                  arr[i] = v;
                }
              }catch(_){}
              return rv;
            });
          }
        }catch(_){}
      })();

      // --- SpeechSynthesis unblock/mocks ---
      (function patchSpeech(){
        if (!("speechSynthesis" in window)) return;

        // Voice constructor-like (Illegal constructor в нативе, делаем через прототип)
        function makeVoice(desc){
          const v = Object.create(window.SpeechSynthesisVoice ? SpeechSynthesisVoice.prototype : {});
          const safe = (k, val) => Object.defineProperty(v, k, { get: nat("get "+k, function(){ return val; }), enumerable:true, configurable:true });
          safe("voiceURI", String(desc.voiceURI||desc.name||""));
          safe("name", String(desc.name||""));
          safe("lang", String(desc.lang||"en-US"));
          safe("localService", !!desc.localService);
          safe("default", !!desc.default);
          return v;
        }

        const voicesList = VOICES.map(makeVoice);
        let fired = false;

        // getVoices: сразу отдаём список, без "первого пустого" (чтобы не было blocked)
        const origGetVoices = window.speechSynthesis.getVoices ? window.speechSynthesis.getVoices.bind(window.speechSynthesis) : null;
        window.speechSynthesis.getVoices = nat("getVoices", function(){
          try { return voicesList.slice(); } catch(_) { return []; }
        });

        // Сразу сгенерим событие voiceschanged (некоторые скрипты ждут его)
        const fireVoices = () => {
          if (fired) return;
          try {
            const ev = new Event("voiceschanged");
            window.speechSynthesis.dispatchEvent ? window.speechSynthesis.dispatchEvent(ev) :
              (window.onvoiceschanged && window.onvoiceschanged(ev));
          } catch(_) {}
          fired = true;
        };
        try { if (document.readyState === "complete") fireVoices(); else window.addEventListener("load", () => setTimeout(fireVoices, 0), { once: true }); } catch(_){}

        // speak(): имитация стабильной работы без реального звука
        // поддерживаем speaking/pending/paused флаги и события onstart/onend/onerror
        let _speaking = false, _pending = false, _paused = false;

        const setFlag = (key, val) => {
          try { Object.defineProperty(window.speechSynthesis, key, { get: nat("get "+key, ()=>val), configurable:true }); } catch(_) {}
        };
        setFlag("speaking", false);
        setFlag("pending", false);
        setFlag("paused", false);

        const origSpeak = window.speechSynthesis.speak ? window.speechSynthesis.speak.bind(window.speechSynthesis) : null;
        window.speechSynthesis.speak = nat("speak", function(utter){
          fireVoices();
          _pending = true; setFlag("pending", true);
          try {
            const evStart = new Event("start");
            setTimeout(() => {
              _pending = false; setFlag("pending", false);
              _speaking = true; setFlag("speaking", true);
              try { utter && typeof utter.onstart === "function" && utter.onstart(evStart); } catch(_){}
            }, 0);

            setTimeout(() => {
              const evEnd = new Event("end");
              _speaking = false; setFlag("speaking", false);
              try { utter && typeof utter.onend === "function" && utter.onend(evEnd); } catch(_){}
            }, SPEAK_MS);
          } catch(_) {}
        });

        // cancel(), pause(), resume() — безошибочные заглушки
        window.speechSynthesis.cancel = nat("cancel", function(){ _speaking=false; _pending=false; _paused=false; setFlag("speaking", false); setFlag("pending", false); setFlag("paused", false); });
        window.speechSynthesis.pause  = nat("pause",  function(){ if (_speaking) { _paused=true; setFlag("paused", true); } });
        window.speechSynthesis.resume = nat("resume", function(){ if (_paused)  { _paused=false; setFlag("paused", false); } });
      })();

      // Экспорт небольшой debug-API
      try {
        Object.defineProperty(window, "__audio_stable_patch_api__", {
          value: { seed: SEED, salt: SALT>>>0, noise_level: NOISE_LEVEL, step: STEP, channels: CHANNELS, voices: VOICES, speak_ms: SPEAK_MS },
          configurable: false
        });
      } catch(_){}
    })();
    """
        return textwrap.dedent(js).replace("__PAYLOAD__", payload_json).replace("__SALT__", str(int(salt)))
