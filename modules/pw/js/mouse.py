import asyncio
import math
import random
from contextlib import asynccontextmanager
from typing import Optional, Tuple

from patchright._impl._errors import TargetClosedError

# === JS-оверлей курсора (один раз на страницу) ===
MOUSE_OVERLAY_JS = r"""
(() => {
  if (window.__human_cursor__) return;

  // --- базовый курсор ---
  const cursor = document.createElement("div");
  Object.assign(cursor.style, {
    width: "16px",
    height: "16px",
    border: "2px solid #ff4444",
    boxShadow: "0 0 6px rgba(255,68,68,0.6)",
    borderRadius: "50%",
    position: "fixed",
    top: "0px",
    left: "0px",
    zIndex: "2147483647",
    pointerEvents: "none",
    transition: "transform 0.08s ease-out, background 0.08s ease-out",
    background: "transparent",
    mixBlendMode: "normal",
  });
  document.documentElement.appendChild(cursor);

  // --- контейнер для хвоста ---
  const trailHost = document.createElement("div");
  Object.assign(trailHost.style, {
    position: "fixed",
    left: "0",
    top: "0",
    width: "0",
    height: "0",
    zIndex: "2147483647",
    pointerEvents: "none",
    contain: "layout style size paint",
  });
  document.documentElement.appendChild(trailHost);

  // --- параметры хвоста (по умолчанию «заметно») ---
  let TRAIL_ENABLED = true;
  let TRAIL_COUNT = 36;          // было 18
  let TRAIL_FADE_MS = 700;       // было 420
  let TRAIL_SPAWN_EVERY_MS = 12; // было 22 (чаще)
  let TRAIL_BASE_SIZE = 10;      // px

  // --- пул точек хвоста ---
  const TRAIL = [];
  function buildTrailPool() {
    // очистим старое
    for (const d of TRAIL) {
      try { clearTimeout(d.__t); } catch {}
      d.remove();
    }
    TRAIL.length = 0;

    for (let i = 0; i < TRAIL_COUNT; i++) {
      const dot = document.createElement("div");
      Object.assign(dot.style, {
        position: "fixed",
        width: TRAIL_BASE_SIZE + "px",
        height: TRAIL_BASE_SIZE + "px",
        marginLeft: -(TRAIL_BASE_SIZE / 2) + "px",
        marginTop: -(TRAIL_BASE_SIZE / 2) + "px",
        borderRadius: "9999px",
        background: "rgba(255,68,68,0.45)",
        boxShadow: "0 0 10px rgba(255,68,68,0.45)",
        opacity: "0",
        transform: "translate3d(0,0,0) scale(1)",
        transition: `opacity ${TRAIL_FADE_MS}ms ease, transform ${TRAIL_FADE_MS}ms ease`,
        pointerEvents: "none",
        willChange: "transform, opacity",
        mixBlendMode: "normal", // можно 'screen' если фон тёмный
      });
      dot.__free = true;
      TRAIL.push(dot);
      trailHost.appendChild(dot);
    }
  }
  buildTrailPool();

  let lastSpawn = 0;
  function spawnTrail(x, y) {
    if (!TRAIL_ENABLED) return;
    const now = performance.now();
    if (now - lastSpawn < TRAIL_SPAWN_EVERY_MS) return;
    lastSpawn = now;

    const dot = TRAIL.find(d => d.__free) || TRAIL[0];
    dot.__free = false;

    dot.style.left = x + "px";
    dot.style.top = y + "px";

    // лёгкая вариативность размера/яркости
    const scale = 0.85 + Math.random() * 0.5;
    const alpha = 0.28 + Math.random() * 0.24;

    dot.style.transition = "none";
    dot.style.opacity = "1";
    dot.style.transform = `translate3d(0,0,0) scale(${scale})`;
    dot.style.background = `rgba(255,68,68,${alpha})`;
    dot.style.boxShadow = `0 0 10px rgba(255,68,68,${alpha})`;

    // «схлопывание» и затухание
    requestAnimationFrame(() => {
      dot.style.transition = `opacity ${TRAIL_FADE_MS}ms ease, transform ${TRAIL_FADE_MS}ms ease`;
      dot.style.opacity = "0";
      dot.style.transform = `translate3d(0,0,0) scale(${0.35 + Math.random()*0.2})`;
      clearTimeout(dot.__t);
      dot.__t = setTimeout(() => { dot.__free = true; }, TRAIL_FADE_MS + 40);
    });
  }

  // --- API курсора ---
  let posX = 8, posY = 8;
  const api = {
    move(x, y) {
      posX = x; posY = y;
      cursor.style.left = (x - 8) + "px";
      cursor.style.top  = (y - 8) + "px";
      spawnTrail(x, y);
    },
    down() {
      cursor.style.transform = "scale(0.78)";
      cursor.style.background = "rgba(255,68,68,0.25)";
    },
    up() {
      cursor.style.transform = "scale(1)";
      cursor.style.background = "transparent";
    },
    getPos() { return { x: posX, y: posY }; },
    setVisible(v) {
      cursor.style.display = v ? "block" : "none";
      trailHost.style.display = v ? "block" : "none";
    },
    // управление шлейфом из Python при желании
    setTrail(enabled, opts) {
      TRAIL_ENABLED = !!enabled;
      if (opts && typeof opts === "object") {
        if (Number.isFinite(opts.count)) TRAIL_COUNT = Math.max(8, opts.count|0);
        if (Number.isFinite(opts.fadeMs)) TRAIL_FADE_MS = Math.max(80, opts.fadeMs|0);
        if (Number.isFinite(opts.spawnEveryMs)) TRAIL_SPAWN_EVERY_MS = Math.max(1, opts.spawnEveryMs|0);
        if (Number.isFinite(opts.size)) TRAIL_BASE_SIZE = Math.max(4, opts.size|0);
        buildTrailPool();
      }
    }
  };

  window.__human_cursor__ = api;

  // стартовая позиция — центр
  const cx = window.innerWidth / 2, cy = window.innerHeight / 2;
  api.move(cx, cy);

  document.addEventListener("visibilitychange", () => {
    api.setVisible(!document.hidden);
  });
})();
"""


