"""Uncle Image Generator: สร้างและแก้ไขรูปภาพด้วย OpenRouter API (tkinter, single file).

ติดตั้ง:  pip install pillow
รัน:      python uncle_image_generator.py
ข้อมูล (API key, ประวัติ, รูปที่สร้าง) เก็บในโฟลเดอร์ UncleImageGenerator_data ข้างไฟล์นี้
"""

import base64
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import uuid
import webbrowser
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

try:
    from PIL import Image, ImageTk
except ImportError:  # ตรวจอีกครั้งตอนเปิดโปรแกรม
    Image = ImageTk = None

APP_TITLE = "Uncle Image Generator"
APP_VERSION = "1.0.0"
DEVELOPER = "Uncle Engiener"
DEVELOPER_URL = "https://uncle-engineer.com/"
DEVELOPER_EMAIL = "loong.wissawakorn@gmail.com"
APP_DESCRIPTION = (
    "Uncle Image Generator คือโปรแกรมสำหรับสร้างและแก้ไขรูปภาพด้วยโมเดล AI ผ่าน OpenRouter API\n\n"
    "• สร้างรูปจาก prompt ภาษาไทยหรืออังกฤษ พร้อมให้โมเดลช่วยแปลและขยาย prompt เป็นอังกฤษ\n"
    "• เลือกรูป reference (เช่น โลโก้) ให้ AI นำไปใส่ในภาพที่สร้าง\n"
    "• เก็บประวัติรูป พร้อม prompt และต้นทุนของแต่ละครั้ง นำ prompt เดิมกลับมาใช้ได้\n"
    "• ดูรายการโมเดลภาพและราคาเพื่อเลือกโมเดลที่คุ้มค่าที่สุด"
)
MIT_TEXT = (
    "MIT License\n\n"
    "Copyright (c) 2026 Uncle Engiener\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a copy "
    "of this software and associated documentation files (the \"Software\"), to deal "
    "in the Software without restriction, including without limitation the rights "
    "to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies "
    "of the Software, and to permit persons to whom the Software is furnished to do so, "
    "subject to the following conditions:\n\n"
    "The above copyright notice and this permission notice shall be included in all "
    "copies or substantial portions of the Software.\n\n"
    "THE SOFTWARE IS PROVIDED \"AS IS\", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR "
    "IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS "
    "FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR "
    "COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN "
    "AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION "
    "WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE."
)
ICON_FILE = "image_gen.ico"
if getattr(sys, "frozen", False):  # รันจาก .exe (PyInstaller)
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    # โฟลเดอร์ติดตั้ง (Program Files) มักเขียนไม่ได้ จึงเก็บข้อมูลไว้ใน %APPDATA%
    APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "UncleImageGenerator"
else:
    BASE_DIR = Path(__file__).resolve().parent
    APP_DIR = BASE_DIR / "UncleImageGenerator_data"
IMAGE_DIR = APP_DIR / "images"
CONFIG_FILE = APP_DIR / "config.json"
HISTORY_FILE = APP_DIR / "history.json"

API_BASE = "https://openrouter.ai/api/v1"
DEFAULT_IMAGE_MODEL = "google/gemini-2.5-flash-image"
DEFAULT_TEXT_MODEL = "google/gemini-2.5-flash"
DEFAULT_PROMPT = (
    "เด็กผู้ชายยิ้มแย้มยืนอยู่ในสวนสาธารณะตอนเช้า สวมเสื้อยืดสีขาว "
    "มีโลโก้ (ใช้รูป reference) อยู่กลางอก แสงธรรมชาตินุ่มนวล ภาพถ่ายคุณภาพสูง"
)

ENHANCE_OFF = "ไม่ช่วยคิด (ใช้ prompt ที่พิมพ์)"
ENHANCE_TRANSLATE = "แปลเป็นอังกฤษ (คงรายละเอียดเดิม)"
ENHANCE_EXPAND = "แปลและขยาย prompt เป็นอังกฤษ"
ENHANCE_MODES = [ENHANCE_OFF, ENHANCE_TRANSLATE, ENHANCE_EXPAND]
ENHANCE_SYSTEM = {
    ENHANCE_TRANSLATE: (
        "Translate the user's image prompt into natural, concise English. "
        "Keep every detail. Output only the English prompt."
    ),
    ENHANCE_EXPAND: (
        "You write prompts for an AI image generator. Translate the user's request (it may be in Thai) "
        "into one detailed English prompt covering subject, action, clothing and colors, setting, lighting, "
        "camera angle and style. If reference images are mentioned (e.g. a logo), state that they must be "
        "reproduced exactly as provided and placed where the user asked. Output only the final prompt."
    ),
}
ASPECT_RATIOS = ["ไม่ระบุ", "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"]
IMAGE_EXTS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
              ".webp": "image/webp", ".gif": "image/gif"}
MIME_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
MAX_REF_BYTES = 20 * 1024 * 1024
MUTED = "#6b7280"
THUMB_BOX = (56, 56)


# ---------------------------------------------------------------- helpers

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fmt_usd(value):
    if value is None:
        return "ไม่ทราบ"
    digits = 6 if abs(value) < 0.01 else 4
    return f"${value:.{digits}f}"


def model_modalities(model):
    """คืน (input, output) เป็นลิสต์ เช่น (["text", "image"], ["image"])"""
    arch = model.get("architecture") or {}
    inp = arch.get("input_modalities")
    out = arch.get("output_modalities")
    if not inp or not out:  # รูปแบบเก่าใช้ "text+image->image"
        src, _, dst = (arch.get("modality") or "").partition("->")
        inp = inp or [x for x in src.split("+") if x]
        out = out or [x for x in dst.split("+") if x]
    return list(inp or ["text"]), list(out or ["text"])


def price_summary(model):
    p = model.get("pricing") or {}
    parts = []
    pin, pout = to_float(p.get("prompt")), to_float(p.get("completion"))
    img, img_out = to_float(p.get("image")), to_float(p.get("image_output"))
    req = to_float(p.get("request"))
    if pin is not None and pin < 0:  # router เช่น openrouter/auto ใช้ -1 แทนราคาแปรผัน
        return "ราคาขึ้นกับโมเดลที่ router เลือก"
    if pin:
        parts.append(f"input ${pin * 1e6:,.2f}/M tok")
    if pout:
        parts.append(f"output ${pout * 1e6:,.2f}/M tok")
    if img_out:
        parts.append(f"รูปที่ออก ${img_out * 1e6:,.2f}/M tok")
    if img:
        parts.append(f"รูป ${img:.4f}")
    if req:
        parts.append(f"ต่อ request ${req:.4f}")
    return " · ".join(parts) or "ไม่ระบุราคา"


def estimate_cost(model, usage, images):
    """ใช้เมื่อ API ไม่ส่ง usage.cost มา: คำนวณจากราคาต่อหน่วยของโมเดล"""
    p = model.get("pricing") or {}
    # image_output = ราคาต่อ token ของรูปที่ส่งออก (โมเดลภาพส่วนใหญ่คิดแบบนี้) จึงบวกเข้ากับ completion
    total = (to_float(p.get("prompt")) or 0) * (usage.get("prompt_tokens") or 0)
    total += ((to_float(p.get("completion")) or 0) + (to_float(p.get("image_output")) or 0)) \
        * (usage.get("completion_tokens") or 0)
    total += (to_float(p.get("image")) or 0) * images
    total += to_float(p.get("request")) or 0
    return total


