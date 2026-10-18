"""
Auto Drawer Pro v2 - draws a reference image onto any on-screen canvas with your mouse.
Hotkeys while drawing:  F8 pause/resume | F9 slower | F10 faster | ESC stop
Emergency stop: slam the mouse into the TOP-LEFT screen corner.
"""
import sys, os, json, threading, time, queue, math, traceback, random
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)   # must be set before pyautogui/tkinter load
    except Exception: pass
import tkinter as tk
from tkinter import filedialog, ttk, messagebox, simpledialog
import numpy as np
from PIL import Image, ImageTk, ImageGrab, ImageFilter, ImageEnhance, ImageOps
import pyautogui

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    DND = True
except Exception:
    DND = False
try:
    from pynput import keyboard
except Exception:
    keyboard = None

pyautogui.FAILSAFE = True
pyautogui.MINIMUM_DURATION = 0
pyautogui.PAUSE = 0

if sys.platform == "win32":
    class _MI(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _IN(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", _MI)]
        _anonymous_ = ("u",)
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]


class Mouse:
    """Mouse backend. On Windows it uses SendInput (looks like real hardware input); PyAutoGUI is the fallback."""
    def __init__(self, sendinput=True): self.si = sendinput and sys.platform == "win32"

    @staticmethod
    def _send(flags, x=0, y=0):
        i = _IN(0, _IN._U(_MI(x, y, 0, flags, 0, 0)))
        ctypes.windll.user32.SendInput(1, ctypes.byref(i), ctypes.sizeof(_IN))

    def move(self, x, y):
        if self.si:
            u = ctypes.windll.user32; vx, vy, vw, vh = (u.GetSystemMetrics(i) for i in (76, 77, 78, 79))
            self._send(0x8001 | 0x4000, int((x - vx) * 65535 / max(1, vw - 1)), int((y - vy) * 65535 / max(1, vh - 1)))
        else: pyautogui.moveTo(int(x), int(y))

    def down(self, b="left"):
        if self.si: self._send(0x0002 if b == "left" else 0x0008)
        else: pyautogui.mouseDown(button=b)

    def up(self, b="left"):
        if self.si: self._send(0x0004 if b == "left" else 0x0010)
        else: pyautogui.mouseUp(button=b)
BG, CARD, FG, ACC, OK = "#1e1f26", "#2a2c36", "#e8e8ee", "#4f8cff", "#4ade80"
CFG = os.path.join(os.path.expanduser("~"), ".autodrawer.json")
GUARDS = ["Off", "Every 6th stroke", "Every stroke"]
PRESETS = {"Fast": dict(speed=90, hold=10, settle=8, lift=12, maxstep=10, dragpts=2, repair=3, swdelay=0.1, guard=GUARDS[0], checkdelay=40, retries=1, jitter=10, gap=0, rate=0, mvint=0, layerdelay=100),
           "Balanced (recommended)": dict(speed=70, hold=20, settle=20, lift=25, maxstep=8, dragpts=3, repair=6, swdelay=0.15, guard=GUARDS[1], checkdelay=60, retries=2, jitter=15, gap=0, rate=0, mvint=0, layerdelay=150),
           "Careful (most accurate)": dict(speed=40, hold=35, settle=35, lift=45, maxstep=5, dragpts=3, repair=8, swdelay=0.3, guard=GUARDS[1], checkdelay=70, retries=3, jitter=15, gap=0, rate=0, mvint=0, layerdelay=250),
           "Roblox / laggy game": dict(speed=55, hold=60, settle=60, lift=80, maxstep=6, dragpts=3, repair=10, swdelay=0.35, guard=GUARDS[1], checkdelay=90, retries=2, jitter=25, gap=0, rate=0, mvint=0, layerdelay=300)}
ORDERS = ["Layers (big brush → small brush)", "One colour at a time", "One row at a time (all colours per row)"]
PREVIEW_KEYS = ["mode", "fit", "scale", "offx", "offy", "flipx", "flipy", "rot", "invert", "bright", "contrast",
                "sat", "blur", "thr", "dither", "skipwhite", "despeckle", "step", "brush", "order", "labmatch", "overlap", "margin"]


class App((TkinterDnD.Tk if DND else tk.Tk)):
    def __init__(self):
        super().__init__()
        self.title("Auto Drawer Pro"); self.geometry("1320x780"); self.minsize(1100, 700); self.configure(bg=BG)
        self.img = self.idx = self.canvas_box = self.mini = self.pid = None
        self.palette, self.brushes = [], []
        self.stop = self.paused = self.drawing = False
        self.spd, self.t0 = 70.0, 0.0
        self.hk = queue.Queue(); self.rebind = None; self.keys = {}; self.keybtns = {}
        self.undo_pos = self.last_before = self.last_plan = self.park_pt = self.cur_cap = None; self.profiles = {}; self.slow = 1.0; self.last_mode = "Black & white"
        S, D, I, B = tk.StringVar, tk.DoubleVar, tk.IntVar, tk.BooleanVar
        self.v = dict(
            speed=D(value=70), dragpts=I(value=3), hold=I(value=20), swdelay=D(value=0.15), button=S(value="left"),
            input=S(value="Windows SendInput (best)"), nudge=B(value=True), undo=B(value=True),
            layers=B(value=True), rebrush=B(value=False), labmatch=B(value=True), tspace=I(value=0),
            maxstep=I(value=8), settle=I(value=20), lift=I(value=25), margin=I(value=1), fixwrong=B(value=False), verify=B(value=True), caps=S(value="Auto-detect"), guard=S(value=GUARDS[1]), checkdelay=I(value=60), retries=I(value=2), jitter=D(value=15), gap=I(value=0), mvint=D(value=0), rate=I(value=0), layerdelay=I(value=150), preset=S(value="Balanced (recommended)"), overlap=D(value=0), repair=I(value=4), tol=D(value=22), autobrush=B(value=True), showlayer=S(value="All layers"), order=S(value=ORDERS[0]),
            hk_pause=S(value="f8"), hk_slower=S(value="f9"), hk_faster=S(value="f10"), hk_stop=S(value="esc"),
            countdown=I(value=4), mode=S(value="Auto"), fit=S(value="Fit (keep ratio)"), scale=D(value=100),
            offx=D(value=0), offy=D(value=0), flipx=B(value=False), flipy=B(value=False), rot=S(value="0°"),
            invert=B(value=False), bright=D(value=1.0), contrast=D(value=1.0), sat=D(value=1.0), blur=D(value=0),
            thr=D(value=110), dither=B(value=False), skipwhite=B(value=True), despeckle=D(value=1),
            scan=S(value="Horizontal"), corder=S(value="Palette order"), step=I(value=6), brush=S(value=""),
            minimize=B(value=True), ontop=B(value=False), beep=B(value=True))
        self.defaults = {k: v.get() for k, v in self.v.items()}
        self.style(); self.build()
        if DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", lambda e: self.load_image(self.tk.splitlist(e.data)[0]))
        if keyboard:
            keyboard.Listener(on_press=self.on_key).start()
        try: self.apply_cfg(json.load(open(CFG)))
        except Exception: pass
        self.sync_keys()
        for a in ("pause", "slower", "faster", "stop"): self.v["hk_" + a].trace_add("write", self.sync_keys)
        self.spd = float(self.v["speed"].get())
        self.v["speed"].trace_add("write", lambda *a: setattr(self, "spd", float(self.v["speed"].get())))
        self.v["ontop"].trace_add("write", lambda *a: self.attributes("-topmost", bool(self.v["ontop"].get())))
        for k in PREVIEW_KEYS: self.v[k].trace_add("write", self.sched_prev)
        self.v["showlayer"].trace_add("write", lambda *a: self.render_preview())
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self.refresh(); self.after(100, self.poll)

    # ---------- hotkeys ----------
    @staticmethod
    def key_name(k):
        n = getattr(k, "name", None)
        if n: return n
        ch = getattr(k, "char", None)
        return ch.lower() if ch and ch.isprintable() else None

    def on_key(self, k):
        name = self.key_name(k)
        if not name: return
        if self.rebind:
            self.hk.put(("bind", self.rebind, name)); self.rebind = None; return
        if not self.drawing: return
        ks = self.keys
        if name == ks.get("stop"): self.stop = True
        elif name == ks.get("pause"): self.paused = not self.paused
        elif name == ks.get("slower"): self.hk.put(("speed", -10))
        elif name == ks.get("faster"): self.hk.put(("speed", 10))

    def poll(self):
        while not self.hk.empty():
            m = self.hk.get()
            if m[0] == "speed": self.v["speed"].set(max(1, min(100, self.v["speed"].get() + m[1])))
            else: self.v["hk_" + m[1]].set(m[2]); self.say(f"Key set to {m[2].upper()}")
        self.after(100, self.poll)

    def sync_keys(self, *a):
        for act in ("pause", "slower", "faster", "stop"):
            n = self.v["hk_" + act].get(); self.keys[act] = n
            if act in self.keybtns and self.rebind != act: self.keybtns[act].config(text=n.upper())

    def start_bind(self, act):
        if not keyboard: return messagebox.showinfo("Keys", "Changing keybinds needs the 'pynput' package (it is included in the exe).")
        self.rebind = act; self.keybtns[act].config(text="press a key..."); self.say("Press the new key now (works from anywhere).")

    def reset_keys(self):
        self.rebind = None
        for a, d in (("pause", "f8"), ("slower", "f9"), ("faster", "f10"), ("stop", "esc")): self.v["hk_" + a].set(d)
        self.sync_keys()

    # ---------- UI helpers ----------
    def style(self):
        s = ttk.Style(self); s.theme_use("clam")
        s.configure(".", background=CARD, foreground=FG, fieldbackground=BG, font=("Segoe UI", 10))
        s.configure("TFrame", background=CARD); s.configure("TLabel", background=CARD, foreground=FG)
        s.configure("TCheckbutton", background=CARD, foreground=FG)
        s.configure("TButton", background="#3a3d4b", foreground=FG, padding=5, borderwidth=0)
        s.map("TButton", background=[("active", ACC)])
        s.configure("Go.TButton", background=ACC, font=("Segoe UI", 12, "bold"), padding=10)
        s.map("Go.TButton", background=[("active", "#6ba0ff")])
        s.configure("H.TLabel", font=("Segoe UI", 11, "bold"))
        s.configure("TNotebook", background=BG, borderwidth=0)
        s.configure("TNotebook.Tab", background="#3a3d4b", foreground=FG, padding=(14, 6))
        s.map("TNotebook.Tab", background=[("selected", ACC)])
        s.configure("TScale", background=CARD); s.configure("TSeparator", background=BG)

    def card(self, parent, title, tag):
        f = ttk.Frame(parent, padding=8); f.pack(fill="x", pady=3)
        h = ttk.Frame(f); h.pack(fill="x")
        ttk.Label(h, text=title, style="H.TLabel").pack(side="left")
        st = ttk.Label(h, text=tag, foreground="#999"); st.pack(side="right")
        return f, st

    def _row(self, p, label):
        r = ttk.Frame(p); r.pack(fill="x", pady=2); ttk.Label(r, text=label, width=17).pack(side="left"); return r

    def slider(self, p, label, key, lo, hi, fmt="{:.0f}"):
        r = self._row(p, label); val = ttk.Label(r, width=7); val.pack(side="right")
        ttk.Scale(r, from_=lo, to=hi, variable=self.v[key]).pack(side="left", fill="x", expand=True)
        upd = lambda *a: val.config(text=fmt.format(self.v[key].get())); self.v[key].trace_add("write", upd); upd()

    def combo(self, p, label, key, values):
        ttk.Combobox(self._row(p, label), textvariable=self.v[key], state="readonly", values=values).pack(side="left", fill="x", expand=True)

    def spin(self, p, label, key, lo, hi, inc=1):
        ttk.Spinbox(self._row(p, label), from_=lo, to=hi, increment=inc, textvariable=self.v[key], width=8).pack(side="left")

    def check(self, p, text, key): ttk.Checkbutton(p, text=text, variable=self.v[key]).pack(anchor="w", pady=1)

    # ---------- layout ----------
    def build(self):
        left = tk.Frame(self, bg=BG, width=340); left.pack(side="left", fill="y", padx=(8, 4), pady=6); left.pack_propagate(False)
        mid = tk.Frame(self, bg=BG, width=400); mid.pack(side="left", fill="y", padx=4, pady=6); mid.pack_propagate(False)
        right = tk.Frame(self, bg=BG); right.pack(side="left", fill="both", expand=True, padx=(4, 8), pady=6)

        f, self.st_img = self.card(left, "Reference image", "required")
        self.drop = tk.Label(f, text="Drop image here or click to browse", bg=BG, fg="#aaa", height=3, cursor="hand2")
        self.drop.pack(fill="x", pady=3); self.drop.bind("<Button-1>", lambda e: self.browse())

        f, self.st_canvas = self.card(left, "1  Canvas area", "required")
        ttk.Button(f, text="Select canvas (drag a box)", command=self.sel_canvas).pack(fill="x")
        self.l_canvas = ttk.Label(f, text="Not set", foreground="#999"); self.l_canvas.pack(anchor="w")

        f, self.st_col = self.card(left, "2  Colours", "optional")
        r = ttk.Frame(f); r.pack(fill="x")
        ttk.Button(r, text="Select palette box", command=self.sel_palette).pack(side="left", expand=True, fill="x")
        ttk.Button(r, text="Click swatches", command=self.click_swatches).pack(side="left", expand=True, fill="x", padx=(4, 0))
        self.chips = tk.Frame(f, bg=CARD); self.chips.pack(fill="x", pady=3)
        ttk.Button(f, text="Clear colours", command=lambda: (self.palette.clear(), self.refresh(), self.sched_prev())).pack(anchor="e")

        f, self.st_br = self.card(left, "3  Brush size", "optional")
        r = ttk.Frame(f); r.pack(fill="x")
        ttk.Button(r, text="Click brush buttons", command=self.click_brushes).pack(side="left", expand=True, fill="x")
        ttk.Button(r, text="Auto-measure sizes", command=lambda: self.calibrate(0)).pack(side="left", expand=True, fill="x", padx=(4, 0))
        ttk.Checkbutton(f, text="Undo test lines afterwards (Ctrl+Z / undo button)", variable=self.v["undo"]).pack(anchor="w")
        ttk.Button(f, text="Pick undo button (optional)", command=self.pick_undo).pack(fill="x", pady=2)
        ttk.Checkbutton(f, text="Auto-detect brush width if no brush is set", variable=self.v["autobrush"]).pack(anchor="w")
        r = ttk.Frame(f); r.pack(fill="x", pady=3); ttk.Label(r, text="Use:").pack(side="left")
        self.cb = ttk.Combobox(r, textvariable=self.v["brush"], state="readonly", width=20); self.cb.pack(side="left", padx=4)
        ttk.Button(r, text="Clear", width=6, command=lambda: (self.brushes.clear(), self.refresh())).pack(side="right")
        self.spin(f, "Manual step px", "step", 1, 60)
        self.spin(f, "Test line spacing px", "tspace", 0, 400, 5)

        r = tk.Frame(left, bg=BG); r.pack(fill="x", pady=4)
        for t, c in (("Preview", self.preview), ("Trace box", self.trace), ("Test line", self.test_stroke)):
            ttk.Button(r, text=t, command=c).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(r, text="Save", width=5, command=self.save_cfg).pack(side="left", padx=2)
        ttk.Button(r, text="Load", width=5, command=self.load_cfg).pack(side="left", padx=2)
        ttk.Button(left, text="START DRAWING", style="Go.TButton", command=self.start).pack(fill="x", padx=2, pady=(4, 1))
        ttk.Button(left, text="Repair gaps (check canvas & redraw missing)", command=lambda: self.start(True)).pack(fill="x", padx=2, pady=1)
        self.status = tk.Label(left, text="Ready", bg=BG, fg="#aaa", wraplength=320, justify="left"); self.status.pack(anchor="w")

        nb = ttk.Notebook(mid); nb.pack(fill="both", expand=True)
        tabs = {n: ttk.Frame(nb, padding=10) for n in ("Speed", "Timing", "Image", "Drawing", "App")}
        for n, t in tabs.items(): nb.add(t, text=n)

        t = tabs["Speed"]
        r = self._row(t, "Preset"); self.pc = ttk.Combobox(r, textvariable=self.v["preset"], state="readonly", values=self.preset_names()); self.pc.pack(side="left", fill="x", expand=True)
        self.pc.bind("<<ComboboxSelected>>", lambda e: self.apply_preset())
        r = ttk.Frame(t); r.pack(fill="x", pady=2)
        ttk.Button(r, text="Save current as preset...", command=self.save_preset).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(r, text="Delete preset", command=self.del_preset).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Label(t, text="Drawing speed", style="H.TLabel").pack(anchor="w")
        self.slider(t, "Speed (1-100)", "speed", 1, 100)
        r = ttk.Frame(t); r.pack(fill="x", pady=4)
        for n, val in (("Slow", 20), ("Normal", 55), ("Fast", 85), ("Max", 100)):
            ttk.Button(r, text=n, command=lambda x=val: self.v["speed"].set(x)).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Label(t, text="Speed can be changed LIVE while drawing\n(F9 slower / F10 faster, or the mini panel).", foreground="#999").pack(anchor="w", pady=(0, 8))
        ttk.Separator(t).pack(fill="x", pady=4)
        ttk.Label(t, text="Lag handling (Roblox / laggy games)", style="H.TLabel").pack(anchor="w")
        self.combo(t, "Lag guard", "guard", GUARDS)
        self.spin(t, "Check delay ms", "checkdelay", 0, 500, 10)
        self.spin(t, "Retries per stroke", "retries", 0, 5)
        self.slider(t, "Timing jitter %", "jitter", 0, 50)
        self.spin(t, "Extra delay / stroke ms", "gap", 0, 500, 5)
        self.spin(t, "Max strokes / sec (0=off)", "rate", 0, 200, 5)
        self.spin(t, "Move interval ms (0=auto)", "mvint", 0, 50, 0.5)
        ttk.Label(t, text="Lag guard checks that strokes really appeared and redraws them,\nand slows down by itself while the game is lagging.", foreground="#999").pack(anchor="w", pady=4)
        t = tabs["Timing"]
        self.spin(t, "Smooth drag points", "dragpts", 0, 10)
        self.spin(t, "Max move step px", "maxstep", 0, 60)
        self.spin(t, "End-of-stroke settle ms", "settle", 0, 150)
        self.spin(t, "Pen-up wait ms", "lift", 0, 200)
        ttk.Button(t, text="Auto-tune speed (test on canvas)", command=self.autotune).pack(fill="x", pady=4)
        self.spin(t, "Mouse-down hold ms", "hold", 0, 300, 5)
        self.spin(t, "Colour switch delay", "swdelay", 0, 3, 0.05)
        self.spin(t, "Layer switch delay ms", "layerdelay", 0, 3000, 50)
        self.spin(t, "Start countdown (s)", "countdown", 1, 20)
        self.combo(t, "Draw with button", "button", ["left", "right"])
        self.combo(t, "Mouse input", "input", ["Windows SendInput (best)", "PyAutoGUI (fallback)"])
        self.check(t, "Nudge mouse on single dots", "nudge")
        ttk.Label(t, text="Roblox tips: use Windowed / F11 fullscreen, lower graphics quality,\nclose other programs, and try the 'Roblox / laggy game' preset.", foreground="#999").pack(anchor="w", pady=6)

        t = tabs["Image"]
        self.slider(t, "Image size %", "scale", 10, 300); self.slider(t, "Move left/right %", "offx", -100, 100)
        self.slider(t, "Move up/down %", "offy", -100, 100); self.combo(t, "Rotate", "rot", ["0°", "90°", "180°", "270°"])
        r = ttk.Frame(t); r.pack(fill="x")
        for txt, k in (("Flip horizontal", "flipx"), ("Flip vertical", "flipy"), ("Invert", "invert")):
            ttk.Checkbutton(r, text=txt, variable=self.v[k]).pack(side="left", padx=4)
        ttk.Separator(t).pack(fill="x", pady=6)
        self.slider(t, "Brightness", "bright", 0.3, 2.0, "{:.2f}"); self.slider(t, "Contrast", "contrast", 0.5, 2.5, "{:.2f}")
        self.slider(t, "Colour boost", "sat", 0, 3, "{:.2f}"); self.slider(t, "Smooth / blur", "blur", 0, 5, "{:.1f}")
        self.slider(t, "Threshold (B&W/lines)", "thr", 5, 250)

        t = tabs["Drawing"]
        self.combo(t, "Mode", "mode", ["Auto", "Palette colours", "Black & white", "Line art"])
        self.combo(t, "Fit", "fit", ["Fit (keep ratio)", "Stretch to canvas"])
        self.combo(t, "Stroke direction", "scan", ["Horizontal", "Vertical", "Serpentine"])
        self.combo(t, "Colour order", "corder", ["Palette order", "Lightest first", "Darkest first", "Most pixels first", "Fewest pixels first"])
        self.combo(t, "Draw order", "order", ORDERS)
        ttk.Label(t, text="Layers: big brush fills solid areas first, small brush adds detail (needs 2+ brushes).\nOne colour at a time: finish a whole colour before the next.\nOne row at a time: complete each row (every colour in it) before the next row.", foreground="#999", wraplength=360, justify="left").pack(anchor="w", pady=2)
        self.check(t, "Re-click brush after each colour change", "rebrush")
        self.check(t, "Perceptual colour matching (more accurate)", "labmatch")
        self.slider(t, "Overlap % (0=no overdraw)", "overlap", 0, 40)
        self.spin(t, "Layer safety margin", "margin", 0, 4)
        self.check(t, "Verify brush & colour while drawing", "verify")
        self.combo(t, "Brush ends", "caps", ["Auto-detect", "Round / square", "Flat"])
        self.spin(t, "Repair passes (0-5)", "repair", 0, 5)
        self.check(t, "Repair wrong colours too (can redraw edges)", "fixwrong")
        self.slider(t, "Repair tolerance", "tol", 8, 50)
        self.slider(t, "Clean up specks (0-3)", "despeckle", 0, 3)
        self.check(t, "Dither colours (smoother blends)", "dither")
        self.check(t, "Skip white (keep canvas background)", "skipwhite")
        ttk.Label(t, text="Tip: 'Most pixels first' paints big background\ncolours first; 'Serpentine' saves mouse travel.", foreground="#999").pack(anchor="w", pady=8)

        t = tabs["App"]
        self.check(t, "Hide this window while drawing", "minimize"); self.check(t, "Keep this window on top", "ontop")
        self.check(t, "Beep when finished", "beep")
        ttk.Button(t, text="Reset all settings", command=self.reset).pack(anchor="w", pady=6)
        ttk.Separator(t).pack(fill="x", pady=4)
        ttk.Label(t, text="Keybinds (click a button, then press the new key)", style="H.TLabel").pack(anchor="w")
        for act, lbl in (("pause", "Pause / resume"), ("slower", "Slower"), ("faster", "Faster"), ("stop", "Stop")):
            r = self._row(t, lbl); b = ttk.Button(r, width=16, text=self.v["hk_" + act].get().upper(), command=lambda a=act: self.start_bind(a))
            b.pack(side="left"); self.keybtns[act] = b
        ttk.Button(t, text="Reset keybinds", command=self.reset_keys).pack(anchor="w", pady=4)
        ttk.Label(t, text="Pick keys your drawing app doesn't use (F-keys are safest).\nTop-left screen corner = emergency stop.\nYour setup is saved automatically on exit.", foreground="#999").pack(anchor="w")

        top = tk.Frame(right, bg=BG); top.pack(fill="x")
        tk.Label(top, text="Show:", bg=BG, fg=FG).pack(side="left", padx=(0, 6))
        self.layer_cb = ttk.Combobox(top, textvariable=self.v["showlayer"], state="readonly", width=24); self.layer_cb.pack(side="left")
        self.layer_lbl = tk.Label(right, text="", bg=BG, fg="#aaa", wraplength=620, justify="left", anchor="w"); self.layer_lbl.pack(fill="x", pady=4)
        self.prev = tk.Label(right, text="Preview", bg="#15161b", fg="#666"); self.prev.pack(fill="both", expand=True)

    def say(self, t): self.status.config(text=t); self.update_idletasks()

    TIMING_KEYS = ("speed", "hold", "settle", "lift", "maxstep", "dragpts", "repair", "swdelay", "guard", "checkdelay", "retries", "jitter", "gap", "rate", "mvint", "layerdelay")

    def preset_names(self): return list(PRESETS) + sorted(self.profiles)

    def save_preset(self):
        n = simpledialog.askstring("Save preset", "Name for this speed/timing preset:", parent=self)
        if not n or not n.strip(): return
        n = n.strip(); self.profiles[n] = {k: self.v[k].get() for k in self.TIMING_KEYS}
        self.pc["values"] = self.preset_names(); self.v["preset"].set(n); self.say(f"Saved preset '{n}'.")

    def del_preset(self):
        n = self.v["preset"].get()
        if n in self.profiles:
            del self.profiles[n]; self.pc["values"] = self.preset_names(); self.v["preset"].set("Balanced (recommended)"); self.say(f"Deleted preset '{n}'.")
        else: self.say("Only presets you saved yourself can be deleted.")

    def apply_preset(self):
        for k, val in (self.profiles.get(self.v["preset"].get()) or PRESETS.get(self.v["preset"].get(), {})).items(): self.v[k].set(val)
        self.say("Preset applied: " + self.v["preset"].get())

    def reset(self):
        for k, val in self.defaults.items(): self.v[k].set(val)
        self.refresh()

    def refresh(self):
        def mark(lbl, ok, opt=False): lbl.config(text="✔ set" if ok else ("optional" if opt else "required"), foreground=OK if ok else "#999")
        mark(self.st_img, self.img is not None); mark(self.st_canvas, self.canvas_box is not None)
        mark(self.st_col, bool(self.palette), True); mark(self.st_br, bool(self.brushes), True)
        b = self.canvas_box
        self.l_canvas.config(text=f"{b[2]-b[0]} x {b[3]-b[1]} px at ({b[0]}, {b[1]})" if b else "Not set")
        for w in self.chips.winfo_children(): w.destroy()
        for i, p in enumerate(self.palette):
            l = tk.Label(self.chips, bg="#%02x%02x%02x" % p["rgb"], width=3, cursor="X_cursor"); l.pack(side="left", padx=1, pady=1)
            l.bind("<Button-1>", lambda e, i=i: (self.palette.pop(i), self.refresh(), self.sched_prev()))
        names = self.brush_names(); self.cb["values"] = names
        if names and self.v["brush"].get() not in names: self.v["brush"].set(names[0])
        if not names: self.v["brush"].set("")

    def brush_names(self): return [f"Brush {i+1}: {b['px']}px" for i, b in enumerate(self.brushes)]

    # ---------- image ----------
    def browse(self):
        p = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp")])
        if p: self.load_image(p)

    def load_image(self, p):
        try: self.img = ImageOps.exif_transpose(Image.open(p)).convert("RGBA")
        except Exception as e: return messagebox.showerror("Error", str(e))
        self.drop.config(text=os.path.basename(p), fg=FG); self.refresh(); self.preview()

    # ---------- screenshot-style selectors ----------
    def overlay(self, hint):
        self.withdraw(); self.update(); time.sleep(0.35)
        grab = ImageGrab.grab().convert("RGB")
        t = tk.Toplevel(self); t.attributes("-fullscreen", True, "-topmost", True); t.config(cursor="crosshair")
        W, H = t.winfo_screenwidth(), t.winfo_screenheight(); k = grab.width / W
        c = tk.Canvas(t, width=W, height=H, highlightthickness=0); c.pack()
        c.dim = ImageTk.PhotoImage(ImageEnhance.Brightness(grab).enhance(0.45).resize((W, H))); c.create_image(0, 0, anchor="nw", image=c.dim)
        c.create_rectangle(0, 0, 880, 36, fill="black"); c.create_text(10, 18, anchor="w", fill="yellow", font=("Arial", 14), text=hint)
        t.bind("<Escape>", lambda e: self.close(t)); t.focus_force()
        return t, c, grab, k

    def close(self, t): t.destroy(); self.deiconify(); self.refresh()

    def box_select(self, hint, done):
        t, c, grab, k = self.overlay(hint); s = {}
        def down(e): s["p"] = (e.x, e.y, e.x_root, e.y_root); s["r"] = c.create_rectangle(e.x, e.y, e.x, e.y, outline="#4f8cff", width=2)
        def drag(e):
            x1, y1 = s["p"][:2]; c.coords(s["r"], x1, y1, e.x, e.y)
            bx = (min(x1, e.x), min(y1, e.y), max(x1, e.x), max(y1, e.y))
            if bx[2] - bx[0] > 2 and bx[3] - bx[1] > 2:
                c.bright = ImageTk.PhotoImage(grab.crop(tuple(int(v * k) for v in bx)).resize((bx[2] - bx[0], bx[3] - bx[1])))
                if "b" in s: c.delete(s["b"])
                s["b"] = c.create_image(bx[0], bx[1], anchor="nw", image=c.bright); c.tag_raise(s["r"])
        def up(e):
            xr, yr = s["p"][2:]; box = (min(xr, e.x_root), min(yr, e.y_root), max(xr, e.x_root), max(yr, e.y_root))
            self.close(t)
            if box[2] - box[0] > 5 and box[3] - box[1] > 5: done(box, grab, k)
        c.bind("<ButtonPress-1>", down); c.bind("<B1-Motion>", drag); c.bind("<ButtonRelease-1>", up)

    def click_select(self, hint, done):
        t, c, grab, k = self.overlay(hint + "  (right-click / Esc = finish)"); pts = []
        def click(e):
            pts.append((e.x_root, e.y_root, grab.getpixel((int(e.x * k), int(e.y * k)))))
            c.create_oval(e.x - 7, e.y - 7, e.x + 7, e.y + 7, outline="red", width=2)
            c.create_text(e.x + 14, e.y - 12, text=str(len(pts)), fill="red", font=("Arial", 14, "bold"))
        c.bind("<Button-1>", click); c.bind("<Button-3>", lambda e: (self.close(t), done(pts)))
        t.bind("<Escape>", lambda e: (self.close(t), done(pts)))

    def sel_canvas(self):
        def done(b, g, k): self.canvas_box = b; self.refresh(); self.preview()
        self.box_select("Drag a box around the drawing canvas.  Esc = cancel", done)

    def click_swatches(self):
        def done(pts): self.palette += [{"pos": (x, y), "rgb": tuple(c)} for x, y, c in pts]; self.refresh(); self.preview()
        self.click_select("Click each colour swatch.", done)

    def click_brushes(self):
        def done(pts):
            if not pts: return
            start = len(self.brushes)
            self.brushes += [{"pos": (x, y), "px": 0} for x, y, _ in pts]; self.refresh()
            if self.canvas_box and messagebox.askyesno("Brush sizes", "Measure the brush sizes automatically?\n\nI will draw a short test line with each brush on your canvas, measure its width, then undo it (Ctrl+Z).\nMake sure the canvas is visible and a colour different from the background is selected."):
                self.calibrate(start)
            else:
                for i in range(start, len(self.brushes)):
                    px = simpledialog.askinteger("Brush size", f"Brush {i+1}: how many pixels wide is it?", initialvalue=4 * (i + 1), minvalue=1, maxvalue=300, parent=self)
                    self.brushes[i]["px"] = px or 4 * (i + 1)
                self.refresh()
        self.click_select("Click each brush-size button (smallest to largest).", done)

    def mini_place(self, w, h):
        """Find the screen spot where the panel covers the least of the canvas / swatches / brush buttons."""
        W, H = self.winfo_screenwidth(), self.winfo_screenheight(); b = self.canvas_box or (0, 0, 0, 0)
        pts = [p["pos"] for p in self.palette] + [q["pos"] for q in self.brushes] + ([self.undo_pos] if self.undo_pos else [])
        best = None
        for x in range(0, max(1, W - w), 40):
            for y in range(0, max(1, H - h - 40), 40):
                ov = max(0, min(x + w, b[2]) - max(x, b[0])) * max(0, min(y + h, b[3]) - max(y, b[1]))
                ov += 10 ** 9 * sum(1 for px, py in pts if x - 15 <= px <= x + w + 15 and y - 15 <= py <= y + h + 15)
                key = (ov, min(x, W - w - x) + min(y, H - h - y))
                if best is None or key < best[0]: best = (key, x, y)
        return best[1], best[2], best[0][0] > 0

    def gscale(self):
        if getattr(self, "_gs", None) is None:
            try: self._gs = ImageGrab.grab().width / max(1, self.winfo_screenwidth())
            except Exception: self._gs = 1.0
        return self._gs

    def snap(self, box):
        k = self.gscale(); b2 = tuple(int(round(v * k)) for v in box) if abs(k - 1) > 0.02 else tuple(box)
        try: im = ImageGrab.grab(bbox=b2, all_screens=True).convert("RGB")
        except TypeError: im = ImageGrab.grab(bbox=b2).convert("RGB")
        w, h = box[2] - box[0], box[3] - box[1]
        return im.resize((w, h), Image.BOX) if im.size != (w, h) else im

    @staticmethod
    def cap_from(before, after, length, w):
        d = np.abs(np.array(before).astype(int) - np.array(after).astype(int)).sum(2) > 60
        cols = np.flatnonzero(d.any(axis=0))
        if len(cols) == 0 or not w: return None
        cap = max(0.0, min(float(w), ((cols[-1] - cols[0] + 1) - length) / 2.0))
        return 0.0 if cap < 1.5 else round(float(cap), 1)      # 0 = flat ends, w/2 = round or square ends

    @staticmethod
    def measure(before, after, c):
        d = np.abs(np.array(before).astype(int) - np.array(after).astype(int)).sum(2) > 60
        rows = d.mean(1) > 0.6
        if not rows[c]:
            near = [r for r in range(max(0, c - 3), min(len(rows), c + 4)) if rows[r]]
            if not near: return None
            c = near[0]
        s = e = c
        while s > 0 and rows[s - 1]: s -= 1
        while e < len(rows) - 1 and rows[e + 1]: e += 1
        return None if s == 0 or e == len(rows) - 1 else e - s + 1

    def calibrate(self, start=0):
        if self.drawing: return
        if not self.canvas_box: return messagebox.showinfo("Canvas", "Select the canvas first - the test lines are drawn on it.")
        if len(self.brushes) <= start: return messagebox.showinfo("Brushes", "Click your brush-size buttons first.")
        g = {k: v.get() for k, v in self.v.items()}
        self.stop = self.paused = False; self.drawing = True
        self.open_mini(); self.withdraw()
        threading.Thread(target=self._calib, args=(g, start), daemon=True).start()

    def do_undo(self, m):
        if self.undo_pos: self.click(m, *self.undo_pos, 0.4)
        else: pyautogui.hotkey("command" if sys.platform == "darwin" else "ctrl", "z"); time.sleep(0.4)

    def pick_undo(self):
        def done(pts):
            if pts: self.undo_pos = (pts[0][0], pts[0][1]); self.say("Undo button saved.")
        self.click_select("Click your app's UNDO button once.", done)

    def test_line(self, m, g, yc, half, brush_pos=None):
        """Select a brush (optional), draw a short test line, measure its thickness in px, then undo it."""
        b = self.canvas_box; W = b[2] - b[0]
        x0, x1 = int(b[0] + W * 0.2), int(b[0] + W * 0.5); xm = (x0 + x1) // 2
        box = (xm - 8, yc - half, xm + 9, yc + half + 1)
        before = self.snap(box); bgc = before.getpixel((8, half)); hb = (x0 - 90, yc - 1, x1 + 91, yc + 2); hbefore = self.snap(hb)
        if brush_pos: self.click(m, *brush_pos, 0.3)
        for p in self.palette:                       # use a colour that contrasts with the background
            if sum(abs(p["rgb"][c] - bgc[c]) for c in range(3)) > 200: self.click(m, *p["pos"], 0.3); break
        m.move(x0, yc); time.sleep(0.05); m.down(g["button"]); time.sleep(0.05)
        for q in range(1, 41): m.move(x0 + (x1 - x0) * q / 40, yc); time.sleep(0.006)
        time.sleep(0.02); m.up(g["button"]); time.sleep(0.3)
        w = self.measure(before, self.snap(box), half); undo_failed = False; cap = self.cap_from(hbefore, self.snap(hb), x1 - x0, w)
        if g["undo"]:
            self.do_undo(m)
            back = np.array(self.snap(box)).astype(int) - np.array(before).astype(int)
            undo_failed = bool((np.abs(back).sum(2) > 60).mean() > 0.02)
        return w, undo_failed, cap

    def _calib(self, g, start):
        res, undo_failed, err = {}, False, ""
        try:
            m = Mouse(g["input"].startswith("Windows")); b = self.canvas_box; H = b[3] - b[1]
            idxs = list(range(start, len(self.brushes))); n = len(idxs)
            for s in range(3, 0, -1):
                if self.stop: raise KeyboardInterrupt
                self.ui(f"Measuring brush sizes in {s}s - keep your drawing app visible!"); time.sleep(1)
            for j, i in enumerate(idxs):
                self.gate(); self.ui(f"Measuring brush {i+1} ({j+1}/{n})...", j / n)
                sp = g["tspace"] if g["tspace"] > 0 else H / (n + 1)
                yc = int(b[1] + sp * (j + 1))
                if yc > b[3] - 4: sp = H / (n + 1); yc = int(b[1] + sp * (j + 1))   # spacing too big for canvas -> auto
                half = int(min(150, max(6, sp / 2 - 3)))
                w, uf, cap = self.test_line(m, g, yc, half, self.brushes[i]["pos"]); res[i] = (w, cap); undo_failed |= uf
        except KeyboardInterrupt: err = "Stopped."
        except pyautogui.FailSafeException: err = "Stopped (failsafe corner)."
        except Exception as ex: self.log(traceback.format_exc()); err = f"Error: {ex}"
        self.drawing = False; self.after(0, self.calib_done, start, res, undo_failed, err)

    @staticmethod
    def dash_score(before, after, n, dash, gap, margin, pad=6):
        d = np.abs(np.array(before).astype(int) - np.array(after).astype(int)).sum(2) > 60
        col = d.any(axis=0); ok = tot = 0
        for k in range(n):
            s = pad + k * (dash + gap)
            ok += int(col[s:s + dash].sum()); tot += dash                        # dash fully drawn
            gs, ge = s + dash + margin, s + dash + gap - margin
            if k < n - 1 and ge > gs: ok += int((~col[gs:ge]).sum()); tot += ge - gs   # gap kept clean (no connecting line)
        return ok / max(1, tot)

    def autotune(self):
        if self.drawing: return
        if not self.canvas_box: return messagebox.showinfo("Canvas", "Select the canvas first.")
        if not messagebox.askyesno("Auto-tune", "I'll draw a few short test lines on your canvas at different speeds, check which speeds draw COMPLETELY, then undo them.\n\nMake sure your drawing app is ready and a visible colour/brush is selected. Continue?"): return
        g = {k: v.get() for k, v in self.v.items()}
        self.stop = self.paused = False; self.drawing = True; self.open_mini(); self.withdraw()
        threading.Thread(target=self._tune, args=(g,), daemon=True).start()

    PROFILES = [(100, 4, 3, 3), (85, 10, 8, 8), (70, 15, 12, 15), (55, 20, 20, 25), (40, 30, 30, 40), (25, 45, 45, 60), (10, 70, 70, 90), (5, 110, 110, 140), (2, 170, 170, 220)]

    def _tune(self, g):
        res, err, uf = [], "", False
        try:
            m = Mouse(g["input"].startswith("Windows")); b = self.canvas_box; W, H = b[2] - b[0], b[3] - b[1]
            n_p = len(self.PROFILES); brush = self.cur_brush()
            for s in range(3, 0, -1):
                if self.stop: raise KeyboardInterrupt
                self.ui(f"Speed test in {s}s - keep your drawing app visible!"); time.sleep(1)
            if brush: self.click(m, *brush["pos"], 0.3)
            bw = min(60, max(int(g["step"]), 8)); dash = 40; gap = max(70, bw + 30); margin = bw // 2 + 4
            n = max(2, min(5, int((W * 0.8 + gap) // (dash + gap)))); x0 = int(b[0] + W * 0.1); total = n * dash + (n - 1) * gap; picked = False
            for j, (sp, hold, settle, lift) in enumerate(self.PROFILES):
                self.gate(); self.ui(f"Testing timing profile {j+1}/{n_p} (speed {sp})...", j / n_p)
                yc = int(b[1] + H * (j + 1) / (n_p + 1)); band = (x0 - 6, yc - 6, x0 + total + 7, yc + 7)
                before = self.snap(band)
                if not picked:
                    picked = True; bgc = before.getpixel((8, 6))
                    for p in self.palette:
                        if sum(abs(p["rgb"][c] - bgc[c]) for c in range(3)) > 200: self.click(m, *p["pos"], 0.3); break
                g2 = dict(g, hold=hold, settle=settle, lift=lift); self.spd = float(sp); pause, interval = self.timing()
                for k in range(n):
                    self.gate(); xa = x0 + k * (dash + gap); self.stroke(m, xa, yc, xa + dash, yc, g2, interval)
                time.sleep(pause + 0.3)
                res.append((j, self.dash_score(before, self.snap(band), n, dash, gap, margin)))
                if g["undo"]:
                    self.do_undo(m); back = np.array(self.snap(band)).astype(int) - np.array(before).astype(int)
                    uf |= bool((np.abs(back).sum(2) > 60).mean() > 0.02)
        except KeyboardInterrupt: err = "Stopped."
        except pyautogui.FailSafeException: err = "Stopped (failsafe corner)."
        except Exception as ex: self.log(traceback.format_exc()); err = f"Error: {ex}"
        self.drawing = False; self.after(0, self.tune_done, res, uf, err)

    def tune_done(self, res, uf, err):
        if self.mini: self.mini.destroy(); self.mini = None
        self.deiconify()
        if err or not res: return self.say(err or "Speed test didn't run.")
        ok = [f >= 0.97 for _, f in res]; best = None
        for i in range(len(res)):                      # fastest profile that, together with the next slower one, draws perfectly
            if ok[i] and (i + 1 >= len(res) or ok[i + 1]): best = i; break
        table = ", ".join(f"speed {self.PROFILES[j][0]}: {int(f * 100)}%" for j, f in res)
        if best is None:
            best = len(self.PROFILES) - 1
            txt = f"No profile drew the test dashes perfectly ({table}). I picked the slowest, safest timing. Check the canvas box, selected colour/brush, and that nothing covers the canvas."
        else: txt = f"Test results: {table}. Applied the fastest reliable timing (speed {self.PROFILES[best][0]})."
        sp, hold, settle, lift = self.PROFILES[best]
        self.v["speed"].set(sp); self.v["hold"].set(hold); self.v["settle"].set(settle); self.v["lift"].set(lift)
        self.say(txt + (" Couldn't undo the test lines - clear your canvas." if uf else ""))

    def calib_done(self, start, res, undo_failed, err):
        if self.mini: self.mini.destroy(); self.mini = None
        self.deiconify()
        for i in range(start, len(self.brushes)):
            w, cap = res.get(i, (None, None))
            if w: self.brushes[i]["px"] = w; self.brushes[i]["cap"] = cap
            elif err: self.brushes[i]["px"] = self.brushes[i]["px"] or 4 * (i + 1)
            else:
                px = simpledialog.askinteger("Brush size", f"Couldn't measure brush {i+1} automatically (a colour that differs from the background must be selected).\nEnter its width in pixels:", initialvalue=self.brushes[i]["px"] or 4 * (i + 1), minvalue=1, maxvalue=300, parent=self)
                self.brushes[i]["px"] = px or 4 * (i + 1)
        self.refresh(); self.sched_prev()
        sizes = ", ".join(f"{b['px']}px" for b in self.brushes)
        self.say((err + " " if err else "") + f"Brush sizes: {sizes}." + (" Couldn't undo the test lines - clear your canvas." if undo_failed else ""))

    def sel_palette(self):
        def done(box, grab, k):
            found = self.detect(box, grab, k)
            if not found: return messagebox.showinfo("Colours", "No swatches found. Try a tighter box or use 'Click swatches'.")
            self.palette += found; self.refresh(); self.preview(); self.say(f"Found {len(found)} colours. Click a chip to remove it.")
        self.box_select("Drag a box around your colour palette.  Esc = cancel", done)

    def detect(self, box, grab, k):
        x1, y1, x2, y2 = (int(v * k) for v in box)
        a = np.array(grab.crop((x1, y1, x2, y2))).astype(int)
        s = max(1, max(a.shape[:2]) // 250); a = a[::s, ::s]; H, W, _ = a.shape
        seen = np.zeros((H, W), bool); out = []
        for y in range(H):
            for x in range(W):
                if seen[y, x]: continue
                seed = a[y, x]; seen[y, x] = True; st = [(y, x)]; cells = []
                while st:
                    cy, cx = st.pop(); cells.append((cy, cx))
                    for ny, nx in ((cy+1, cx), (cy-1, cx), (cy, cx+1), (cy, cx-1)):
                        if 0 <= ny < H and 0 <= nx < W and not seen[ny, nx] and abs(a[ny, nx] - seed).sum() < 40:
                            seen[ny, nx] = True; st.append((ny, nx))
                n = len(cells)
                if n < 12 or n > 0.25 * H * W: continue
                ys, xs = np.array(cells).T; bh, bw = np.ptp(ys) + 1, np.ptp(xs) + 1
                if bw < 3 or bh < 3 or n / (bh * bw) < 0.6: continue
                rgb = tuple(int(v) for v in a[ys, xs].mean(0))
                if any(sum(abs(np.array(rgb) - np.array(o[2]))) < 14 for o in out): continue
                out.append((ys.mean(), xs.mean(), rgb, bh))
        if not out: return []
        rh = np.median([o[3] for o in out]) * 1.5
        out.sort(key=lambda o: (int(o[0] / rh), o[1]))
        return [{"pos": ((x1 + o[1] * s + s / 2) / k, (y1 + o[0] * s + s / 2) / k), "rgb": o[2]} for o in out]

    # ---------- image -> stroke grid ----------
    def cur_brush(self):
        n = self.v["brush"].get(); names = self.brush_names()
        return self.brushes[names.index(n)] if n in names else None

    def eff(self, px): return max(1, int(round(px * (1 - self.v["overlap"].get() / 100.0))))

    def active_brushes(self):
        valid = sorted((b for b in self.brushes if b["px"] > 0), key=lambda b: -b["px"]); uniq = []
        for b in valid:                                    # ignore near-duplicate sizes
            if not uniq or uniq[-1]["px"] - b["px"] >= 2: uniq.append(b)
        if self.v["order"].get().startswith("Layers") and len(uniq) >= 2: return uniq     # big -> small
        b = self.cur_brush(); return [b] if b and b["px"] > 0 else []

    def step_px(self):
        bs = self.active_brushes()
        return self.eff(min(b["px"] for b in bs)) if bs else self.eff(int(self.v["step"].get()))

    def geom(self, br):
        w = float(br["px"]) if br else float(max(1, int(self.v["step"].get())))
        mode = self.v["caps"].get(); known = br.get("cap") if br else self.cur_cap
        cap = 0.0 if mode.startswith("Flat") else (w / 2.0 if mode.startswith("Round") or known is None else float(known))
        return w, cap

    @staticmethod
    def endpoints(a, b, p, w, cap, bx, by):
        """Mouse start/end for a run of cells so the stroke covers exactly those cells (caps stay inside them)."""
        spill = max(0.0, (w - p) / 2.0)
        if a[1] == b[1]:
            lo, hi = min(a[0], b[0]) * p, (max(a[0], b[0]) + 1) * p; y = (a[1] + 0.5) * p
            s, e = lo - spill + cap, hi + spill - cap
            if e < s: s = e = (lo + hi) / 2.0
            if a[0] > b[0]: s, e = e, s
            return bx + s, by + y, bx + e, by + y
        lo, hi = min(a[1], b[1]) * p, (max(a[1], b[1]) + 1) * p; x = (a[0] + 0.5) * p
        s, e = lo - spill + cap, hi + spill - cap
        if e < s: s = e = (lo + hi) / 2.0
        if a[1] > b[1]: s, e = e, s
        return bx + x, by + s, bx + x, by + e

    def eff_mode(self):
        m = self.v["mode"].get(); return ("Palette colours" if self.palette else "Black & white") if m == "Auto" else m

    @staticmethod
    def to_lab(a):
        c = a / 255.0
        c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
        xyz = (c @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T) / np.array([0.95047, 1.0, 1.08883])
        f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
        return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)

    @staticmethod
    def nearest(arr, pal):
        out = np.empty(arr.shape[:2], int)
        for y in range(0, arr.shape[0], 64):
            out[y:y+64] = ((arr[y:y+64, :, None, :] - pal[None, None]) ** 2).sum(3).argmin(2)
        return out

    @staticmethod
    def merge_specks(out, passes):
        out = out.copy(); h, w = out.shape
        for _ in range(passes):
            P = np.pad(out, 1, constant_values=-2)
            nb = [P[1+dy:1+dy+h, 1+dx:1+dx+w] for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy, dx) != (0, 0)]
            iso = (out >= 0) & (sum((n == out).astype(int) for n in nb) <= 1)      # a cell with at most 1 same-colour neighbour
            if not iso.any(): break
            best, bestc = np.full(out.shape, -1), np.zeros(out.shape, int)
            for c in np.unique(out[out >= 0]):
                cnt = sum((n == c).astype(int) for n in nb); better = cnt > bestc
                best = np.where(better, c, best); bestc = np.where(better, cnt, bestc)
            out = np.where(iso & (bestc >= 2), best, out)
        return out

    def build_grid(self):
        if self.img is None or self.canvas_box is None: raise ValueError("Add a reference image and select the canvas first.")
        g = {k: v.get() for k, v in self.v.items()}
        step, mode, b = self.step_px(), self.eff_mode(), self.canvas_box
        cols, rows = (b[2] - b[0]) // step, (b[3] - b[1]) // step
        if cols < 2 or rows < 2: raise ValueError("Canvas too small for this brush size.")
        im = self.img
        if g["rot"] != "0°": im = im.rotate(-int(g["rot"][:-1]), expand=True)
        if g["flipx"]: im = ImageOps.mirror(im)
        if g["flipy"]: im = ImageOps.flip(im)
        sz = g["scale"] / 100.0
        if g["fit"].startswith("Fit"): sc = min(cols / im.width, rows / im.height) * sz; w, h = im.width * sc, im.height * sc
        else: w, h = cols * sz, rows * sz
        w, h = max(1, min(int(w), 1500)), max(1, min(int(h), 1500))
        big = 3 if mode == "Line art" else 1
        rs = Image.BOX if w * big <= im.width and h * big <= im.height else Image.BICUBIC   # area-average when shrinking
        bg = Image.new("RGBA", (w * big, h * big), (255, 255, 255, 0)); bg.alpha_composite(im.resize((w * big, h * big), rs))
        alpha = np.array(bg)[:, :, 3] > 40
        rgb = bg.convert("RGB")
        if g["blur"] > 0: rgb = rgb.filter(ImageFilter.GaussianBlur(g["blur"] * big))
        rgb = ImageEnhance.Color(ImageEnhance.Brightness(rgb).enhance(g["bright"])).enhance(g["sat"])
        arr = np.clip((np.array(rgb).astype(float) - 128) * g["contrast"] + 128, 0, 255)
        if g["invert"]: arr = 255 - arr
        gray, thr = arr.mean(2), g["thr"]
        if mode == "Line art":
            e = np.array(Image.fromarray(gray.astype("uint8")).filter(ImageFilter.FIND_EDGES))
            e = np.array(Image.fromarray(e).resize((w, h), Image.BOX)).astype(float)
            out = np.where((e > thr / 4) & alpha[::big, ::big][:h, :w], 0, -1)
        elif mode == "Black & white":
            out = np.where((gray < thr) & alpha, 0, -1)
        else:
            if not self.palette: raise ValueError("Add colours first, or switch mode to Black & white.")
            pal = np.array([p["rgb"] for p in self.palette], float)
            if g["dither"]:
                a = arr.copy(); out = np.zeros((h, w), int)
                for y in range(h):
                    for x in range(w):
                        old = a[y, x]; i = int(((pal - old) ** 2).sum(1).argmin()); out[y, x] = i; err = old - pal[i]
                        if x + 1 < w: a[y, x+1] += err * 7 / 16
                        if y + 1 < h:
                            if x > 0: a[y+1, x-1] += err * 3 / 16
                            a[y+1, x] += err * 5 / 16
                            if x + 1 < w: a[y+1, x+1] += err / 16
            else: out = self.nearest(self.to_lab(arr), self.to_lab(pal)) if g["labmatch"] else self.nearest(arr, pal)
            skip = ~alpha
            if g["skipwhite"]: skip |= arr.min(2) > 235
            out = np.where(skip, -1, out)
        out = self.merge_specks(out, int(g["despeckle"]))
        full = -np.ones((rows, cols), int)
        oy, ox = (rows - h) // 2 + int(g["offy"] / 100 * rows), (cols - w) // 2 + int(g["offx"] / 100 * cols)
        sy, sx, dy, dx = max(0, -oy), max(0, -ox), max(0, oy), max(0, ox)
        hh, ww = min(h - sy, rows - dy), min(w - sx, cols - dx)
        if hh > 0 and ww > 0: full[dy:dy+hh, dx:dx+ww] = out[sy:sy+hh, sx:sx+ww]
        return full, step

    def runs_from(self, grid, g):
        vert, serp = g["scan"] == "Vertical", g["scan"] == "Serpentine"
        mat = grid.T if vert else grid; runs = []
        for r in range(mat.shape[0]):
            d = np.diff(np.concatenate(([0], mat[r].astype(np.int8), [0])))
            rs = list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1) - 1))
            if serp and r % 2: rs = [(e, s) for s, e in reversed(rs)]
            for s, e in rs:
                s, e = int(s), int(e); runs.append(((r, s), (r, e)) if vert else ((s, r), (e, r)))
        return runs

    @staticmethod
    def erode(m, k):
        for _ in range(k):
            p = np.pad(m, 1, constant_values=False)
            m = p[1:-1, 1:-1] & p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:] & p[:-2, :-2] & p[:-2, 2:] & p[2:, :-2] & p[2:, 2:]
        return m

    @staticmethod
    def by_row(per_colour, cis, vert):
        rows = {}
        for c, runs in per_colour:
            for run in runs: rows.setdefault(run[0][0] if vert else run[0][1], {}).setdefault(c, []).append(run)
        out = []
        for i, key in enumerate(sorted(rows)):
            cs = [c for c in cis if c in rows[key]]
            if i % 2: cs.reverse()      # alternate colour order so one row ends on the colour the next row starts with
            out += [(c, rows[key][c]) for c in cs]
        return out

    def make_plan(self, idx, g, mode, s0):
        """Returns layers (big brush -> small brush). A big-brush layer only paints blocks that are ONE colour and not yet
        painted, so strokes never run over other colours; whatever is left is filled by the smaller brushes."""
        pal = mode == "Palette colours"; rows, cols = idx.shape
        cis = list(range(len(self.palette))) if pal else [0]
        counts = {c: int((idx == c).sum()) for c in cis}; cis = [c for c in cis if counts[c] > 0]
        lum = lambda c: sum(self.palette[c]["rgb"]) if pal else 0
        o = g["corder"]
        if o == "Lightest first": cis.sort(key=lum, reverse=True)
        elif o == "Darkest first": cis.sort(key=lum)
        elif o == "Most pixels first": cis.sort(key=lambda c: -counts[c])
        elif o == "Fewest pixels first": cis.sort(key=lambda c: counts[c])
        layers = [(b, self.eff(b["px"])) for b in self.active_brushes()] or [(None, s0)]
        done = np.zeros(idx.shape, bool); fy = np.arange(rows) * s0 + s0 / 2; fx = np.arange(cols) * s0 + s0 / 2
        vert = g["scan"] == "Vertical"; out = []
        for li, (br, p) in enumerate(layers):
            last = li == len(layers) - 1; per_colour = []; before_done = done.copy()
            if not last:
                R, C = (rows * s0) // p, (cols * s0) // p
                ys = np.minimum((fy // p).astype(int), R); xs = np.minimum((fx // p).astype(int), C)
                tot = np.zeros((R + 1, C + 1), int); np.add.at(tot, (ys[:, None], xs[None, :]), 1)
            for c in cis:
                mask = (idx == c) & ~done
                if not mask.any(): continue
                if last: grid = mask; done |= mask
                else:
                    me = mask & self.erode(idx == c, int(g["margin"]))      # keep clear of other colours / the canvas edge
                    cnt = np.zeros((R + 1, C + 1), int); np.add.at(cnt, (ys[:, None], xs[None, :]), me.astype(int))
                    full = (cnt == tot) & (tot > 0); full[R, :] = False; full[:, C] = False
                    pad = np.pad(full, 1)   # lone cells are left for finer brushes (a round tip would leave gaps)
                    full &= (pad[:-2, 1:-1] | pad[2:, 1:-1]) if vert else (pad[1:-1, :-2] | pad[1:-1, 2:])
                    done |= mask & full[ys[:, None], xs[None, :]]; grid = full[:R, :C]
                runs = self.runs_from(grid, g)
                if runs: per_colour.append((c, runs))
            if last and g["order"].startswith("One row"): per_colour = self.by_row(per_colour, cis, vert)
            w_, cap_ = self.geom(br)
            out.append({"brush": br, "step": s0 if last else p, "colours": per_colour, "mask": done & ~before_done, "w": w_, "cap": cap_})
        return out

    def timing(self):
        s = self.spd / 100.0
        return 0.06 * (1 - s) ** 2, 0.0005 + 0.02 * (1 - s) ** 2   # pause after each stroke, delay between mouse-move events

    def sched_prev(self, *a):
        if self.pid: self.after_cancel(self.pid)
        self.pid = self.after(300, lambda: self.img is not None and self.canvas_box and self.preview())

    def preview(self):
        try: self.idx, step = self.build_grid()
        except ValueError as e: return self.say(str(e))
        g = {k: v.get() for k, v in self.v.items()}; mode = self.eff_mode()
        self.last_mode = mode; self.last_plan = plan = self.make_plan(self.idx, g, mode, step)
        names = ["All layers"] + [f"Layer {i+1} · {l['step']}px" for i, l in enumerate(plan)]
        self.layer_cb["values"] = names
        if self.v["showlayer"].get() not in names: self.v["showlayer"].set("All layers")
        self.render_preview()
        n, plen = 0, 0
        for l in plan:
            for _, runs in l["colours"]:
                for a, b in runs: n += 1; plen += (abs(b[0] - a[0]) + abs(b[1] - a[1])) * l["step"]
        pause, iv = self.timing(); est = n * (2 * pause + 0.03) + plen / max(1, g["maxstep"] or 8) * (iv + 0.0004)
        info = "   |   ".join(f"L{i+1}: {l['step']}px x{sum(len(r) for _, r in l['colours'])}" for i, l in enumerate(plan))
        if g["order"].startswith("Layers") and len(self.active_brushes()) < 2:
            info = "Layers need 2+ measured brush sizes (Brush card: click brush buttons, then Auto-measure). Drawing one colour at a time until then.   " + info
        elif g["order"].startswith("One row"): info = "Row by row: each row is finished (all its colours) before the next.   " + info
        self.layer_lbl.config(text=info)
        self.say(f"{mode} | {len(plan)} layer(s) | {n} strokes | est. ~{int(est//60)}m {int(est%60)}s at current speed")

    def render_preview(self):
        if self.idx is None or not self.last_plan: return
        cols = [p["rgb"] for p in self.palette] if self.last_mode == "Palette colours" else [(0, 0, 0)]
        names = list(self.layer_cb["values"]); sel = self.v["showlayer"].get(); show, bgc = self.idx, 255
        if sel in names and names.index(sel) > 0:
            show = np.where(self.last_plan[names.index(sel) - 1]["mask"], self.idx, -1); bgc = 225
        px = np.full((*self.idx.shape, 3), bgc, np.uint8)
        for i, c in enumerate(cols): px[show == i] = c
        im = Image.fromarray(px); sc = min(560 / im.width, 660 / im.height)
        im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.NEAREST)
        self.tkp = ImageTk.PhotoImage(im); self.prev.config(image=self.tkp, text="")

    # ---------- drawing ----------
    def click(self, m, x, y, wait=0.15):
        m.move(x, y); time.sleep(0.06); m.down(); time.sleep(0.06); m.up(); time.sleep(wait)

    def stroke(self, m, xa, ya, xb, yb, g, interval):
        k = getattr(self, "slow", 1.0); j = g.get("jitter", 0) / 100.0
        rj = (lambda: 1.0 + random.uniform(-j, j)) if j else (lambda: 1.0)       # random timing wobble so strokes don't line up with the game's frames
        hold, settle, lift = g["hold"] / 1000.0 * k * rj(), g["settle"] / 1000.0 * k * rj(), g["lift"] / 1000.0 * k * rj()
        dist = math.hypot(xb - xa, yb - ya)
        n = max(1, int(g["dragpts"]), math.ceil(dist / g["maxstep"]) if g["maxstep"] > 0 else 1)
        m.move(xa, ya); time.sleep(0.004)
        m.down(g["button"]); time.sleep(hold)
        if dist == 0:
            if g["nudge"]: m.move(xa + 1, ya); time.sleep(0.003); m.move(xa, ya)
        else:
            for i in range(1, n + 1):
                m.move(xa + (xb - xa) * i / n, ya + (yb - ya) * i / n); time.sleep(interval)
            m.move(xb, yb)          # repeat the final point so an app can't drop the tail of the stroke
        time.sleep(settle); m.up(g["button"]); time.sleep(lift)

    def glide(self, m, xa, ya, xb, yb, steps=30):
        for i in range(1, steps + 1): m.move(xa + (xb - xa) * i / steps, ya + (yb - ya) * i / steps); time.sleep(0.01)

    def trace(self):
        if not self.canvas_box: return messagebox.showinfo("Canvas", "Select the canvas first.")
        b = self.canvas_box; g = {k: v.get() for k, v in self.v.items()}; self.iconify()
        def go():
            try:
                time.sleep(2.5); m = Mouse(g["input"].startswith("Windows")); m.move(b[0], b[1])
                pts = [(b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3]), (b[0], b[1])]
                for p, q in zip(pts, pts[1:]): self.glide(m, *p, *q)
            except Exception: pass
            self.after(0, self.deiconify)
        threading.Thread(target=go, daemon=True).start()

    def test_stroke(self):
        if not self.canvas_box: return messagebox.showinfo("Canvas", "Select the canvas first.")
        g = {k: v.get() for k, v in self.v.items()}; brush = self.cur_brush(); b = self.canvas_box
        messagebox.showinfo("Test line", "Click OK, then switch to your drawing app.\nIn 3 seconds I'll draw one line and one dot across the middle of your canvas.")
        self.iconify()
        def go():
            msg = "Test finished: did a line and a dot appear? If not, set Mouse input to PyAutoGUI, or run as administrator."
            try:
                time.sleep(3); m = Mouse(g["input"].startswith("Windows"))
                if brush: self.click(m, *brush["pos"], g["swdelay"])
                if self.palette: self.click(m, *self.palette[0]["pos"], g["swdelay"])
                cy, w = (b[1] + b[3]) // 2, b[2] - b[0]
                self.stroke(m, b[0] + w * 0.2, cy, b[0] + w * 0.8, cy, g, 0.004)
                self.stroke(m, b[0] + w * 0.5, cy + 50, b[0] + w * 0.5, cy + 50, g, 0.004)
            except Exception as ex: msg = f"Test error: {ex}"
            self.after(0, self.deiconify); self.after(0, self.say, msg)
        threading.Thread(target=go, daemon=True).start()

    def open_mini(self):
        m = self.mini = tk.Toplevel(self); m.title("Auto Drawer"); m.attributes("-topmost", True); m.configure(bg=CARD); m.resizable(False, False)
        w, h = 290, 175; x, y, blocked = self.mini_place(w, h); self.panel_blocked = blocked
        m.geometry(f"{w}x{h}+{x}+{y}"); self.park_pt = (x + w // 2, y + h // 2)
        m.protocol("WM_DELETE_WINDOW", lambda: setattr(self, "stop", True))
        self.mt = tk.StringVar(value="Starting...")
        ttk.Label(m, textvariable=self.mt, wraplength=270).pack(padx=10, pady=(8, 4), anchor="w")
        self.pb = ttk.Progressbar(m, maximum=100); self.pb.pack(fill="x", padx=10)
        r = ttk.Frame(m); r.pack(fill="x", padx=10, pady=6)
        self.pbtn = ttk.Button(r, text="Pause", command=lambda: setattr(self, "paused", not self.paused)); self.pbtn.pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(r, text="Stop", command=lambda: setattr(self, "stop", True)).pack(side="left", expand=True, fill="x", padx=2)
        r = ttk.Frame(m); r.pack(fill="x", padx=10); ttk.Label(r, text="Speed").pack(side="left")
        ttk.Scale(r, from_=1, to=100, variable=self.v["speed"]).pack(side="left", fill="x", expand=True, padx=6)
        k = self.keys
        ttk.Label(m, text=("Click-through (it overlaps your canvas) - use hotkeys:\n" if blocked else "") + f"{k['pause'].upper()} pause · {k['slower'].upper()} slower · {k['faster'].upper()} faster · {k['stop'].upper()} stop", foreground="#999", wraplength=270).pack(pady=4)
        m.update_idletasks()
        if sys.platform == "win32":
            try:
                if blocked: m.attributes("-alpha", 0.85)
                u = ctypes.windll.user32; hwnd = u.GetParent(m.winfo_id()) or m.winfo_id(); st = u.GetWindowLongW(hwnd, -20)
                st |= 0x08000000 | 0x80                    # never take focus away from your drawing app
                if blocked: st |= 0x80000 | 0x20           # click-through so strokes pass over the panel
                u.SetWindowLongW(hwnd, -20, st)
            except Exception: pass

    def panel_vis(self, show):
        if self.mini and getattr(self, "panel_blocked", False):
            self.after(0, lambda: self.mini and (self.mini.deiconify() if show else self.mini.withdraw()))

    def set_progress(self, frac, text):
        if not self.mini: return
        if frac is not None: self.pb["value"] = frac * 100
        self.mt.set(text); self.pbtn.config(text="Resume" if self.paused else "Pause")

    def ui(self, text, frac=None): self.after(0, self.set_progress, frac, text)

    def log(self, msg):
        try:
            with open(os.path.join(os.path.expanduser("~"), "autodrawer.log"), "a") as f: f.write(time.strftime("%H:%M:%S ") + msg + "\n")
        except Exception: pass

    def start(self, repair_only=False):
        if self.drawing: return
        if self.img is None or self.canvas_box is None: return messagebox.showinfo("Setup", "Add a reference image and select the canvas first.")
        try: self.idx, _ = self.build_grid()
        except ValueError as e: return messagebox.showinfo("Setup", str(e))
        g = {k: v.get() for k, v in self.v.items()}
        need = (not repair_only) and g["autobrush"] and not self.active_brushes()
        self.stop = self.paused = False; self.drawing = True
        self.open_mini()
        if g["minimize"]: self.withdraw()
        threading.Thread(target=self.pre, args=(g, need, repair_only), daemon=True).start()

    def pre(self, g, need, repair_only):
        px, note, cap = None, "", None
        try:
            for s in range(g["countdown"], 0, -1):
                if self.stop: raise KeyboardInterrupt
                self.ui(f"Starting in {s}s - click on your drawing app now!"); time.sleep(1)
            if need:
                self.ui("Detecting your brush width with a test line...")
                m = Mouse(g["input"].startswith("Windows")); b = self.canvas_box
                px, uf, cap = self.test_line(m, g, (b[1] + b[3]) // 2, int(min(150, max(6, (b[3] - b[1]) / 4))), None)
                if px and not (1 <= px <= min(b[2] - b[0], b[3] - b[1]) / 3): px = None
                note = (f"Detected brush width: {px}px. " if px else "Couldn't detect the brush width, using the manual value. ") + ("Couldn't undo the test line. " if uf else "")
        except KeyboardInterrupt: self.drawing = False; return self.after(0, self.finish, "Stopped.", False)
        except pyautogui.FailSafeException: self.drawing = False; return self.after(0, self.finish, "Stopped (failsafe corner).", False)
        except Exception as ex:
            self.log(traceback.format_exc()); self.drawing = False; return self.after(0, self.finish, f"Error: {ex}", False)
        self.after(0, self.go, g, px, note, repair_only, cap)

    def go(self, g, px, note, repair_only, cap=None):
        if px: self.v["step"].set(px)
        self.cur_cap = cap if px else None
        g = {k: v.get() for k, v in self.v.items()}
        try: self.idx, step = self.build_grid(); mode = self.eff_mode(); plan = self.make_plan(self.idx, g, mode, step)
        except ValueError as e: self.drawing = False; return self.finish(f"Error: {e}", False)
        if not any(l["colours"] for l in plan): self.drawing = False; return self.finish("Nothing to draw with these settings.", False)
        self.say(note + f"Drawing {len(plan)} layer(s), finest step {step}px.")
        threading.Thread(target=self.run, args=(plan, g, mode, step, self.idx.copy(), repair_only), daemon=True).start()

    def gate(self):
        if tuple(pyautogui.position()) == (0, 0): raise pyautogui.FailSafeException()
        if self.stop: raise KeyboardInterrupt
        if self.paused:
            p0 = time.time(); self.ui("Paused - press your pause key or the Resume button")
            while self.paused and not self.stop: time.sleep(0.1)
            self.t0 += time.time() - p0
            if self.stop: raise KeyboardInterrupt

    def painted(self, mx, my, want_rgb, pre=None, tol=35):
        """Palette mode: the spot shows the wanted colour. Single-colour mode: the spot changed since `pre`."""
        im = np.array(self.snap((int(mx) - 3, int(my) - 3, int(mx) + 4, int(my) + 4))).astype(float).reshape(-1, 3).mean(0)
        if want_rgb is not None: return float(np.linalg.norm(self.to_lab(im) - self.to_lab(np.array(want_rgb, float)))) < tol
        return pre is None or float(np.linalg.norm(self.to_lab(im) - self.to_lab(pre))) > 12

    def verify_colour(self, mx, my, rgb, tol=45):
        time.sleep(0.05)
        im = np.array(self.snap((int(mx) - 3, int(my) - 3, int(mx) + 4, int(my) + 4))).astype(float).reshape(-1, 3).mean(0)
        return float(np.linalg.norm(self.to_lab(im) - self.to_lab(np.array(rgb, float)))) < tol, im

    def park(self, m):
        if self.park_pt: m.move(*self.park_pt)

    def observe(self, rows, cols, s0):
        """Average colour of the centre of every grid cell on the live canvas."""
        try:
            img = np.array(self.snap(tuple(self.canvas_box))).astype(float)
            if img.shape[0] < rows * s0 or img.shape[1] < cols * s0: return None
            a = img[:rows * s0, :cols * s0].reshape(rows, s0, cols, s0, 3); lo = s0 // 4; hi = max(lo + 1, s0 - lo)
            return a[:, lo:hi, :, lo:hi].mean((1, 3))
        except Exception: self.log(traceback.format_exc()); return None

    def find_missing(self, idx, obs, before, pal_rgb, tol, gaps_only=False):
        lab = self.to_lab(obs); want = idx >= 0
        if pal_rgb:
            exp = np.array(pal_rgb, float); labb = self.to_lab(before) if before is not None else None
            for c in range(len(exp)):      # learn how each palette colour really looks on this canvas
                cells = idx == c
                if labb is not None: cells = cells & (np.linalg.norm(lab - labb, axis=2) > 12)
                sel = cells & (np.linalg.norm(lab - self.to_lab(exp[c]), axis=2) < 45)
                if sel.sum() >= 5: exp[c] = np.median(obs[sel], axis=0)
            ok = np.linalg.norm(lab - self.to_lab(exp)[np.clip(idx, 0, None)], axis=2) < tol
        else:
            if before is None: return np.zeros(idx.shape, bool)
            ok = np.linalg.norm(lab - self.to_lab(before), axis=2) > 12
        miss = want & ~ok
        if gaps_only and before is not None: miss &= np.linalg.norm(lab - self.to_lab(before), axis=2) < 15   # still blank = a real gap
        return miss

    def fine_layer(self, idx_m, s0, g, brush, mode):
        cis = [c for c in (range(len(self.palette)) if mode == "Palette colours" else [0]) if (idx_m == c).any()]
        return {"brush": brush, "step": s0, "colours": [(c, self.runs_from(idx_m == c, g)) for c in cis]}

    def run(self, plan, g, mode, s0, idx, repair_only=False):
        msg, m = "Done!", None
        try:
            m = Mouse(g["input"].startswith("Windows")); bx, by = self.canvas_box[:2]; pal = mode == "Palette colours"
            rows, cols = idx.shape; want = max(1, int((idx >= 0).sum()))
            self.park(m); time.sleep(0.2)
            before = self.last_before if repair_only else self.observe(rows, cols, s0)
            if before is not None and before.shape[:2] != idx.shape: before = None
            if not repair_only: self.last_before = before
            weight = lambda a, b, p: 1 + (abs(b[0] - a[0]) + abs(b[1] - a[1])) * p / 16.0
            total = max(1.0, sum(weight(a, b, l["step"]) for l in plan for _, rs in l["colours"] for a, b in rs))
            st = {"done": 0.0, "last": 0.0}; self.t0 = time.time()

            pal_all = [p["rgb"] for p in self.palette]; warns = {"brush": 0, "colour": 0, "guard": 0}; expo = {}
            gs = {"ema": 0.0, "since": 0, "consec": 0, "off": False, "n": 0, "peak": 1.0}; self.slow = 1.0

            def draw(layers, tag, track=True):
                nonlocal g
                for li, layer in enumerate(layers):
                    p, br, w, cap = layer["step"], layer["brush"], layer["w"], layer["cap"]
                    if not layer["colours"]: continue
                    self.gate()
                    if br: self.click(m, *br["pos"], g["swdelay"] * self.slow); time.sleep(g["layerdelay"] / 1000.0 * self.slow)
                    st["col"] = None; bdone = False
                    for ci, runs in layer["colours"]:
                        self.gate()
                        switched = pal and (st["col"] != ci or g["rebrush"])
                        if switched: self.click(m, *self.palette[ci]["pos"], g["swdelay"] * self.slow)
                        if br and g["rebrush"]: self.click(m, *br["pos"], g["swdelay"] * self.slow)
                        st["col"] = ci; cdone = not (switched and g["verify"])
                        for a, b in runs:
                            t_s = time.time(); self.gate(); pause, interval = self.timing()
                            if g["mvint"] > 0: interval = g["mvint"] / 1000.0
                            x1, y1, x2, y2 = self.endpoints(a, b, p, w, cap, bx, by); mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                            first_in_block = not cdone; gs["n"] += 1
                            due = (not gs["off"]) and (not first_in_block) and (g["guard"] == "Every stroke" or (g["guard"].startswith("Every 6th") and gs["n"] % 6 == 0))
                            want_rgb = expo.get(ci, pal_all[ci]) if pal else None; pre_c = None
                            if due and not pal: pre_c = np.array(self.snap((int(mx) - 3, int(my) - 3, int(mx) + 4, int(my) + 4))).astype(float).reshape(-1, 3).mean(0)
                            chk = br is not None and not bdone and g["verify"] and a[1] == b[1] and abs(b[0] - a[0]) >= 2
                            if chk:
                                H = int(min(120, max(10, w * 1.2))); bx0 = int(mx); box = (bx0 - 3, int(y1) - H, bx0 + 4, int(y1) + H + 1); pre = self.snap(box)
                            self.stroke(m, x1, y1, x2, y2, g, interval)
                            if chk:      # is the brush really the size we think? (catches a missed brush-button click)
                                bdone = True; t = self.measure(pre, self.snap(box), H)
                                if t is not None and abs(t - w) > max(2, 0.3 * w):
                                    warns["brush"] += 1; self.log(f"brush check: expected {w:.0f}px, saw {t}px - re-selecting brush")
                                    self.click(m, *br["pos"], g["swdelay"] * self.slow + 0.3); self.stroke(m, x1, y1, x2, y2, g, interval)
                            if not cdone:      # did the colour click really register?
                                cdone = True; okc, got = self.verify_colour(mx, my, want_rgb)
                                if not okc:
                                    self.click(m, *self.palette[ci]["pos"], g["swdelay"] * self.slow + 0.25); self.stroke(m, x1, y1, x2, y2, g, interval)
                                    ok2, got2 = self.verify_colour(mx, my, want_rgb)
                                    if not ok2:
                                        if float(np.linalg.norm(self.to_lab(got) - self.to_lab(got2))) < 12: expo[ci] = tuple(got2)   # app's colour just differs from its swatch
                                        else:
                                            warns["colour"] += 1; g = dict(g); g["swdelay"] = min(1.0, g["swdelay"] + 0.15)
                                            self.log(f"colour check failed for colour {ci}: saw {got2.round()}")
                            if due:            # lag guard: did this stroke really appear? if not, draw it again
                                time.sleep(g["checkdelay"] / 1000.0 * self.slow)
                                first_failed = not self.painted(mx, my, want_rgb, pre_c); failed = first_failed; tries = 0
                                while failed and tries < g["retries"]:
                                    tries += 1
                                    if tries >= 2 and pal: self.click(m, *self.palette[ci]["pos"], g["swdelay"] * self.slow + 0.1)
                                    self.stroke(m, x1, y1, x2, y2, g, interval); time.sleep(g["checkdelay"] / 1000.0 * self.slow * (1 + tries))
                                    failed = not self.painted(mx, my, want_rgb, pre_c)
                                gs["consec"] = gs["consec"] + 1 if failed else 0
                                if gs["consec"] >= 8: gs["off"] = True; warns["guard"] += 1; self.log("lag guard switched off: spots never verify (colour mismatch?)")
                                gs["ema"] = 0.9 * gs["ema"] + 0.1 * (1.0 if first_failed else 0.0); gs["since"] += 1
                                if gs["ema"] > 0.25 and self.slow < 3.0:
                                    self.slow = min(3.0, self.slow * 1.2); gs["peak"] = max(gs["peak"], self.slow); gs["ema"] = 0.12; gs["since"] = 0
                                    self.log(f"lag detected - slowing timing to x{self.slow:.2f}")
                                elif gs["ema"] < 0.06 and self.slow > 1.0 and gs["since"] > 25: self.slow = max(1.0, self.slow / 1.15); gs["since"] = 0
                            extra = max(pause + g["gap"] / 1000.0 * self.slow, (1.0 / g["rate"] if g["rate"] > 0 else 0.0) - (time.time() - t_s))
                            if extra > 0: time.sleep(extra)
                            if track:
                                st["done"] += weight(a, b, p)
                                if time.time() - st["last"] > 0.25:
                                    st["last"] = time.time(); rem = (st["last"] - self.t0) / st["done"] * (total - st["done"])
                                    self.ui(f"{tag} {li+1}/{len(layers)} | {int(st['done']*100//total)}% | {int(rem//60)}m {int(rem%60)}s left | speed {int(self.spd)}" + (f" | lag x{self.slow:.1f}" if self.slow > 1.05 else ""), st["done"] / total)

            if not repair_only: draw(plan, "Layer")
            passes = max(1, int(g["repair"])) if repair_only else int(g["repair"])
            if repair_only and not pal and before is None: msg = "Repair needs Palette colours mode, or a drawing run first in this session."; passes = 0
            finest = (self.active_brushes() or [None])[-1]; pal_rgb = [p["rgb"] for p in self.palette] if pal else None

            def look():
                self.panel_vis(False); time.sleep(0.25 if getattr(self, "panel_blocked", False) else 0.05)
                o = self.observe(rows, cols, s0); self.panel_vis(True); return o

            final, prev = None, None
            for ps in (range(passes + 1) if passes else []):
                self.gate(); self.ui(f"Checking the canvas ({ps+1}/{passes+1})...", 1.0)
                self.park(m); time.sleep(0.3)
                obs = look()
                if obs is None: msg = "Done (couldn't read the canvas to check it)."; break
                allm = self.find_missing(idx, obs, before, pal_rgb, g["tol"], False)
                gaps = self.find_missing(idx, obs, before, pal_rgb, g["tol"], True) if before is not None else allm
                final = int(allm.sum()); wrong = final - int(gaps.sum())
                miss = allm if (g["fixwrong"] or wrong > 0.03 * want) else gaps      # wrong colours are only redrawn when there are lots (a real failure, not edge noise)
                n = int(miss.sum())
                self.log(f"check {ps+1}: {final} of {want} spots off ({n} to repair) (speed {int(self.spd)}, hold {g['hold']}, settle {g['settle']}, step {g['maxstep']})")
                if not repair_only and ps == 0 and final / want > 0.97: final = None; msg = "Done (the canvas check didn't match what was drawn, so repair was skipped)."; break
                if n <= max(2, 0.002 * want) or ps == passes: break
                if (prev is not None and n > 0.6 * prev) or n / want > 0.25:      # not converging -> slow down, be more careful
                    g = dict(g); g["hold"] = min(150, g["hold"] + 10); g["settle"] = min(150, g["settle"] + 10); g["lift"] = min(200, g["lift"] + 15); g["maxstep"] = max(3, (g["maxstep"] or 8) // 2)
                    self.spd = max(5.0, self.spd * 0.6); self.after(0, self.v["speed"].set, self.spd)
                    self.ui(f"Gaps remain - slowing down to speed {int(self.spd)} and repairing {n} spots...", 1.0)
                else: self.ui(f"Repairing {n} missing spots (pass {ps+1}/{passes})...", 1.0)
                prev = n
                fl = self.fine_layer(np.where(miss, idx, -1), s0, g, finest, mode); fl["w"], fl["cap"] = plan[-1]["w"], plan[-1]["cap"]
                draw([fl], "Repair", False)
            if final is not None:
                msg = f"Done! {100 * (1 - final / want):.1f}% of the image matches ({final} spots still blank or wrong)." if final else "Done! Checked the canvas: everything matches."
                if final > 0.02 * want: msg += " Gaps remain: try Auto-tune speed (Speed tab) or lower the speed."
            if gs["peak"] > 1.05 and msg.startswith("Done"): msg += f" (lag guard slowed the timing up to x{gs['peak']:.1f})"
            if warns["guard"] and msg.startswith("Done"): msg += " (lag guard switched itself off: check that the swatch colours match what the game draws)"
            if (warns["brush"] or warns["colour"]) and msg.startswith("Done"): msg += f" (brush/colour selection needed {warns['brush'] + warns['colour']} retries - try the Careful preset)"
        except KeyboardInterrupt: msg = "Stopped."
        except pyautogui.FailSafeException: msg = "Stopped (failsafe corner)."
        except Exception as ex: self.log(traceback.format_exc()); msg = f"Error: {ex}"
        finally:
            try: m and m.up(g["button"])
            except Exception: pass
            self.slow = 1.0; self.drawing = False; self.after(0, self.finish, msg, g["beep"])

    def finish(self, msg, beep):
        if self.mini: self.mini.destroy(); self.mini = None
        self.deiconify(); self.say(msg)
        if msg.startswith("Error"): messagebox.showerror("Auto Drawer", msg + "\n\nDetails are saved in autodrawer.log in your user folder.")
        elif beep and msg.startswith("Done"):
            try:
                import winsound; winsound.MessageBeep()
            except Exception: self.bell()

    # ---------- setup files ----------
    def cfg_dict(self):
        return {"ver": 7, "canvas": self.canvas_box, "palette": self.palette, "brushes": self.brushes, "undo_pos": self.undo_pos, "profiles": self.profiles, "settings": {k: v.get() for k, v in self.v.items()}}

    def apply_cfg(self, d):
        self.canvas_box = tuple(d["canvas"]) if d.get("canvas") else None
        self.palette = [{"pos": tuple(x["pos"]), "rgb": tuple(x["rgb"])} for x in d.get("palette", [])]
        self.brushes = [{"pos": tuple(x["pos"]), "px": x["px"]} for x in d.get("brushes", [])]
        self.undo_pos = tuple(d["undo_pos"]) if d.get("undo_pos") else None
        self.profiles = dict(d.get("profiles", {}))
        if hasattr(self, "pc"): self.pc["values"] = self.preset_names()
        old = d.get("ver", 0) < 7
        for k, val in d.get("settings", {}).items():
            if old and k in ("hold", "settle", "maxstep", "dragpts", "repair", "lift", "margin", "overlap", "despeckle"): continue
            if k in self.v:
                try: self.v[k].set(val)
                except Exception: pass

    def save_cfg(self):
        p = filedialog.asksaveasfilename(defaultextension=".json")
        if p: json.dump(self.cfg_dict(), open(p, "w"))

    def load_cfg(self):
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if p: self.apply_cfg(json.load(open(p))); self.refresh(); self.sched_prev()

    def quit_app(self):
        try: json.dump(self.cfg_dict(), open(CFG, "w"))
        except Exception: pass
        self.stop = True; self.destroy()


if __name__ == "__main__":
    App().mainloop()