class MouseOverlay:
    """
    Визуальный «человеческий» курсор с реальными кликами (user gesture).

    Основные методы:
      - install(): инжект визуального курсора
      - move_to_locator()/move_to_point(): плавное наведение
      - hover(locator): навёлся + микро-джиттер
      - click(locator): дефолт — железный клик (page.mouse), даёт userActivation
      - click_js(locator): Fallback — синтетические DOM-события (не всегда котируются)
      - move_and_click(locator, js=False): комбо

    Доп. возможности:
      - start_idle()/stop_idle(): «дыхание» курсора вне активных действий
      - настройки скорости/джиттера/overshoot и т.п.
    """

    def __init__(
        self,
        page,
        *,
        speed_px_s: Tuple[int, int] = (900, 1400),  # диапазон «скорости человека»
        step_px: Tuple[int, int] = (6, 12),  # средний шаг (px)
        jitter_px: Tuple[float, float] = (0.0, 0.9),  # лёгкая тряска траектории
        overshoot_px: Tuple[int, int] = (1, 4),  # «перелёт» мимо цели
        overshoot_prob: float = 0.65,  # не всегда перелетаем
        micro_pause_ms: Tuple[int, int] = (0, 90),  # микро-паузы при движении
        idle_jitter_px: Tuple[float, float] = (0.6, 1.8),
        idle_period_s: Tuple[float, float] = (0.5, 1.3),
        idle_move_cm: Tuple[float, float] = (1.0, 2.0),  # шаг «перекладки» руки (см)
        idle_dwell_s: Tuple[float, float] = (
            1.5,
            4.0,
        ),  # сколько «стоять» после перемещения
        idle_pause_between_moves_s: Tuple[float, float] = (
            4.0,
            10.0,
        ),  # пауза перед след. перекладкой
        idle_micro_px: Tuple[float, float] = (
            0.15,
            0.6,
        ),  # микро-дрожь во время стоянки (px)
        idle_micro_period_s: Tuple[float, float] = (0.35, 0.9),  # период «дыхания»
        idle_wander_prob: float = 0.55,  # вероятность вообще сдвинуться со стоянки
        screen_ppi: float = 96.0,  # оценочный PPI (96≈1 CSS px/дюйм)
        **kwargs,
    ):
        self.page = page
        self.speed_px_s = speed_px_s
        self.step_px = step_px
        self.jitter_px = jitter_px
        self.overshoot_px = overshoot_px
        self.overshoot_prob = overshoot_prob
        self.micro_pause_ms = micro_pause_ms
        self._idle_jitter_px = idle_jitter_px
        self._idle_period_s = idle_period_s
        self._idle_task: Optional[asyncio.Task] = None
        self._idle_enabled = False
        self._busy = 0  # счётчик «занятости» — чтобы idle не мешал
        self._idle_move_cm = idle_move_cm
        self._idle_dwell_s = idle_dwell_s
        self._idle_pause_between_moves_s = idle_pause_between_moves_s
        self._idle_micro_px = idle_micro_px
        self._idle_micro_period_s = idle_micro_period_s
        self._idle_wander_prob = idle_wander_prob
        self._ppi = screen_ppi

    # ---------- public API ----------

    async def install(self):
        await self.page.add_init_script(MOUSE_OVERLAY_JS)
        await self.page.evaluate(MOUSE_OVERLAY_JS)

    async def move_to_point(self, x: float, y: float):
        async with self._busy_section():
            cx, cy = await self._get_pos()
            await self._human_move(cx, cy, x, y)

    async def move_to_locator(self, locator):
        async with self._busy_section():
            await locator.scroll_into_view_if_needed()
            box = await locator.bounding_box()
            if not box:
                await locator.wait_for(state="visible", timeout=30_000)
                box = await locator.bounding_box()
                if not box:
                    raise RuntimeError("Locator has no bounding box")
            target_x = box["x"] + box["width"] / 2
            target_y = box["y"] + box["height"] / 2
            await self.move_to_point(target_x, target_y)

    async def hover(self, locator):
        await self.move_to_locator(locator)
        await asyncio.sleep(random.uniform(0.05, 0.18))
        await self._nudge()

    async def click(
        self, locator, *, delay_after_down: Tuple[float, float] = (0.04, 0.12)
    ):
        """Дефолт: железный клик, который даёт user gesture (рекомендуется)."""
        return await self.click_hardware(locator, delay_after_down=delay_after_down)

    async def click_hardware(
        self, locator, *, delay_after_down: Tuple[float, float] = (0.04, 0.12)
    ):
        """
        Реальный «железный» клик по центру локатора:
          - плавно наводимся
          - визуально нажимаем
          - page.mouse.move/down/up (userActivation)
        """
        async with self._busy_section():
            await self.move_to_locator(locator)

            # Actionability-проверка (не кликает, просто валидирует доступность)
            try:
                await locator.click(trial=True, timeout=5_000)
            except Exception:
                pass

            box = await locator.bounding_box()
            if not box:
                raise RuntimeError("Locator has no bounding box for click_hardware()")

            x = box["x"] + box["width"] / 2
            y = box["y"] + box["height"] / 2

            # визуальный «палец вниз»
            await self._down()
            await asyncio.sleep(random.uniform(*delay_after_down))

            # реальный клик мышью (ВАЖНО: page.mouse, координаты главного фрейма)
            await self.page.mouse.move(x, y)
            await self.page.mouse.down(button="left")
            await self.page.mouse.up(button="left")

            await self._up()

            # (опционально) можно вернуть диагностику userActivation
            # ua = await self.page.evaluate("() => !!(navigator.userActivation && navigator.userActivation.isActive)")
            # return {"x": x, "y": y, "userActivation": ua}

    async def click_js(
        self,
        locator,
        *,
        delay_after_down: Tuple[float, float] = (0.04, 0.12),
        button: str = "left",
    ) -> None:
        """
        Fallback: JS-клик с диспатчем Pointer/Mouse событий.
        НЕ всегда даёт user gesture; использовать только при необходимости.
        """
        async with self._busy_section():
            await self.move_to_locator(locator)
            await locator.wait_for(state="visible", timeout=30_000)

            box = await locator.bounding_box()
            if not box:
                raise RuntimeError("Locator has no bounding box for click_js()")

            cx = box["x"] + box["width"] / 2
            cy = box["y"] + box["height"] / 2

            await self._down()
            await asyncio.sleep(random.uniform(*delay_after_down))

            await locator.evaluate(
                """
                (el, args) => {
                  const {cx, cy, button} = args;
                  if (!el) return;
                  try { el.focus({preventScroll: true}); } catch (e) {}
                  const btn = button === 'left' ? 0 : (button === 'middle' ? 1 : 2);
                  const common = {
                    bubbles: true, cancelable: true, composed: true,
                    clientX: cx, clientY: cy, button: btn, buttons: 1,
                  };
                  const fire = (type, init) => {
                    try { const C = type.startsWith('pointer') ? PointerEvent : MouseEvent;
                          el.dispatchEvent(new C(type, init)); } catch(e){}
                  };
                  fire('pointerover', common);  fire('pointerenter', common);
                  fire('mouseover', common);    fire('mouseenter', common);
                  fire('pointerdown', common);  fire('mousedown', common);
                  try { el.focus({preventScroll: true}); } catch (e) {}
                  fire('pointerup', common);    fire('mouseup', common);
                  fire('click', common);
                  if (typeof el.click === 'function') { try { el.click(); } catch (e) {} }
                }
                """,
                {"cx": float(cx), "cy": float(cy), "button": button},
            )

            await self._up()

    async def _click_native_locked(self, locator, *, delay_after_down=(0.04, 0.12)):
        box = await locator.bounding_box()
        if not box:
            await locator.wait_for(state="visible", timeout=30_000)
            box = await locator.bounding_box()
            if not box:
                raise RuntimeError("No bbox for click_native")
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2

        await self._move(cx, cy)  # ← курсор ровно в центре
        await asyncio.sleep(0.03)
        await self._down()
        await asyncio.sleep(random.uniform(*delay_after_down))
        await self.page.mouse.move(cx, cy)
        await self.page.mouse.down()
        await self.page.mouse.up()
        await self._up()

    async def move_and_click(self, locator, js: bool = False):
        async with self._busy_section():
            await self.move_to_locator(locator)
            if js:
                await self.click_js(locator)
            else:
                await self.click_hardware(locator)

    # ---- idle jitter control ----
    async def start_idle(self):
        """Запускает фоновое «дыхание» курсора."""
        if self._idle_task and not self._idle_task.done():
            self._idle_enabled = True
            return
        self._idle_enabled = True
        self._idle_task = asyncio.create_task(self._idle_loop(), name="mouse_idle")

    async def stop_idle(self):
        """Останавливает фоновое «дыхание» курсора."""
        self._idle_enabled = False
        t = self._idle_task
        self._idle_task = None
        if t and not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    def set_idle_style(self, *, calm: bool | None = None, precise: bool | None = None):
        """Быстрый тюнинг поведения idle."""
        if calm is True:
            self._idle_wander_prob = 0.35
            self._idle_dwell_s = (2.5, 5.5)
            self._idle_pause_between_moves_s = (6.0, 14.0)
            self._idle_micro_px = (0.12, 0.4)
        if precise is True:
            self.jitter_px = (0.0, 0.6)
            self.overshoot_px = (1, 4)
            self.overshoot_prob = 0.45

    # ---------- internals ----------

    # async def ensure_ready(self):
    #     """Убедиться, что __human_cursor__ реально существует в текущем документе."""
    #     # повторная инициализация JS (на случай, если document поменялся)
    #     await self.page.evaluate(
    #         "(() => { if (!window.__human_cursor__) { %s } })();" % MOUSE_OVERLAY_JS
    #     )
    #     ok = await self.page.evaluate("() => !!window.__human_cursor__")
    #
    #     await self.page.evaluate("""
    #       () => window.__human_cursor__ && window.__human_cursor__.setTrail(true, {
    #         count: 48,        // больше точек
    #         fadeMs: 900,      // дольше живут
    #         spawnEveryMs: 8,  // чаще спавним
    #         size: 9           // базовый размер точки
    #       })
    #     """)
    #     if not ok:
    #         raise RuntimeError("human cursor overlay not present after ensure_ready()")

    async def ensure_ready(self):
        """
        Убедиться, что overlay есть в ТЕКУЩЕМ документе и включить «шлейф».
        Возвращает dict-диагностику.
        """
        # 1) Гарантируем, что код реально в документе (после любых навигаций)
        ok = await self.page.evaluate(
            """(code) => {
                try {
                  if (!window.__human_cursor__) { (0, eval)(code); }
                  return !!window.__human_cursor__;
                } catch (e) {
                  console.error("[human-cursor] inject error:", e);
                  return false;
                }
            }""",
            MOUSE_OVERLAY_JS,  # <— передаём сам код как аргумент, без форматирования %s
        )
        if not ok:
            raise RuntimeError("human cursor overlay not present after inject()")

        # 2) Включаем шлейф (если в API есть setTrail)
        trail_ok = await self.page.evaluate(
            """(opts) => {
                const api = window.__human_cursor__;
                if (!api) return false;
                if (typeof api.setTrail !== "function") return false;
                try { api.setTrail(true, opts); return true; }
                catch { return false; }
            }""",
            {"count": 48, "fadeMs": 900, "spawnEveryMs": 8, "size": 9},
        )

        # 3) На всякий — показываем курсор/хвост (если вдруг кто-то спрятал)
        await self.page.evaluate("""() => {
            const api = window.__human_cursor__;
            if (api && typeof api.setVisible === 'function') api.setVisible(true);
        }""")

        return {"overlay": True, "trail": bool(trail_ok)}

    async def self_test_circle(self, radius: int = 60, steps: int = 24):
        """Короткий видимый тест: кружок вокруг текущей точки."""
        cx, cy = await self._get_pos()
        for i in range(steps):
            ang = 2 * math.pi * (i / steps)
            x = cx + radius * math.cos(ang)
            y = cy + radius * math.sin(ang)
            await self._move(x, y)
            await asyncio.sleep(0.02)
        await self._move(cx, cy)

    @asynccontextmanager
    async def _busy_section(self):
        """На время активного действия останавливаем idle-джиттер."""
        self._busy += 1
        try:
            yield
        finally:
            self._busy = max(0, self._busy - 1)

    async def _idle_loop(self):
        """
        Человеческий idle:
          - «Стоим» на месте (с микро-дрожью 0.15–0.6 px)
          - Иногда (по вероятности idle_wander_prob) «перекладываем» руку на 1–2 см и снова стоим
          - Все действия паузятся, если идёт активное движение/клик (_busy>0)
        """

        # вспомогалки
        def cm_to_px(cm: float) -> float:
            # 1 inch = 2.54 cm; CSS px ~ PPI при масштабе 100%
            return (self._ppi / 2.54) * cm

        try:
            next_move_ready_at = 0.0
            dwell_until = 0.0
            target: Tuple[float, float] | None = None

            while self._idle_enabled:
                if self._busy == 0:
                    cx, cy = await self._get_pos()
                    j = random.uniform(*self._idle_jitter_px)
                    dx = random.uniform(-j, j)
                    dy = random.uniform(-j, j)
                    await self._move(cx + dx, cy + dy)
                    await asyncio.sleep(random.uniform(*self._idle_period_s))

                if self._busy > 0:
                    # если заняты — просто подождём и продолжим
                    await asyncio.sleep(0.2)
                    continue

                now = asyncio.get_event_loop().time()
                cx, cy = await self._get_pos()

                # если есть активная «стоялка» — мелкая дрожь и ждём
                if dwell_until > now:
                    j = random.uniform(*self._idle_micro_px)
                    if j > 0:
                        # еле заметный вздох в пределах ±j
                        dx = random.uniform(-j, j)
                        dy = random.uniform(-j, j)
                        await self._move(cx + dx, cy + dy)
                    await asyncio.sleep(random.uniform(*self._idle_micro_period_s))
                    continue

                # здесь стоянка завершилась → решаем, двигаться ли на 1–2 см
                if now < next_move_ready_at or random.random() > self._idle_wander_prob:
                    # остаёмся стоять ещё немного (новая стоянка)
                    dwell_until = now + random.uniform(*self._idle_dwell_s)
                    await asyncio.sleep(random.uniform(0.2, 0.4))
                    continue

                # готовим «перекладку» руки (1–2 см в случайном направлении)
                move_cm = random.uniform(*self._idle_move_cm)
                radius_px = cm_to_px(move_cm)  # ~ 38–76 px при 96ppi
                angle = random.uniform(0, 2 * math.pi)
                tx = cx + math.cos(angle) * radius_px
                ty = cy + math.sin(angle) * radius_px

                # аккуратно двигаемся «как человек»
                await self._human_move(cx, cy, tx, ty)

                # после перекладки — снова «стоялка»
                dwell_until = asyncio.get_event_loop().time() + random.uniform(
                    *self._idle_dwell_s
                )
                # следующую перекладку разрешим не сразу
                next_move_ready_at = asyncio.get_event_loop().time() + random.uniform(
                    *self._idle_pause_between_moves_s
                )
        except asyncio.CancelledError:
            return

        except TargetClosedError:
            return

    async def _get_pos(self) -> Tuple[float, float]:
        pos = await self.page.evaluate(
            "() => (window.__human_cursor__ ? window.__human_cursor__.getPos() : {x:8, y:8})"
        )
        return float(pos["x"]), float(pos["y"])

    async def _move(self, x: float, y: float):
        await self.page.evaluate(
            """({x, y}) => { const api = window.__human_cursor__; if (api) api.move(x, y); }""",
            {"x": float(x), "y": float(y)},
        )

    async def _down(self):
        await self.page.evaluate(
            "() => window.__human_cursor__ && window.__human_cursor__.down()"
        )

    async def _up(self):
        await self.page.evaluate(
            "() => window.__human_cursor__ && window.__human_cursor__.up()"
        )

    async def _nudge(self):
        # Маленькое смещение вокруг текущей точки
        cx, cy = await self._get_pos()
        j = random.uniform(*self.jitter_px)
        if j <= 0:
            return
        dx = random.uniform(-j, j)
        dy = random.uniform(-j, j)
        await self._move(cx + dx, cy + dy)
        await asyncio.sleep(random.uniform(0.01, 0.05))
        await self._move(cx, cy)

    async def _human_move(self, x0: float, y0: float, x1: float, y1: float):
        dx, dy = (x1 - x0), (y1 - y0)
        dist = math.hypot(dx, dy)
        if dist < 1.0:
            await self._move(x1, y1)
            return

        # Перелёт (иногда «недолёт» для естественности)
        if random.random() < self.overshoot_prob:
            ov = random.randint(*self.overshoot_px)
            sign = -1 if random.random() < 0.35 else 1
        else:
            ov = 0
            sign = 1
        ovx, ovy = sign * (dx / dist) * ov, sign * (dy / dist) * ov
        tx, ty = (x1 + ovx, y1 + ovy)

        # Контрольные точки кубической Безье с лёгким рандомом
        def ctrl(p0, p1, t, spread=30.0):
            return (
                p0[0] + (p1[0] - p0[0]) * t + random.uniform(-spread, spread),
                p0[1] + (p1[1] - p0[1]) * t + random.uniform(-spread, spread),
            )

        p0 = (x0, y0)
        p3 = (tx, ty)
        p1 = ctrl(p0, p3, 0.33)
        p2 = ctrl(p0, p3, 0.66)

        spd = random.randint(*self.speed_px_s)  # px/sec
        step_target = random.randint(*self.step_px)  # px/step
        steps = max(8, int(dist / max(1, step_target)))

        def bezier(t: float):
            u = 1 - t
            b0 = u * u * u
            b1 = 3 * u * u * t
            b2 = 3 * u * t * t
            b3 = t * t * t
            x = b0 * p0[0] + b1 * p1[0] + b2 * p2[0] + b3 * p3[0]
            y = b0 * p0[1] + b1 * p1[1] + b2 * p2[1] + b3 * p3[1]
            return x, y

        duration = dist / spd
        base_dt = duration / steps

        for i in range(1, steps + 1):
            t = i / steps
            x, y = bezier(t)
            j = random.uniform(*self.jitter_px)
            if j > 0:
                x += random.uniform(-j, j)
                y += random.uniform(-j, j)
            await self._move(x, y)

            dt = base_dt * random.uniform(0.7, 1.35)
            # иногда одна-две микропаузы по пути
            if i in {
                int(steps * random.uniform(0.25, 0.4)),
                int(steps * random.uniform(0.6, 0.85)),
            }:
                dt += random.uniform(
                    self.micro_pause_ms[0] / 1000, self.micro_pause_ms[1] / 1000
                )

            await asyncio.sleep(max(0.005, dt))

        # Лёгкое возвращение из overshoot к точной цели
        await self._move(x1, y1)
        await asyncio.sleep(random.uniform(0.01, 0.04))