SORT_OPTIONS = ["ชื่อ (A-Z)", "ถูกสุดก่อน", "แพงสุดก่อน"]
# การใช้งานสมมติ 1 ครั้ง ไว้เทียบราคาโมเดลให้เป็นตัวเลขเดียวกัน
TYPICAL_USAGE = {
    "image": {"prompt_tokens": 1000, "completion_tokens": 1300, "images": 1},
    "text": {"prompt_tokens": 1000, "completion_tokens": 500, "images": 0},
}


def est_typical_cost(model, kind):
    """ต้นทุนประมาณต่อ 1 ครั้งตาม TYPICAL_USAGE; คืน None ถ้าราคาเป็นแบบแปรผัน (router)"""
    p = model.get("pricing") or {}
    if any((to_float(v) or 0) < 0 for v in p.values()):
        return None
    usage = TYPICAL_USAGE[kind]
    return estimate_cost(model, usage, usage["images"])


def cost_for(usage, info, images):
    """คืน (ต้นทุน, เป็นค่าประมาณการหรือไม่)"""
    actual = to_float(usage.get("cost"))
    if actual is not None:
        return actual, False
    if info:
        return estimate_cost(info, usage, images), True
    return None, True


def message_text(resp):
    msg = (resp.get("choices") or [{}])[0].get("message") or {}
    content = msg.get("content")
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def decode_image_url(url):
    """คืน (mime, bytes) จาก data URL หรือ URL ปกติ"""
    if url.startswith("http"):
        with urllib.request.urlopen(url, timeout=120) as resp:
            return resp.headers.get_content_type(), resp.read()
    m = re.match(r"data:([\w/+.-]+);base64,(.*)$", url, re.S)
    if not m:
        raise ValueError("รูปแบบรูปที่ตอบกลับมาไม่รู้จัก")
    return m.group(1), base64.b64decode(m.group(2))


