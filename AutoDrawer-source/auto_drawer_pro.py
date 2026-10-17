"""
Auto Drawer Pro - draws a reference image into any on-screen canvas with your mouse.
Canvas selection is required; colours and brush are optional and independent.
Emergency stop: slam the mouse into a screen corner, or press ESC.
"""
import sys, json, threading, time, os
import tkinter as tk
from tkinter import filedialog, ttk, messagebox, simpledialog
import numpy as np
from PIL import Image, ImageTk, ImageGrab, ImageFilter, ImageEnhance
import pyautogui

if sys.platform == "win32":
    try:
        import ctypes; ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
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
BG, CARD, FG, ACC, OK = "#1e1f26", "#2a2c36", "#e8e8ee", "#4f8cff", "#4ade80"


class App((TkinterDnD.Tk if DND else tk.Tk)):
    def __init__(self):
        super().__init__()
        self.title("Auto Drawer Pro"); self.geometry("1080x760"); self.configure(bg=BG)
        self.img = self.idx = self.canvas_box = None
        self.palette, self.brushes = [], []
        self.stop = self.drawing = False
        V = tk.StringVar, tk.IntVar, tk.DoubleVar, tk.BooleanVar
        self.v = {"mode": V[0](value="Auto"), "fit": V[0](value="Fit (keep ratio)"), "step": V[1](value=6),
                  "thr": V[1](value=110), "contrast": V[2](value=1.0), "delay": V[2](value=0.002),
                  "countdown": V[1](value=4), "dither": V[3](value=False), "skipwhite": V[3](value=True),
                  "brush": V[0](value="")}
        self.style()
        self.build()
        if DND:
            self.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", lambda e: self.load_image(self.tk.splitlist(e.data)[0]))
        if keyboard:
            keyboard.Listener(on_press=lambda k: setattr(self, "stop", True) if k == keyboard.Key.esc else None).start()
        self.refresh()

    # ---------- UI ----------
    def style(self):
        s = ttk.Style(self); s.theme_use("clam")
        s.configure(".", background=CARD, foreground=FG, fieldbackground=BG, font=("Segoe UI", 10))
        s.configure("TFrame", background=CARD); s.configure("TLabel", background=CARD, foreground=FG)
        s.configure("TCheckbutton", background=CARD, foreground=FG)
        s.configure("TButton", background="#3a3d4b", foreground=FG, padding=6, borderwidth=0)
        s.map("TButton", background=[("active", ACC)])
        s.configure("Go.TButton", background=ACC, font=("Segoe UI", 12, "bold"), padding=10)
        s.map("Go.TButton", background=[("active", "#6ba0ff")])
        s.configure("H.TLabel", font=("Segoe UI", 11, "bold"))
        s.configure("TScale", background=CARD); s.configure("TSeparator", background=BG)

    def card(self, parent, title, tag):
        f = ttk.Frame(parent, padding=8); f.pack(fill="x", pady=4)
        h = ttk.Frame(f); h.pack(fill="x")
        ttk.Label(h, text=title, style="H.TLabel").pack(side="left")
        st = ttk.Label(h, text=tag, foreground="#999"); st.pack(side="right")
        return f, st

    def build(self):
        left = tk.Frame(self, bg=BG, width=380); left.pack(side="left", fill="y", padx=8, pady=4)
        left.pack_propagate(False)
        right = tk.Frame(self, bg=BG); right.pack(side="right", fill="both", expand=True, padx=8, pady=8)

        f, self.st_img = self.card(left, "Reference image", "required")
        self.drop = tk.Label(f, text="Drop image here or click to browse", bg=BG, fg="#aaa", height=3, relief="flat", cursor="hand2")
        self.drop.pack(fill="x", pady=4); self.drop.bind("<Button-1>", lambda e: self.browse())

        f, self.st_canvas = self.card(left, "1  Canvas area", "required")
        ttk.Button(f, text="Select canvas (drag a box)", command=self.sel_canvas).pack(fill="x")
        self.l_canvas = ttk.Label(f, text="Not set", foreground="#999"); self.l_canvas.pack(anchor="w")

        f, self.st_col = self.card(left, "2  Colours", "optional")
        r = ttk.Frame(f); r.pack(fill="x")
        ttk.Button(r, text="Select palette box (auto-find)", command=self.sel_palette).pack(side="left", expand=True, fill="x")
        ttk.Button(r, text="Click swatches", command=self.click_swatches).pack(side="left", expand=True, fill="x", padx=(4, 0))
        self.chips = tk.Frame(f, bg=CARD); self.chips.pack(fill="x", pady=4)
        ttk.Button(f, text="Clear colours", command=lambda: (self.palette.clear(), self.refresh())).pack(anchor="e")

        f, self.st_br = self.card(left, "3  Brush size", "optional")
        ttk.Button(f, text="Click brush-size buttons", command=self.click_brushes).pack(fill="x")
        r = ttk.Frame(f); r.pack(fill="x", pady=3)
        ttk.Label(r, text="Use:").pack(side="left")
        self.cb = ttk.Combobox(r, textvariable=self.v["brush"], state="readonly", width=22); self.cb.pack(side="left", padx=4)
        ttk.Button(r, text="Clear", command=lambda: (self.brushes.clear(), self.refresh()), width=6).pack(side="right")
        r = ttk.Frame(f); r.pack(fill="x")
        ttk.Label(r, text="Manual step px:").pack(side="left")
        ttk.Spinbox(r, from_=1, to=60, textvariable=self.v["step"], width=5).pack(side="left", padx=4)

        f, _ = self.card(left, "Options", "")
        def row(lbl, w):
            r = ttk.Frame(f); r.pack(fill="x", pady=1); ttk.Label(r, text=lbl, width=14).pack(side="left"); w.pack(side="left", fill="x", expand=True)
        row("Mode", ttk.Combobox(f, textvariable=self.v["mode"], state="readonly", values=["Auto", "Palette colours", "Black & white", "Line art"]))
        row("Fit", ttk.Combobox(f, textvariable=self.v["fit"], state="readonly", values=["Fit (keep ratio)", "Stretch to canvas"]))
        row("Threshold", ttk.Scale(f, from_=5, to=250, variable=self.v["thr"], command=lambda e: None))
        row("Contrast", ttk.Scale(f, from_=0.5, to=2.5, variable=self.v["contrast"]))
        row("Delay (s)", ttk.Spinbox(f, from_=0, to=0.2, increment=0.001, textvariable=self.v["delay"], width=6))
        row("Countdown (s)", ttk.Spinbox(f, from_=1, to=15, textvariable=self.v["countdown"], width=6))
        ttk.Checkbutton(f, text="Dither colours", variable=self.v["dither"]).pack(anchor="w")
        ttk.Checkbutton(f, text="Skip white (keep canvas background)", variable=self.v["skipwhite"]).pack(anchor="w")

        r = tk.Frame(left, bg=BG); r.pack(fill="x", pady=4)
        for t, c in (("Preview", self.preview), ("Trace outline", self.trace)):
            ttk.Button(r, text=t, command=c).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(r, text="Save", command=self.save_cfg, width=6).pack(side="left", padx=2)
        ttk.Button(r, text="Load", command=self.load_cfg, width=6).pack(side="left", padx=2)
        ttk.Button(left, text="START DRAWING", style="Go.TButton", command=self.start).pack(fill="x", padx=2, pady=4)
        self.status = tk.Label(left, text="Ready", bg=BG, fg="#aaa", wraplength=360, justify="left"); self.status.pack(anchor="w")

        self.prev = tk.Label(right, text="Preview", bg="#15161b", fg="#666"); self.prev.pack(fill="both", expand=True)

    def say(self, t): self.status.config(text=t); self.update_idletasks()

    def refresh(self):
        def mark(lbl, ok, opt=False):
            lbl.config(text="✔ set" if ok else ("optional" if opt else "required"), foreground=OK if ok else "#999")
        mark(self.st_img, self.img is not None); mark(self.st_canvas, self.canvas_box is not None)
        mark(self.st_col, bool(self.palette), True); mark(self.st_br, bool(self.brushes), True)
        b = self.canvas_box
        self.l_canvas.config(text=f"{b[2]-b[0]} x {b[3]-b[1]} px at ({b[0]}, {b[1]})" if b else "Not set")
        for w in self.chips.winfo_children(): w.destroy()
        for i, p in enumerate(self.palette):
            l = tk.Label(self.chips, text="", bg="#%02x%02x%02x" % p["rgb"], width=3, height=1, cursor="X_cursor")
            l.pack(side="left", padx=1, pady=1); l.bind("<Button-1>", lambda e, i=i: (self.palette.pop(i), self.refresh()))
        names = [f"Brush {i+1}: {b['px']}px" for i, b in enumerate(self.brushes)]
        self.cb["values"] = names
        if names and self.v["brush"].get() not in names: self.v["brush"].set(names[0])
        if not names: self.v["brush"].set("")

    # ---------- reference image ----------
    def browse(self):
        p = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.gif *.webp")])
        if p: self.load_image(p)

    def load_image(self, p):
        try: self.img = Image.open(p).convert("RGBA")
        except Exception as e: return messagebox.showerror("Error", str(e))
        self.drop.config(text=os.path.basename(p), fg=FG); self.refresh(); self.preview()

    # ---------- screenshot-style selectors ----------
    def overlay(self, hint):
        self.withdraw(); self.update(); time.sleep(0.35)
        grab = ImageGrab.grab().convert("RGB")
        t = tk.Toplevel(self); t.attributes("-fullscreen", True, "-topmost", True); t.config(cursor="crosshair")
        W, H = t.winfo_screenwidth(), t.winfo_screenheight()
        k = grab.width / W
        c = tk.Canvas(t, width=W, height=H, highlightthickness=0); c.pack()
        dim = ImageEnhance.Brightness(grab).enhance(0.45).resize((W, H))
        c.dim = ImageTk.PhotoImage(dim); c.create_image(0, 0, anchor="nw", image=c.dim)
        c.create_rectangle(0, 0, 880, 36, fill="black"); c.create_text(10, 18, anchor="w", fill="yellow", font=("Arial", 14), text=hint)
        t.bind("<Escape>", lambda e: self.close(t)); t.focus_force()
        return t, c, grab, k, (W, H)

    def close(self, t):
        t.destroy(); self.deiconify(); self.refresh()

    def box_select(self, hint, done):
        t, c, grab, k, (W, H) = self.overlay(hint)
        s = {}
        def down(e):
            s["p"] = (e.x, e.y, e.x_root, e.y_root); s["r"] = c.create_rectangle(e.x, e.y, e.x, e.y, outline="#4f8cff", width=2)
        def drag(e):
            x1, y1 = s["p"][:2]; c.coords(s["r"], x1, y1, e.x, e.y)
            bx = (min(x1, e.x), min(y1, e.y), max(x1, e.x), max(y1, e.y))
            if bx[2] - bx[0] > 2 and bx[3] - bx[1] > 2:
                crop = grab.crop(tuple(int(v * k) for v in bx)).resize((bx[2] - bx[0], bx[3] - bx[1]))
                c.bright = ImageTk.PhotoImage(crop)
                if "b" in s: c.delete(s["b"])
                s["b"] = c.create_image(bx[0], bx[1], anchor="nw", image=c.bright); c.tag_raise(s["r"])
        def up(e):
            x1, y1, xr, yr = s["p"]
            box = (min(xr, e.x_root), min(yr, e.y_root), max(xr, e.x_root), max(yr, e.y_root))
            self.close(t)
            if box[2] - box[0] > 5 and box[3] - box[1] > 5: done(box, grab, k)
        c.bind("<ButtonPress-1>", down); c.bind("<B1-Motion>", drag); c.bind("<ButtonRelease-1>", up)

    def click_select(self, hint, done):
        t, c, grab, k, _ = self.overlay(hint + "  (right-click / Esc = finish)")
        pts = []
        def click(e):
            pts.append((e.x_root, e.y_root, grab.getpixel((int(e.x * k), int(e.y * k)))))
            c.create_oval(e.x - 7, e.y - 7, e.x + 7, e.y + 7, outline="red", width=2)
            c.create_text(e.x + 14, e.y - 12, text=str(len(pts)), fill="red", font=("Arial", 14, "bold"))
        c.bind("<Button-1>", click)
        c.bind("<Button-3>", lambda e: (self.close(t), done(pts)))
        t.bind("<Escape>", lambda e: (self.close(t), done(pts)))

    def sel_canvas(self):
        def done(b, g, k): self.canvas_box = b; self.refresh(); self.preview()
        self.box_select("Drag a box around the drawing canvas.  Esc = cancel", done)

    def click_swatches(self):
        def done(pts): self.palette += [{"pos": (x, y), "rgb": tuple(c)} for x, y, c in pts]; self.refresh(); self.preview()
        self.click_select("Click each colour swatch.", done)

    def click_brushes(self):
        def done(pts):
            for i, (x, y, _) in enumerate(pts):
                px = simpledialog.askinteger("Brush size", f"Brush button {i+1}: how many pixels wide is this brush?", initialvalue=4 * (i + 1), minvalue=1, maxvalue=200, parent=self)
                if px: self.brushes.append({"pos": (x, y), "px": px})
            self.refresh()
        self.click_select("Click each brush-size button (smallest to largest).", done)

    def sel_palette(self):
        def done(box, grab, k):
            found = self.detect(box, grab, k)
            if not found: return messagebox.showinfo("Colours", "No swatches found. Try a tighter box or use 'Click swatches'.")
            self.palette += found; self.refresh(); self.preview()
            self.say(f"Found {len(found)} colours. Click a colour chip to remove it.")
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
                ys, xs = np.array(cells).T; bh, bw = ys.ptp() + 1, xs.ptp() + 1
                if bw < 3 or bh < 3 or n / (bh * bw) < 0.6: continue
                rgb = tuple(int(v) for v in a[ys, xs].mean(0))
                if any(sum(abs(np.array(rgb) - np.array(o[2]))) < 14 for o in out): continue
                out.append((ys.mean(), xs.mean(), rgb, bh))
        if not out: return []
        rh = np.median([o[3] for o in out]) * 1.5
        out.sort(key=lambda o: (int(o[0] / rh), o[1]))
        return [{"pos": ((x1 + o[1] * s + s / 2) / k, (y1 + o[0] * s + s / 2) / k), "rgb": o[2]} for o in out]

    # ---------- processing ----------
    def step_px(self):
        n = self.v["brush"].get()
        if n and self.brushes: return self.brushes[[f"Brush {i+1}: {b['px']}px" for i, b in enumerate(self.brushes)].index(n)]["px"]
        return max(1, self.v["step"].get())

    def eff_mode(self):
        m = self.v["mode"].get()
        return ("Palette colours" if self.palette else "Black & white") if m == "Auto" else m

    def build_grid(self):
        if self.img is None or self.canvas_box is None: raise ValueError("Add a reference image and select the canvas first.")
        step, mode, b = self.step_px(), self.eff_mode(), self.canvas_box
        cols, rows = (b[2] - b[0]) // step, (b[3] - b[1]) // step
        if cols < 2 or rows < 2: raise ValueError("Canvas too small for this brush size.")
        im = self.img
        if self.v["fit"].get().startswith("Fit"):
            sc = min(cols / im.width, rows / im.height); w, h = max(1, int(im.width * sc)), max(1, int(im.height * sc))
        else: w, h = cols, rows
        big = 3 if mode == "Line art" else 1
        bg = Image.new("RGBA", (w * big, h * big), (255, 255, 255, 0)); bg.alpha_composite(im.resize((w * big, h * big), Image.LANCZOS))
        alpha = np.array(bg)[:, :, 3] > 40
        arr = np.clip((np.array(bg.convert("RGB")).astype(float) - 128) * self.v["contrast"].get() + 128, 0, 255)
        gray, thr = arr.mean(2), self.v["thr"].get()
        if mode == "Line art":
            e = np.array(Image.fromarray(gray.astype("uint8")).filter(ImageFilter.FIND_EDGES))
            e = np.array(Image.fromarray(e).resize((w, h), Image.BOX)).astype(float)
            out = np.where((e > thr / 4) & alpha[::big, ::big][:h, :w], 0, -1)
        elif mode == "Black & white":
            out = np.where((gray < thr) & alpha, 0, -1)
        else:
            if not self.palette: raise ValueError("Add colours first, or switch mode to Black & white.")
            pal = np.array([p["rgb"] for p in self.palette], float)
            if self.v["dither"].get():
                a = arr.copy(); out = np.zeros((h, w), int)
                for y in range(h):
                    for x in range(w):
                        old = a[y, x]; i = int(((pal - old) ** 2).sum(1).argmin()); out[y, x] = i; err = old - pal[i]
                        if x + 1 < w: a[y, x+1] += err * 7 / 16
                        if y + 1 < h:
                            if x > 0: a[y+1, x-1] += err * 3 / 16
                            a[y+1, x] += err * 5 / 16
                            if x + 1 < w: a[y+1, x+1] += err / 16
            else: out = ((arr[:, :, None, :] - pal[None, None]) ** 2).sum(3).argmin(2)
            skip = ~alpha
            if self.v["skipwhite"].get(): skip |= gray > 240
            out = np.where(skip, -1, out)
        full = -np.ones((rows, cols), int); oy, ox = (rows - out.shape[0]) // 2, (cols - out.shape[1]) // 2
        full[oy:oy + out.shape[0], ox:ox + out.shape[1]] = out[:rows, :cols]
        return full, step

    def preview(self):
        try: self.idx, step = self.build_grid()
        except ValueError as e: return self.say(str(e))
        cols = [p["rgb"] for p in self.palette] if self.eff_mode() == "Palette colours" else [(0, 0, 0)]
        px = np.full((*self.idx.shape, 3), 255, np.uint8)
        for i, c in enumerate(cols): px[self.idx == i] = c
        im = Image.fromarray(px); sc = min(660 / im.width, 680 / im.height)
        im = im.resize((max(1, int(im.width * sc)), max(1, int(im.height * sc))), Image.NEAREST)
        self.tkp = ImageTk.PhotoImage(im); self.prev.config(image=self.tkp, text="")
        self.say(f"{self.eff_mode()} | grid {self.idx.shape[1]}x{self.idx.shape[0]} | ~{int((self.idx >= 0).sum())} dabs | step {step}px")

    # ---------- drawing ----------
    def trace(self):
        if not self.canvas_box: return messagebox.showinfo("Canvas", "Select the canvas first.")
        b = self.canvas_box; self.iconify()
        def go():
            time.sleep(2.5)
            try:
                pyautogui.PAUSE = 0.01; pyautogui.moveTo(b[0], b[1])
                for p in ((b[2], b[1]), (b[2], b[3]), (b[0], b[3]), (b[0], b[1])): pyautogui.moveTo(*p, duration=0.4)
            except Exception: pass
            self.after(0, self.deiconify)
        threading.Thread(target=go, daemon=True).start()

    def start(self):
        if self.drawing: return
        try: self.idx, step = self.build_grid()
        except ValueError as e: return messagebox.showinfo("Setup", str(e))
        self.stop, self.drawing = False, True
        threading.Thread(target=self.run, args=(self.idx, step), daemon=True).start()

    def run(self, idx, step):
        try:
            for s in range(self.v["countdown"].get(), 0, -1):
                self.after(0, self.say, f"Starting in {s}s - switch to your drawing app! (ESC / corner = stop)"); time.sleep(1)
            self.after(0, self.iconify)
            pyautogui.PAUSE = max(0, self.v["delay"].get()); x0, y0 = self.canvas_box[:2]
            n = self.v["brush"].get()
            if n and self.brushes: pyautogui.click(*self.brushes[[f"Brush {i+1}: {b['px']}px" for i, b in enumerate(self.brushes)].index(n)]["pos"])
            pal = self.eff_mode() == "Palette colours"
            for ci in (range(len(self.palette)) if pal else [0]):
                if not (idx == ci).any(): continue
                if pal: pyautogui.click(*self.palette[ci]["pos"])
                for r in range(idx.shape[0]):
                    row, c, y = idx[r], 0, y0 + r * step + step // 2
                    while c < len(row):
                        if row[c] != ci: c += 1; continue
                        e = c
                        while e + 1 < len(row) and row[e + 1] == ci: e += 1
                        if self.stop: raise KeyboardInterrupt
                        pyautogui.moveTo(x0 + c * step + step // 2, y)
                        if e == c: pyautogui.click()
                        else: pyautogui.mouseDown(); pyautogui.moveTo(x0 + e * step + step // 2, y); pyautogui.mouseUp()
                        c = e + 1
            msg = "Done!"
        except KeyboardInterrupt: msg = "Stopped."
        except pyautogui.FailSafeException: msg = "Stopped (failsafe corner)."
        except Exception as ex: msg = f"Error: {ex}"
        finally:
            try: pyautogui.mouseUp()
            except Exception: pass
            self.drawing = False; self.after(0, self.deiconify); self.after(0, self.say, msg)

    # ---------- setup files ----------
    def save_cfg(self):
        p = filedialog.asksaveasfilename(defaultextension=".json")
        if p: json.dump({"canvas": self.canvas_box, "palette": self.palette, "brushes": self.brushes,
                         "settings": {k: v.get() for k, v in self.v.items()}}, open(p, "w"))

    def load_cfg(self):
        p = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not p: return
        d = json.load(open(p))
        self.canvas_box = tuple(d["canvas"]) if d.get("canvas") else None
        self.palette = [{"pos": tuple(x["pos"]), "rgb": tuple(x["rgb"])} for x in d.get("palette", [])]
        self.brushes = [{"pos": tuple(x["pos"]), "px": x["px"]} for x in d.get("brushes", [])]
        for k, val in d.get("settings", {}).items():
            if k in self.v: self.v[k].set(val)
        self.refresh()


if __name__ == "__main__":
    App().mainloop()