def load_reference(path):
    p = Path(path)
    mime = IMAGE_EXTS.get(p.suffix.lower())
    if not mime:
        raise ValueError(f"{p.name}: รองรับเฉพาะ png, jpg, webp, gif")
    raw = p.read_bytes()
    if len(raw) > MAX_REF_BYTES:
        raise ValueError(f"{p.name}: ไฟล์ใหญ่เกิน 20 MB")
    return {"name": p.name, "path": str(p),
            "data_url": f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")}


def make_photo(path, box):
    """สร้าง PhotoImage ย่อให้พอดี box (กว้าง, สูง)"""
    with Image.open(path) as im:
        im.thumbnail(box, Image.LANCZOS)
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA")
        return ImageTk.PhotoImage(im)


def set_text(widget, text, readonly=True):
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", text)
    if readonly:
        widget.configure(state="disabled")


def open_path(path):
    path = str(path)
    if sys.platform.startswith("win"):
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# ---------------------------------------------------------------- OpenRouter client

class OpenRouterError(Exception):
    pass


class OpenRouterClient:
    def __init__(self, api_key):
        self.api_key = api_key

    def request(self, method, path, body=None, timeout=180):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(API_BASE + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Title", APP_TITLE)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "replace")
            try:
                msg = json.loads(raw)["error"]["message"]
            except (ValueError, KeyError, TypeError):
                msg = raw[:300] or e.reason
            raise OpenRouterError(f"HTTP {e.code}: {msg}") from None
        except urllib.error.URLError as e:
            raise OpenRouterError(f"เชื่อมต่อ OpenRouter ไม่ได้: {e.reason}") from None
        except TimeoutError:
            raise OpenRouterError("หมดเวลารอการตอบกลับจาก OpenRouter") from None

    def list_models(self):
        # ค่าเริ่มต้นของ API คืนเฉพาะโมเดล output เป็นข้อความ ต้องขอ all เพื่อให้มีโมเดลสร้างรูปด้วย
        return self.request("GET", "/models?output_modalities=all", timeout=60).get("data", [])

    def key_info(self):
        return self.request("GET", "/key", timeout=30).get("data", {})

    def chat(self, body, timeout=240):
        return self.request("POST", "/chat/completions", body, timeout)

    def enhance_prompt(self, model, mode, prompt, ref_names):
        user_text = prompt
        if ref_names:
            user_text += "\n\n(Reference image(s) provided: " + ", ".join(ref_names) + ")"
        resp = self.chat({"model": model, "messages": [
            {"role": "system", "content": ENHANCE_SYSTEM[mode]},
            {"role": "user", "content": user_text},
        ]}, timeout=120)
        text = message_text(resp).strip().strip('"').strip()
        if not text:
            raise OpenRouterError("โมเดลช่วยคิด prompt ไม่ได้ส่งข้อความกลับมา")
        return text, resp.get("usage") or {}

    def generate_image(self, model, output_modalities, prompt, refs, aspect):
        """โมเดลที่ส่งออกเป็นรูปล้วนใช้ /images, โมเดลอื่นใช้ chat/completions"""
        if "text" not in output_modalities:
            return self.generate_via_images(model, prompt, refs, aspect)
        try:
            return self.generate_via_chat(model, output_modalities, prompt, refs, aspect)
        except OpenRouterError as e:
            if "/api/v1/images" in str(e):  # API แจ้งให้ใช้ endpoint นี้แทน
                return self.generate_via_images(model, prompt, refs, aspect)
            raise

    def generate_via_images(self, model, prompt, refs, aspect):
        body = {"model": model, "prompt": prompt}
        if refs:
            body["input_references"] = [{"type": "image_url", "url": r["data_url"]} for r in refs]
        if aspect != ASPECT_RATIOS[0]:
            body["aspect_ratio"] = aspect
        resp = self.request("POST", "/images", body, timeout=240)
        items = resp.get("data") or []
        if not items or not items[0].get("b64_json"):
            raise OpenRouterError("โมเดลไม่ได้ส่งรูปกลับมา")
        media = items[0].get("media_type") or "image/png"
        return [f"data:{media};base64,{items[0]['b64_json']}"], resp.get("usage") or {}

    def generate_via_chat(self, model, output_modalities, prompt, refs, aspect):
        content = [{"type": "text", "text": prompt}]
        for ref in refs:
            content.append({"type": "image_url", "image_url": {"url": ref["data_url"]}})
        body = {"model": model, "messages": [{"role": "user", "content": content}],
                "modalities": output_modalities}
        if aspect != ASPECT_RATIOS[0]:
            body["image_config"] = {"aspect_ratio": aspect}
        resp = self.chat(body)
        msg = (resp.get("choices") or [{}])[0].get("message") or {}
        urls = []
        for img in msg.get("images") or []:
            url = (img.get("image_url") or {}).get("url") or img.get("url")
            if url:
                urls.append(url)
        if not urls:
            text = message_text(resp)
            raise OpenRouterError("โมเดลไม่ได้ส่งรูปกลับมา" + (f": {text[:200]}" if text else ""))
        return urls, resp.get("usage") or {}


# ---------------------------------------------------------------- widgets

class ImageView(ttk.Frame):
    """กรอบแสดงรูปที่ย่อ/ขยายให้พอดีเมื่อปรับขนาดหน้าต่าง"""

    def __init__(self, master, placeholder="", **kw):
        super().__init__(master, **kw)
        self.placeholder = placeholder
        self._path = None
        self._photo = None
        self._job = None
        self.label = tk.Label(self, bg="#1f2328", fg="#9ca3af", text=placeholder, compound="center")
        self.label.place(relx=0.5, rely=0.5, anchor="center")
        self.bind("<Configure>", self._on_resize)

    def set_image(self, path):
        self._path = str(path) if path and Path(path).exists() else None
        self._redraw()

    def _on_resize(self, _event):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(80, self._redraw)

    def _redraw(self):
        self._job = None
        if not self._path or Image is None:
            self._photo = None
            self.label.configure(image="", text=self.placeholder)
            return
        w, h = self.winfo_width() - 16, self.winfo_height() - 16
        if w < 40 or h < 40:
            return
        try:
            self._photo = make_photo(self._path, (w, h))
            self.label.configure(image=self._photo, text="")
        except Exception:
            self._photo = None
            self.label.configure(image="", text="เปิดรูปไม่ได้")


# ---------------------------------------------------------------- app

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(1040, 700)
        # ขนาดปกติอยู่กลางจอ และเปิดแบบ maximize ตั้งแต่ครั้งแรก
        w, h = 1280, 820
        x = max((self.winfo_screenwidth() - w) // 2, 0)
        y = max((self.winfo_screenheight() - h) // 2, 0)
        self.geometry(f"{w}x{h}+{x}+{y}")
        try:
            self.state("zoomed")
        except tk.TclError:  # ระบบที่ไม่รองรับ zoomed
            pass
        self._set_icon()
        APP_DIR.mkdir(parents=True, exist_ok=True)
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)

        self.config_data = load_json(CONFIG_FILE, {})
        self.history = load_json(HISTORY_FILE, [])
        self.models_by_id = {}
        self.references = []
        self.current_result = None
        self.session_cost = 0.0
        self.busy = False
        self.current_job = None
        self.ui_queue = queue.Queue()
        self._thumbs = {}
        self._ref_photo = None

        self._setup_style()

        self.image_model_var = tk.StringVar(value=self.config_data.get("image_model", DEFAULT_IMAGE_MODEL))
        self.text_model_var = tk.StringVar(value=self.config_data.get("text_model", DEFAULT_TEXT_MODEL))
        self.enhance_var = tk.StringVar(value=self.config_data.get("enhance_mode", ENHANCE_OFF))
        self.aspect_var = tk.StringVar(value=self.config_data.get("aspect_ratio", ASPECT_RATIOS[0]))
        self.status_var = tk.StringVar(value="พร้อมใช้งาน")
        self.key_var = tk.StringVar()

        self._build_menu()
        self._build_ui()
        self._update_key_label()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(100, self._poll_queue)
        self.after(300, self._initial_load)

    # ----- setup

    def _set_icon(self):
        icon = BASE_DIR / ICON_FILE
        if not icon.exists():
            return
        if sys.platform.startswith("win"):
            # ให้ Windows แยก taskbar ของโปรแกรมนี้ออกจาก python.exe จึงใช้ไอคอนของเราได้
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("UncleImageGenerator")
            except (AttributeError, OSError):
                pass
        try:
            self.iconbitmap(default=str(icon))
        except tk.TclError:
            # ระบบที่ไม่รองรับ .ico ให้ใช้รูปจากไฟล์เดียวกันแทน
            try:
                if Image is not None:
                    with Image.open(icon) as im:
                        self._icon_photo = ImageTk.PhotoImage(im.convert("RGBA"))
                    self.iconphoto(True, self._icon_photo)
            except (OSError, tk.TclError):
                pass

    def _setup_style(self):
        try:
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
                tkfont.nametofont(name).configure(family="Leelawadee UI", size=10)
        except tk.TclError:
            pass
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        bold = tkfont.nametofont("TkDefaultFont").copy()
        bold.configure(weight="bold", size=11)
        style.configure("Accent.TButton", font=bold, padding=(10, 8))
        style.configure("Hist.Treeview", rowheight=62)
        style.configure("Key.TLabel", foreground=MUTED)

    def _build_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        m = tk.Menu(menubar, tearoff=0)
        m.add_command(label="ตั้งค่า API Key…", command=self.open_settings, accelerator="Ctrl+,")
        m.add_command(label="โหลดรายการโมเดลใหม่", command=self.load_models, accelerator="F5")
        m.add_separator()
        m.add_command(label="เปิดโฟลเดอร์ข้อมูล", command=lambda: open_path(APP_DIR))
        m.add_separator()
        m.add_command(label="ออก", command=self.on_close)
        menubar.add_cascade(label="ไฟล์ / ตั้งค่า", menu=m)
        h = tk.Menu(menubar, tearoff=0)
        h.add_command(label="เกี่ยวกับโปรแกรม (About)…", command=self.show_about)
        h.add_command(label="เว็บไซต์ผู้พัฒนา", command=lambda: webbrowser.open(DEVELOPER_URL))
        menubar.add_cascade(label="Help", menu=h)
        self.bind("<Control-comma>", lambda _e: self.open_settings())
        self.bind("<F5>", lambda _e: self.load_models())

    def show_about(self):
        win = tk.Toplevel(self)
        win.title("เกี่ยวกับโปรแกรม")
        win.transient(self)
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=f"{APP_TITLE}  v{APP_VERSION}",
                  font=tkfont.nametofont("TkHeadingFont")).pack(anchor="w")
        ttk.Label(frm, text=APP_DESCRIPTION, wraplength=460, justify="left").pack(anchor="w", pady=(8, 12))

        def link(parent, row, text, url):
            lbl = tk.Label(parent, text=text, fg="#1d4ed8", cursor="hand2", anchor="w")
            lbl.grid(row=row, column=1, sticky="w", padx=6)
            lbl.bind("<Button-1>", lambda _e: webbrowser.open(url))

        info = ttk.Frame(frm)
        info.pack(anchor="w")
        ttk.Label(info, text="ผู้พัฒนา:").grid(row=0, column=0, sticky="w")
        ttk.Label(info, text=DEVELOPER).grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(info, text="เว็บไซต์:").grid(row=1, column=0, sticky="w")
        link(info, 1, DEVELOPER_URL, DEVELOPER_URL)
        ttk.Label(info, text="ติดต่อ:").grid(row=2, column=0, sticky="w")
        link(info, 2, DEVELOPER_EMAIL, f"mailto:{DEVELOPER_EMAIL}")
        ttk.Label(info, text="License:").grid(row=3, column=0, sticky="w")
        ttk.Label(info, text="MIT License").grid(row=3, column=1, sticky="w", padx=6)

        ttk.Label(frm, text="ข้อความ License ฉบับเต็ม", style="Key.TLabel").pack(anchor="w", pady=(12, 4))
        box = tk.Text(frm, height=8, width=70, wrap="word", relief="solid", bd=1, padx=6, pady=6)
        box.insert("1.0", MIT_TEXT)
        box.configure(state="disabled")
        box.pack(fill="both", expand=True)
        ttk.Button(frm, text="ปิด", command=win.destroy).pack(anchor="e", pady=(10, 0))
        win.grab_set()

    def _build_ui(self):
        bar = ttk.Frame(self, padding=(8, 4))
        bar.pack(fill="x", side="bottom")
        ttk.Label(bar, textvariable=self.status_var).pack(side="left")
        self.key_label = ttk.Label(bar, textvariable=self.key_var)
        self.key_label.pack(side="right")

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(8, 0))
        self.tab_generate = ttk.Frame(self.notebook)
        self.tab_history = ttk.Frame(self.notebook)
        self.tab_models = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_generate, text="  สร้างรูป  ")
        self.notebook.add(self.tab_history, text="  ประวัติ  ")
        self.notebook.add(self.tab_models, text="  โมเดลและราคา  ")
        self._build_generate_tab(self.tab_generate)
        self._build_history_tab(self.tab_history)
        self._build_models_tab(self.tab_models)

    # ----- generate tab

    def _build_generate_tab(self, parent):
        paned = ttk.PanedWindow(parent, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=8)
        left = ttk.Frame(paned)
        right = ttk.Frame(paned, padding=(8, 0, 0, 0))
        paned.add(left, weight=0)
        paned.add(right, weight=1)

        # ปุ่มสร้างรูปและแถบความคืบหน้าต้อง pack ที่ด้านล่างก่อน ไม่งั้นจะถูกดันหายเมื่อหน้าต่างเล็ก
        self.progress = ttk.Progressbar(left, mode="indeterminate")
        self.progress.pack(side="bottom", fill="x", pady=(6, 0))
        action = ttk.Frame(left)
        action.pack(side="bottom", fill="x", pady=(8, 0))
        self.gen_btn = ttk.Button(action, text="สร้างรูป", style="Accent.TButton", command=self.start_generate)
        self.gen_btn.pack(fill="x")

        # 1) ตั้งค่าโมเดล
        settings = ttk.LabelFrame(left, text="1) ตั้งค่าโมเดล", padding=8)
        settings.pack(fill="x")
        ttk.Label(settings, text="โมเดลสร้างรูป").pack(anchor="w")
        self.image_combo = ttk.Combobox(settings, textvariable=self.image_model_var,
                                        values=[DEFAULT_IMAGE_MODEL], width=50)
        self.image_combo.pack(fill="x")
        self.image_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_model_hints())
        self.image_combo.bind("<Return>", lambda _e: self._update_model_hints())
        self.image_hint = ttk.Label(settings, style="Key.TLabel", wraplength=440, justify="left")
        self.image_hint.pack(anchor="w", pady=(2, 8))

        ttk.Label(settings, text="โมเดลช่วยคิด prompt (ใช้เมื่อเลือกโหมดช่วยคิด)").pack(anchor="w")
        self.text_combo = ttk.Combobox(settings, textvariable=self.text_model_var,
                                       values=[DEFAULT_TEXT_MODEL], width=50)
        self.text_combo.pack(fill="x")
        self.text_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_model_hints())
        self.text_combo.bind("<Return>", lambda _e: self._update_model_hints())
        self.text_hint = ttk.Label(settings, style="Key.TLabel", wraplength=440, justify="left")
        self.text_hint.pack(anchor="w", pady=(2, 8))

        row = ttk.Frame(settings)
        row.pack(fill="x")
        col1 = ttk.Frame(row)
        col1.pack(side="left", fill="x", expand=True)
        ttk.Label(col1, text="โหมด prompt").pack(anchor="w")
        ttk.Combobox(col1, textvariable=self.enhance_var, values=ENHANCE_MODES,
                     state="readonly", width=30).pack(fill="x", padx=(0, 8))
        col2 = ttk.Frame(row)
        col2.pack(side="left")
        ttk.Label(col2, text="อัตราส่วนภาพ").pack(anchor="w")
        ttk.Combobox(col2, textvariable=self.aspect_var, values=ASPECT_RATIOS,
                     state="readonly", width=10).pack()

        # 2) รูป reference
        refs = ttk.LabelFrame(left, text="2) รูป reference (ไม่บังคับ เช่น โลโก้)", padding=8)
        refs.pack(fill="x", pady=8)
        row = ttk.Frame(refs)
        row.pack(fill="x")
        self.ref_list = tk.Listbox(row, height=4, activestyle="none", exportselection=False)
        self.ref_list.pack(side="left", fill="both", expand=True)
        self.ref_list.bind("<<ListboxSelect>>", lambda _e: self._show_ref_thumb())
        self.ref_thumb = tk.Label(row, width=12, height=6, bg="#e5e7eb", text="ไม่มีรูป", fg=MUTED)
        self.ref_thumb.pack(side="left", padx=(8, 0))
        btns = ttk.Frame(refs)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="+ เพิ่มรูป", command=self.add_references).pack(side="left")
        ttk.Button(btns, text="ลบรูปที่เลือก", command=self.remove_reference).pack(side="left", padx=6)
        ttk.Button(btns, text="ล้างทั้งหมด", command=self.clear_references).pack(side="left")
        ttk.Label(refs, style="Key.TLabel", text="ใช้ได้เฉพาะโมเดลที่รับ input เป็นรูปภาพ").pack(anchor="w", pady=(4, 0))

        # 3) prompt
        prompt_frame = ttk.LabelFrame(left, text="3) Prompt (พิมพ์ภาษาไทยได้)  กด Ctrl+Enter เพื่อสร้าง", padding=8)
        prompt_frame.pack(fill="both", expand=True)
        self.prompt_text = tk.Text(prompt_frame, height=8, width=50, wrap="word", undo=True,
                                   relief="solid", bd=1, padx=6, pady=6, font=("Leelawadee UI", 11))
        self.prompt_text.pack(fill="both", expand=True)
        self.prompt_text.insert("1.0", DEFAULT_PROMPT)
        self.prompt_text.bind("<Control-Return>", self._on_ctrl_enter)

        # ผลลัพธ์ (ขวา)
        self.result_view = ImageView(right, placeholder="ผลลัพธ์จะแสดงที่นี่")
        self.result_view.pack(fill="both", expand=True)
        info = ttk.LabelFrame(right, text="ต้นทุนและรายละเอียด", padding=8)
        info.pack(fill="x", pady=(8, 0))
        self.result_info = tk.Text(info, height=7, wrap="word", relief="flat", bg=self._bg(), bd=0)
        self.result_info.pack(fill="x")
        ttk.Label(info, text="prompt ที่ส่งจริง (อังกฤษ ถ้ามีการช่วยคิด)").pack(anchor="w", pady=(6, 0))
        self.result_prompt = tk.Text(info, height=4, wrap="word", relief="solid", bd=1, padx=6, pady=4)
        self.result_prompt.pack(fill="x")
        btns = ttk.Frame(info)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="บันทึกรูป…", command=lambda: self.save_record_as(self.current_result)).pack(side="left")
        ttk.Button(btns, text="เปิดไฟล์รูป", command=lambda: self.open_record(self.current_result)).pack(side="left", padx=6)
        ttk.Button(btns, text="คัดลอก prompt อังกฤษ",
                   command=lambda: self.copy_text(self.current_result and self.current_result["prompt_sent"])).pack(side="left")
        ttk.Button(btns, text="ใช้ prompt นี้ต่อ", command=self.reuse_result_prompt).pack(side="right")
        self.session_var = tk.StringVar(value="ค่าใช้จ่ายรอบนี้ (session): $0")
        ttk.Label(info, textvariable=self.session_var, style="Key.TLabel").pack(anchor="w", pady=(6, 0))

        self._update_model_hints()

    def _bg(self):
        return ttk.Style(self).lookup("TFrame", "background") or "#f0f0f0"

    def _on_ctrl_enter(self, _event):
        self.start_generate()
        return "break"

    def _update_model_hints(self):
        self._hint_for(self.image_combo, self.image_hint, need_out="image")
        self._hint_for(self.text_combo, self.text_hint, need_out="text")

    def _hint_for(self, combo, label, need_out):
        mid = combo.get().strip()
        m = self.models_by_id.get(mid)
        if not m:
            label.configure(text="ยังไม่มีข้อมูลโมเดลนี้ (กด F5 เพื่อโหลดรายการโมเดลจาก OpenRouter)")
            return
        inp, out = model_modalities(m)
        text = f"รับ input: {', '.join(inp)} · output: {', '.join(out)}\nราคา: {price_summary(m)}"
        if need_out not in out:
            text += f"\n⚠ โมเดลนี้ไม่ได้ส่ง output เป็น {need_out}"
        elif need_out == "image" and "image" not in inp:
            text += "\n⚠ โมเดลนี้ไม่รับรูป reference"
        label.configure(text=text)

    def add_references(self):
        paths = filedialog.askopenfilenames(parent=self, title="เลือกรูป reference",
                                            filetypes=[("รูปภาพ", "*.png *.jpg *.jpeg *.webp *.gif")])
        errors = []
        for path in paths:
            try:
                self.references.append(load_reference(path))
            except (OSError, ValueError) as e:
                errors.append(str(e))
        self._refresh_ref_list()
        if errors:
            messagebox.showwarning(APP_TITLE, "\n".join(errors), parent=self)

    def remove_reference(self):
        sel = self.ref_list.curselection()
        if sel:
            del self.references[sel[0]]
            self._refresh_ref_list()

    def clear_references(self):
        self.references = []
        self._refresh_ref_list()

    def _refresh_ref_list(self):
        self.ref_list.delete(0, "end")
        for ref in self.references:
            self.ref_list.insert("end", ref["name"])
        if self.references:
            self.ref_list.selection_clear(0, "end")
            self.ref_list.selection_set(len(self.references) - 1)
        self._show_ref_thumb()

    def _show_ref_thumb(self):
        sel = self.ref_list.curselection()
        photo = None
        if sel and Image is not None:
            try:
                photo = make_photo(self.references[sel[0]]["path"], (104, 104))
            except Exception:
                photo = None
        self._ref_photo = photo
        if photo:  # มีรูปแล้ว width/height เป็นพิกเซล ให้ 0 = ขนาดตามรูป
            self.ref_thumb.configure(image=photo, text="", width=0, height=0)
        else:
            self.ref_thumb.configure(image="", text="ไม่มีรูป", width=12, height=6)

    def start_generate(self):
        if self.busy:
            return
        key = self._require_key()
        if not key:
            return
        prompt = self.prompt_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning(APP_TITLE, "กรุณาพิมพ์ prompt ก่อน", parent=self)
            return
        image_model = self.image_combo.get().strip()
        if not image_model:
            messagebox.showwarning(APP_TITLE, "กรุณาเลือกโมเดลสร้างรูป", parent=self)
            return
        mode = self.enhance_var.get()
        text_model = self.text_combo.get().strip()
        if mode != ENHANCE_OFF and not text_model:
            messagebox.showwarning(APP_TITLE, "กรุณาเลือกโมเดลช่วยคิด prompt หรือเปลี่ยนโหมดเป็น 'ไม่ช่วยคิด'", parent=self)
            return

        refs = [dict(r) for r in self.references]
        image_info = self.models_by_id.get(image_model)
        if refs and image_info and "image" not in model_modalities(image_info)[0]:
            if not messagebox.askyesno(APP_TITLE,
                                       "โมเดลที่เลือกไม่รับรูป reference ผลลัพธ์อาจไม่มีโลโก้ตามที่ต้องการ\nจะดำเนินการต่อหรือไม่?",
                                       parent=self):
                return
        output_mods = ["image", "text"]
        if image_info and "text" not in model_modalities(image_info)[1]:
            output_mods = ["image"]

        req = {
            "prompt": prompt, "mode": mode,
            "text_model": text_model if mode != ENHANCE_OFF else "",
            "image_model": image_model, "output_modalities": output_mods,
            "refs": refs, "aspect": self.aspect_var.get(),
            "image_info": image_info, "text_info": self.models_by_id.get(text_model),
        }
        token = threading.Event()  # ถูก set เมื่อผู้ใช้กดยกเลิก
        self.current_job = token
        req["token"] = token
        self._set_busy(True, "กำลังเริ่มงาน…")
        client = OpenRouterClient(key)

        def notify(msg):
            if not token.is_set():
                self.ui_queue.put(lambda: self.set_status(msg))

        # ผลของงานที่ถูกยกเลิกแล้วจะถูกทิ้ง ไม่แสดงและไม่บันทึก
        self.run_bg(lambda: self._generate_job(client, req, notify),
                    on_ok=lambda rec: token.is_set() or self._on_generated(rec),
                    on_err=lambda e: token.is_set() or self._show_error(e))

    def cancel_generate(self):
        """หยุดรอผลลัพธ์ทันที คำขอที่ส่งไปแล้วอาจยังถูกคิดค่าใช้จ่ายโดย OpenRouter"""
        if not self.busy or self.current_job is None:
            return
        self.current_job.set()
        self.current_job = None
        self._set_busy(False, "ยกเลิกการสร้างรูปแล้ว (คำขอที่ส่งไปแล้วอาจยังถูกคิดค่าใช้จ่าย)")

    def _generate_job(self, client, req, notify):
        """ทำงานใน thread แยก: (ช่วยคิด prompt) -> สร้างรูป -> บันทึกไฟล์"""
        token = req["token"]
        prompt_sent, prompt_usage = req["prompt"], {}
        if req["mode"] != ENHANCE_OFF:
            notify("กำลังให้โมเดลช่วยเขียน prompt ภาษาอังกฤษ…")
            prompt_sent, prompt_usage = client.enhance_prompt(
                req["text_model"], req["mode"], req["prompt"], [r["name"] for r in req["refs"]])
            if token.is_set():
                return None

        notify("กำลังสร้างรูป… (มักใช้เวลา 10–60 วินาที)")
        urls, image_usage = client.generate_image(
            req["image_model"], req["output_modalities"], prompt_sent, req["refs"], req["aspect"])
        if token.is_set():
            return None
        mime, raw = decode_image_url(urls[0])

        rec_id = uuid.uuid4().hex[:12]
        rel = f"images/{rec_id}.{MIME_EXT.get(mime, 'png')}"
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)
        (APP_DIR / rel).write_bytes(raw)

        cost_image, est_image = cost_for(image_usage, req["image_info"], 1)
        if req["mode"] != ENHANCE_OFF:
            cost_prompt, est_prompt = cost_for(prompt_usage, req["text_info"], 0)
        else:
            cost_prompt, est_prompt = None, False
        parts = [c for c in (cost_image, cost_prompt) if c is not None]
        return {
            "id": rec_id,
            "created": datetime.now().isoformat(timespec="seconds"),
            "image_model": req["image_model"],
            "text_model": req["text_model"],
            "enhance_mode": req["mode"],
            "aspect_ratio": req["aspect"],
            "prompt_th": req["prompt"],
            "prompt_sent": prompt_sent,
            "references": [{"name": r["name"], "path": r["path"]} for r in req["refs"]],
            "image_file": rel,
            "cost_image": cost_image,
            "cost_prompt": cost_prompt,
            "cost_total": sum(parts) if parts else None,
            "cost_estimated": bool(est_image or est_prompt),
            "tokens": {"input": image_usage.get("prompt_tokens"),
                       "output": image_usage.get("completion_tokens")},
        }

    def _on_generated(self, rec):
        self.history.insert(0, rec)
        save_json(HISTORY_FILE, self.history)
        self.session_cost += rec["cost_total"] or 0
        self.current_result = rec
        self._show_result(rec)
        self.refresh_history()
        self._set_busy(False, f"สร้างรูปเสร็จแล้ว · {datetime.now().strftime('%H:%M:%S')}")

    def _show_result(self, rec):
        self.result_view.set_image(APP_DIR / rec["image_file"])
        est = " (ประมาณการ)" if rec["cost_estimated"] else " (จาก OpenRouter)"
        lines = [
            f"โมเดลรูป: {rec['image_model']}",
            f"โมเดลช่วยคิด prompt: {rec['text_model'] or '- (ไม่ได้ใช้)'}",
            f"ต้นทุนรูป: {fmt_usd(rec['cost_image'])}",
            f"ต้นทุน prompt: {fmt_usd(rec['cost_prompt']) if rec['cost_prompt'] is not None else '-'}",
            f"รวม: {fmt_usd(rec['cost_total'])}{est}",
            f"Token: input {rec['tokens']['input'] or '-'} / output {rec['tokens']['output'] or '-'}",
        ]
        set_text(self.result_info, "\n".join(lines))
        set_text(self.result_prompt, rec["prompt_sent"])
        self.session_var.set(f"ค่าใช้จ่ายรอบนี้ (session): {fmt_usd(self.session_cost)}")

    def reuse_result_prompt(self):
        if not self.current_result:
            return
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", self.current_result["prompt_sent"])
        self.enhance_var.set(ENHANCE_OFF)
        self.set_status("ใส่ prompt อังกฤษที่ส่งไปแล้วในช่อง prompt (ปิดโหมดช่วยคิดแล้ว)")

    # ----- history tab

    def _build_history_tab(self, parent):
        paned = ttk.PanedWindow(parent, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=8)
        left = ttk.Frame(paned)
        right = ttk.Frame(paned, padding=(8, 0, 0, 0))
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        top = ttk.Frame(left)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="ค้นหา prompt / โมเดล:").pack(side="left")
        self.hist_filter = tk.StringVar()
        ttk.Entry(top, textvariable=self.hist_filter).pack(side="left", fill="x", expand=True, padx=6)
        self.hist_filter.trace_add("write", lambda *_: self.refresh_history())
        self.hist_summary = ttk.Label(left, style="Key.TLabel")
        self.hist_summary.pack(anchor="w", pady=(0, 4))

        wrap = ttk.Frame(left)
        wrap.pack(fill="both", expand=True)
        self.hist_tree = ttk.Treeview(wrap, columns=("time", "model", "cost", "prompt"),
                                      show="tree headings", style="Hist.Treeview", selectmode="browse")
        self.hist_tree.heading("#0", text="รูป")
        self.hist_tree.column("#0", width=76, stretch=False)
        for col, title, width, stretch in (("time", "เวลา", 120, False), ("model", "โมเดล", 170, False),
                                           ("cost", "ต้นทุน", 90, False), ("prompt", "prompt", 300, True)):
            self.hist_tree.heading(col, text=title)
            self.hist_tree.column(col, width=width, stretch=stretch)
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.hist_tree.yview)
        self.hist_tree.configure(yscrollcommand=scroll.set)
        self.hist_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.hist_tree.bind("<<TreeviewSelect>>", lambda _e: self.on_history_select())

        self.hist_view = ImageView(right, placeholder="เลือกรายการจากประวัติ")
        self.hist_view.pack(fill="both", expand=True)
        detail = ttk.LabelFrame(right, text="รายละเอียด", padding=8)
        detail.pack(fill="x", pady=(8, 0))
        self.hist_detail = tk.Text(detail, height=9, wrap="word", relief="flat", bg=self._bg(), bd=0)
        self.hist_detail.pack(fill="x")
        btns = ttk.Frame(detail)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="ใช้ prompt ไทยเดิม", command=lambda: self.reuse_history("th")).pack(side="left")
        ttk.Button(btns, text="ใช้ prompt อังกฤษ", command=lambda: self.reuse_history("en")).pack(side="left", padx=6)
        ttk.Button(btns, text="โหลดทั้งหมด (รวม ref + โมเดล)", command=lambda: self.reuse_history("all")).pack(side="left")
        btns2 = ttk.Frame(detail)
        btns2.pack(fill="x", pady=(6, 0))
        ttk.Button(btns2, text="บันทึกรูป…", command=lambda: self.save_record_as(self.selected_record())).pack(side="left")
        ttk.Button(btns2, text="เปิดไฟล์รูป", command=lambda: self.open_record(self.selected_record())).pack(side="left", padx=6)
        ttk.Button(btns2, text="ลบรายการ", command=self.delete_history).pack(side="right")

    def _thumb_for(self, rec):
        if rec["id"] in self._thumbs:
            return self._thumbs[rec["id"]]
        photo = None
        path = APP_DIR / rec["image_file"]
        if Image is not None and path.exists():
            try:
                photo = make_photo(path, THUMB_BOX)
            except Exception:
                photo = None
        self._thumbs[rec["id"]] = photo
        return photo

    def refresh_history(self):
        flt = self.hist_filter.get().strip().lower()
        tree = self.hist_tree
        tree.delete(*tree.get_children())
        shown = 0
        for rec in self.history:
            hay = " ".join([rec.get("prompt_th", ""), rec.get("prompt_sent", ""), rec.get("image_model", "")]).lower()
            if flt and flt not in hay:
                continue
            tree.insert("", "end", iid=rec["id"], image=self._thumb_for(rec) or "", values=(
                rec["created"].replace("T", " ")[:16],
                rec["image_model"].split("/")[-1],
                fmt_usd(rec.get("cost_total")),
                rec.get("prompt_th", "").replace("\n", " ")[:120],
            ))
            shown += 1
        total = sum(r.get("cost_total") or 0 for r in self.history)
        self.hist_summary.configure(
            text=f"ทั้งหมด {len(self.history)} รายการ · แสดง {shown} · ค่าใช้จ่ายรวมในประวัติ {fmt_usd(total)}")

    def selected_record(self):
        sel = self.hist_tree.selection()
        if not sel:
            return None
        return next((r for r in self.history if r["id"] == sel[0]), None)

    def on_history_select(self):
        rec = self.selected_record()
        if not rec:
            return
        self.hist_view.set_image(APP_DIR / rec["image_file"])
        refs = ", ".join(r["name"] for r in rec.get("references", [])) or "-"
        est = " (ประมาณการ)" if rec.get("cost_estimated") else ""
        header = (f"เวลา: {rec['created'].replace('T', ' ')}\n"
                  f"โมเดลรูป: {rec['image_model']}\n"
                  f"โมเดลช่วยคิด: {rec.get('text_model') or '-'} · โหมด: {rec.get('enhance_mode')}\n"
                  f"อัตราส่วน: {rec.get('aspect_ratio')} · reference: {refs}\n"
                  f"ต้นทุน: {fmt_usd(rec.get('cost_total'))}{est} "
                  f"(รูป {fmt_usd(rec.get('cost_image'))}"
                  f"{', prompt ' + fmt_usd(rec['cost_prompt']) if rec.get('cost_prompt') is not None else ''})\n\n"
                  f"[prompt ไทย]\n{rec['prompt_th']}\n\n[prompt ที่ส่งจริง]\n{rec['prompt_sent']}")
        set_text(self.hist_detail, header)

    def reuse_history(self, what):
        rec = self.selected_record()
        if not rec:
            messagebox.showinfo(APP_TITLE, "เลือกรายการในประวัติก่อน", parent=self)
            return
        if what == "en":
            text = rec["prompt_sent"]
            self.enhance_var.set(ENHANCE_OFF)
        else:
            text = rec["prompt_th"]
        self.prompt_text.delete("1.0", "end")
        self.prompt_text.insert("1.0", text)
        if what == "all":
            self.enhance_var.set(rec.get("enhance_mode", ENHANCE_OFF))
            self.aspect_var.set(rec.get("aspect_ratio", ASPECT_RATIOS[0]))
            if rec.get("image_model"):
                self.image_combo.set(rec["image_model"])
            if rec.get("text_model"):
                self.text_combo.set(rec["text_model"])
            self.references = []
            missing = []
            for ref in rec.get("references", []):
                try:
                    self.references.append(load_reference(ref["path"]))
                except (OSError, ValueError):
                    missing.append(ref["name"])
            self._refresh_ref_list()
            self._update_model_hints()
            if missing:
                messagebox.showwarning(APP_TITLE, "ไม่พบไฟล์ reference เหล่านี้แล้ว:\n" + "\n".join(missing), parent=self)
        self.notebook.select(self.tab_generate)
        self.set_status("โหลด prompt จากประวัติแล้ว")

    def delete_history(self):
        rec = self.selected_record()
        if not rec:
            return
        if not messagebox.askyesno(APP_TITLE, "ลบรายการนี้ออกจากประวัติ และลบไฟล์รูปด้วยหรือไม่?", parent=self):
            return
        try:
            (APP_DIR / rec["image_file"]).unlink(missing_ok=True)
        except OSError:
            pass
        self.history = [r for r in self.history if r["id"] != rec["id"]]
        self._thumbs.pop(rec["id"], None)
        save_json(HISTORY_FILE, self.history)
        self.refresh_history()
        self.hist_view.set_image(None)
        set_text(self.hist_detail, "")

    # ----- models tab

    def _build_models_tab(self, parent):
        top = ttk.Frame(parent, padding=(8, 8, 8, 0))
        top.pack(fill="x")
        self.model_kind = tk.StringVar(value="image")
        ttk.Radiobutton(top, text="โมเดลสร้างรูป (output เป็นภาพ)", value="image",
                        variable=self.model_kind, command=self.refresh_model_table).pack(side="left")
        ttk.Radiobutton(top, text="โมเดลข้อความ (ช่วยคิด prompt)", value="text",
                        variable=self.model_kind, command=self.refresh_model_table).pack(side="left", padx=12)
        self.model_filter = tk.StringVar()
        self.model_filter.trace_add("write", lambda *_: self.refresh_model_table())
        ttk.Entry(top, textvariable=self.model_filter, width=30).pack(side="right")
        ttk.Label(top, text="ค้นหา:").pack(side="right", padx=6)
        self.sort_var = tk.StringVar(value=SORT_OPTIONS[0])
        sort_box = ttk.Combobox(top, textvariable=self.sort_var, values=SORT_OPTIONS,
                                state="readonly", width=16)
        sort_box.pack(side="right", padx=(6, 18))
        sort_box.bind("<<ComboboxSelected>>", lambda _e: self.refresh_model_table())
        ttk.Label(top, text="เรียงตาม:").pack(side="right")

        wrap = ttk.Frame(parent, padding=8)
        wrap.pack(fill="both", expand=True)
        self.model_tree = ttk.Treeview(wrap, columns=("id", "name", "input", "est", "price"), show="headings",
                                       selectmode="browse", height=12)
        for col, title, width, stretch in (("id", "Model ID", 260, False), ("name", "ชื่อ", 200, False),
                                           ("input", "รับ input", 130, False),
                                           ("est", "ประมาณ/ครั้ง", 110, False),
                                           ("price", "ราคาละเอียด", 330, True)):
            self.model_tree.heading(col, text=title)
            self.model_tree.column(col, width=width, stretch=stretch)
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.model_tree.yview)
        self.model_tree.configure(yscrollcommand=scroll.set)
        self.model_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.model_tree.bind("<<TreeviewSelect>>", lambda _e: self.on_model_select())

        bottom = ttk.Frame(parent, padding=(8, 0, 8, 8))
        bottom.pack(fill="x")
        self.model_detail = tk.Text(bottom, height=9, wrap="word", relief="flat", bg=self._bg(), bd=0)
        self.model_detail.pack(fill="x")
        btns = ttk.Frame(bottom)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="ตั้งเป็นโมเดลสร้างรูป", command=self.use_selected_as_image).pack(side="left")
        ttk.Button(btns, text="ตั้งเป็นโมเดลช่วยคิด prompt", command=self.use_selected_as_text).pack(side="left", padx=6)
        ttk.Button(btns, text="โหลดรายการโมเดลใหม่", command=self.load_models).pack(side="right")

    def refresh_model_table(self):
        kind = self.model_kind.get()
        flt = self.model_filter.get().strip().lower()
        tree = self.model_tree
        tree.delete(*tree.get_children())
        rows = []
        for mid, m in self.models_by_id.items():
            inp, out = model_modalities(m)
            if kind == "image" and "image" not in out:
                continue
            if kind == "text" and "text" not in out:
                continue
            name = m.get("name") or ""
            if flt and flt not in f"{mid} {name}".lower():
                continue
            cost = est_typical_cost(m, kind)
            rows.append((mid, name, inp, cost))

        sort_by = self.sort_var.get()
        if sort_by == SORT_OPTIONS[1]:  # ถูกสุดก่อน (ไม่ทราบราคาไปท้ายสุด)
            rows.sort(key=lambda r: (r[3] is None, r[3] or 0))
        elif sort_by == SORT_OPTIONS[2]:  # แพงสุดก่อน
            rows.sort(key=lambda r: (r[3] is None, -(r[3] or 0)))
        else:
            rows.sort(key=lambda r: r[0])

        for mid, name, inp, cost in rows:
            tree.insert("", "end", iid=mid, values=(
                mid, name, ", ".join(inp), fmt_usd(cost) if cost is not None else "ไม่ทราบ",
                price_summary(self.models_by_id[mid])))
        if not self.models_by_id:
            set_text(self.model_detail, "ยังไม่มีรายการโมเดล — ตั้ง API Key แล้วกด F5 หรือปุ่ม 'โหลดรายการโมเดลใหม่'")

    def on_model_select(self):
        sel = self.model_tree.selection()
        if not sel:
            return
        m = self.models_by_id.get(sel[0])
        if not m:
            return
        inp, out = model_modalities(m)
        p = m.get("pricing") or {}

        def per(key, unit):
            v = to_float(p.get(key))
            return f"${v:.8f} {unit}" if v is not None else "-"

        ctx = m.get("context_length")
        desc = (m.get("description") or "").strip().replace("\n", " ")
        lines = [
            f"{m.get('name') or sel[0]}   [{sel[0]}]",
            f"รับ input: {', '.join(inp)}    ส่ง output: {', '.join(out)}"
            + (f"    context: {ctx:,} tokens" if ctx else ""),
            f"ราคา input: {per('prompt', 'ต่อ token')}  |  output: {per('completion', 'ต่อ token')}",
            f"ราคารูปที่ออก (image_output): {per('image_output', 'ต่อ token')}  |  "
            f"image: {per('image', 'ต่อรูป')}  |  request: {per('request', 'ต่อ request')}",
            f"สรุป: {price_summary(m)}",
        ]
        if desc:
            lines.append("\n" + desc[:500])
        set_text(self.model_detail, "\n".join(lines))

    def use_selected_as_image(self):
        sel = self.model_tree.selection()
        if not sel:
            return
        mid = sel[0]
        if "image" not in model_modalities(self.models_by_id[mid])[1]:
            messagebox.showwarning(APP_TITLE, "โมเดลนี้ไม่ได้ส่งรูปภาพกลับมา", parent=self)
            return
        self.image_combo.set(mid)
        self._update_model_hints()
        self.notebook.select(self.tab_generate)
        self.set_status(f"ตั้งโมเดลสร้างรูปเป็น {mid}")

    def use_selected_as_text(self):
        sel = self.model_tree.selection()
        if not sel:
            return
        mid = sel[0]
        if "text" not in model_modalities(self.models_by_id[mid])[1]:
            messagebox.showwarning(APP_TITLE, "โมเดลนี้ไม่ได้ส่งข้อความกลับมา", parent=self)
            return
        self.text_combo.set(mid)
        self._update_model_hints()
        self.set_status(f"ตั้งโมเดลช่วยคิด prompt เป็น {mid}")

    # ----- records (shared)

    def save_record_as(self, rec):
        if not rec:
            messagebox.showinfo(APP_TITLE, "ยังไม่มีรูปให้บันทึก", parent=self)
            return
        src = APP_DIR / rec["image_file"]
        dst = filedialog.asksaveasfilename(parent=self, initialfile=src.name, defaultextension=src.suffix,
                                           filetypes=[("รูปภาพ", f"*{src.suffix}"), ("ทั้งหมด", "*.*")])
        if dst:
            shutil.copyfile(src, dst)
            self.set_status(f"บันทึกรูปไปที่ {dst}")

    def open_record(self, rec):
        if not rec:
            messagebox.showinfo(APP_TITLE, "ยังไม่มีรูปให้เปิด", parent=self)
            return
        try:
            open_path(APP_DIR / rec["image_file"])
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"เปิดไฟล์ไม่ได้: {e}", parent=self)

    def copy_text(self, text):
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.set_status("คัดลอกแล้ว")

    # ----- settings / key

    def api_key(self):
        return (self.config_data.get("api_key") or os.environ.get("OPENROUTER_API_KEY") or "").strip()

    def _require_key(self):
        key = self.api_key()
        if not key:
            messagebox.showwarning(APP_TITLE, "ยังไม่ได้ตั้งค่า API Key\nไปที่เมนู ไฟล์ / ตั้งค่า > ตั้งค่า API Key",
                                   parent=self)
            self.open_settings()
        return key

    def _update_key_label(self):
        if self.api_key():
            self.key_var.set("API Key: ตั้งค่าแล้ว")
            self.key_label.configure(foreground="#15803d")
        else:
            self.key_var.set("⚠ ยังไม่ได้ตั้งค่า API Key")
            self.key_label.configure(foreground="#b91c1c")

    def open_settings(self):
        win = tk.Toplevel(self)
        win.title("ตั้งค่า API Key")
        win.transient(self)
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="OpenRouter API Key", font=tkfont.nametofont("TkHeadingFont")).pack(anchor="w")
        ttk.Label(frm, style="Key.TLabel", text="สร้างได้ที่ openrouter.ai/keys (ขึ้นต้นด้วย sk-or-)").pack(anchor="w", pady=(0, 8))
        var = tk.StringVar(value=self.config_data.get("api_key", ""))
        entry = ttk.Entry(frm, textvariable=var, width=60, show="•")
        entry.pack(fill="x")
        show = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="แสดงค่า", variable=show,
                        command=lambda: entry.configure(show="" if show.get() else "•")).pack(anchor="w", pady=4)
        info = ttk.Label(frm, style="Key.TLabel", wraplength=420, justify="left", text="")
        info.pack(anchor="w", pady=(4, 8))

        def test():
            key = var.get().strip()
            if not key:
                info.configure(text="กรุณาใส่ key ก่อน")
                return
            info.configure(text="กำลังทดสอบ…")

            def ok(data):
                used = to_float(data.get("usage"))
                limit = to_float(data.get("limit"))
                lim = f"วงเงิน ${limit:.2f}" if limit is not None else "ไม่จำกัดวงเงิน"
                info.configure(text=f"✔ ใช้งานได้ · ใช้ไปแล้ว {fmt_usd(used or 0)} · {lim}")

            self.run_bg(OpenRouterClient(key).key_info, on_ok=ok,
                        on_err=lambda e: info.configure(text=f"ไม่สำเร็จ: {e}"))

        def save():
            self.config_data["api_key"] = var.get().strip()
            save_json(CONFIG_FILE, self.config_data)
            win.destroy()
            self._update_key_label()
            if self.api_key():
                self.load_models()

        btns = ttk.Frame(frm)
        btns.pack(fill="x")
        ttk.Button(btns, text="ทดสอบ Key", command=test).pack(side="left")
        ttk.Button(btns, text="บันทึก", style="Accent.TButton", command=save).pack(side="right")
        ttk.Button(btns, text="ยกเลิก", command=win.destroy).pack(side="right", padx=6)
        win.grab_set()
        entry.focus_set()

    # ----- models loading

    def load_models(self):
        key = self.api_key()
        if not key:
            self.set_status("ยังไม่มี API Key — ตั้งค่าก่อนจึงจะโหลดรายการโมเดลได้")
            return
        self.set_status("กำลังโหลดรายการโมเดลจาก OpenRouter…")
        self.run_bg(OpenRouterClient(key).list_models, on_ok=self._on_models_loaded,
                    on_err=lambda e: self.set_status(f"โหลดรายการโมเดลไม่สำเร็จ: {e}"))

    def _on_models_loaded(self, models):
        self.models_by_id = {m["id"]: m for m in models if m.get("id")}
        image_ids = sorted(i for i, m in self.models_by_id.items() if "image" in model_modalities(m)[1])
        text_ids = sorted(i for i, m in self.models_by_id.items() if "text" in model_modalities(m)[1])
        self.image_combo["values"] = image_ids or [DEFAULT_IMAGE_MODEL]
        self.text_combo["values"] = text_ids or [DEFAULT_TEXT_MODEL]
        self._update_model_hints()
        self.refresh_model_table()
        self.set_status(f"โหลดโมเดลแล้ว: {len(image_ids)} โมเดลสร้างรูป, {len(text_ids)} โมเดลข้อความ")

    def _initial_load(self):
        self.refresh_history()
        if self.api_key():
            self.load_models()
        else:
            self.set_status("ยังไม่มี API Key — ใส่ key ในหน้าต่างตั้งค่าที่เปิดขึ้นมา")
            self.open_settings()

    # ----- background plumbing

    def run_bg(self, fn, on_ok=None, on_err=None):
        """รัน fn ใน thread แยก แล้วส่งผลกลับมาทำงานบน UI thread ผ่าน queue"""
        def target():
            try:
                result = fn()
            except Exception as e:  # ส่งต่อให้ UI แสดง (e ถูกลบหลังจบ except จึงต้อง bind ค่าไว้)
                self.ui_queue.put(lambda err=e: (on_err or self._show_error)(err))
            else:
                if on_ok:
                    self.ui_queue.put(lambda: on_ok(result))
        threading.Thread(target=target, daemon=True).start()

    def _poll_queue(self):
        while True:
            try:
                fn = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except tk.TclError:
                pass  # หน้าต่างถูกปิดไปแล้ว
            except Exception as e:
                self._show_error(e)
        self.after(100, self._poll_queue)

    def _show_error(self, err):
        self._set_busy(False, "เกิดข้อผิดพลาด")
        messagebox.showerror(APP_TITLE, str(err), parent=self)

    def _set_busy(self, busy, msg=""):
        self.busy = busy
        if busy:  # ระหว่างสร้างรูป ปุ่มเดียวกันกลายเป็นปุ่มยกเลิก
            self.gen_btn.configure(text="ยกเลิก", command=self.cancel_generate)
            self.progress.start(12)
        else:
            self.gen_btn.configure(text="สร้างรูป", command=self.start_generate)
            self.progress.stop()
        self.set_status(msg)

    def set_status(self, msg):
        self.status_var.set(msg)

    def on_close(self):
        self.config_data.update(image_model=self.image_combo.get().strip(),
                                text_model=self.text_combo.get().strip(),
                                enhance_mode=self.enhance_var.get(),
                                aspect_ratio=self.aspect_var.get())
        save_json(CONFIG_FILE, self.config_data)
        self.destroy()


if __name__ == "__main__":
    if Image is None:
        _root = tk.Tk()
        _root.withdraw()
        messagebox.showerror(APP_TITLE, "ต้องติดตั้ง Pillow ก่อน\n\npip install pillow")
        _root.destroy()
        raise SystemExit(1)
    App().mainloop()
