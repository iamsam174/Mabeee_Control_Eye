import tkinter as tk
from tkinter import ttk, messagebox
import threading
import cv2
from PIL import Image, ImageTk
import winsound
import sys
import asyncio
import traceback
import configparser
import os
from bleak import BleakClient, BleakScanner
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("MaBeee Control Eye App")
        
        # 画面設定（デフォルトで最大化、F11で全画面切替）
        self.root.state('zoomed')
        self.root.configure(bg="#f0f0f0") # 背景色を明るいグレーに
        
        # 設定ファイルの読み込み
        self.config_file = "config.ini"
        self.config = configparser.ConfigParser()
        self.load_config()
        
        # キーバインドの設定
        self.root.bind("<Escape>", lambda e: self.root.attributes("-fullscreen", False))
        self.root.bind("<F11>", self.toggle_fullscreen)
        
        # モード切替ショートカット
        self.root.bind("1", lambda e: self.mode.set(1))
        self.root.bind("2", lambda e: self.mode.set(2))
        self.root.bind("3", lambda e: self.mode.set(3))
        
        # 矢印キーでのタイマー変更バインド
        self.root.bind("<Left>", self.decrease_timer)
        self.root.bind("<Right>", self.increase_timer)
        
        self.target_mac = None
        self.client = None
        self.active_char_uuid = None # 確定した1つの窓口UUID
        self.is_running = False
        self.cap = None
        self.loop = None
        
        # 設定値の反映
        self.sound = tk.BooleanVar(value=self.config.getboolean('Settings', 'sound', fallback=True))
        self.mode = tk.IntVar(value=self.config.getint('Settings', 'mode', fallback=1))
        self.found_devs = []
        self.size_var = tk.StringVar(value=self.config.get('Settings', 'size', fallback="中"))
        self.sizes = {"特大": (1000, 563), "大": (800, 450), "中": (600, 338), "小": (400, 225)}
        
        try:
            self.setup_ui()
            self.root.after(100, self.update_camera)
            self.root.after(200, self.start_thread)
        except Exception as e:
            messagebox.showerror("UI起動エラー", traceback.format_exc())
            sys.exit()

    def load_config(self):
        if os.path.exists(self.config_file):
            self.config.read(self.config_file, encoding='utf-8')
        else:
            self.config['Settings'] = {
                'sound': 'True',
                'mode': '1',
                'size': '中',
                'timer': '5',
                'camera': 'カメラなし'
            }
            self.save_config()

    def save_config(self):
        with open(self.config_file, 'w', encoding='utf-8') as configfile:
            self.config.write(configfile)

    # 各種設定変更時に自動保存するメソッド
    def on_setting_change(self, *args):
        if not self.config.has_section('Settings'):
            self.config.add_section('Settings')
        self.config.set('Settings', 'sound', str(self.sound.get()))
        self.config.set('Settings', 'mode', str(self.mode.get()))
        self.config.set('Settings', 'size', self.size_var.get())
        if hasattr(self, 'sc_t'):
            self.config.set('Settings', 'timer', str(self.sc_t.get()))
        if hasattr(self, 'cb_cam'):
            self.config.set('Settings', 'camera', self.cb_cam.get())
        self.save_config()

    # タイマー加減算用メソッド
    def decrease_timer(self, event=None):
        current = self.sc_t.get()
        if current > 1:
            self.sc_t.set(current - 1)
            self.on_setting_change()
    def increase_timer(self, event=None):
        current = self.sc_t.get()
        if current < 180:
            self.sc_t.set(current + 1)
            self.on_setting_change()
    def toggle_fullscreen(self, event=None):
        is_full = self.root.attributes("-fullscreen")
        self.root.attributes("-fullscreen", not is_full)
        return "break"
    def setup_ui(self):
        f_b = ("Yu Gothic", 12, "bold")
        
        self.header = tk.Frame(self.root, bg="#f0f0f0")
        self.header.pack(side="top", fill="x", padx=40, pady=5)
        # 1. 設定セクション
        adm = tk.LabelFrame(self.header, text=" 設定 ", font=f_b, bg="white", fg="#333", padx=15, pady=10)
        adm.pack(fill="x", pady=2)
        r1 = tk.Frame(adm, bg="white")
        r1.pack(fill="x", pady=2)
        tk.Button(r1, text="🔍 MaBeeeを探査", command=self.scan, font=f_b, bg="#4CAF50", fg="white", padx=10).pack(side="left", padx=5)
        self.lbl_s = tk.Label(r1, text="スキャン待機中", font=f_b, bg="white")
        self.lbl_s.pack(side="left", padx=15)
        tk.Label(r1, text="ペアリング:", font=f_b, bg="white").pack(side="left")
        self.cb_dev = ttk.Combobox(r1, state="readonly", width=27, font=("Consolas", 10))
        self.cb_dev.pack(side="left", padx=5)
        tk.Button(r1, text="接続", command=self.conn, font=f_b, bg="#2196F3", fg="white", padx=10).pack(side="left", padx=5)
        tk.Label(r1, text=" | カメラ:", font=f_b, bg="white").pack(side="left", padx=(15,0))
        self.cb_cam = ttk.Combobox(r1, state="readonly", width=10, font=f_b)
        self.cb_cam['values'] = ("カメラ1", "カメラ2", "カメラなし")
        saved_cam = self.config.get('Settings', 'camera', fallback="カメラなし")
        if saved_cam in self.cb_cam['values']:
            self.cb_cam.set(saved_cam)
        else:
            self.cb_cam.current(2)
        self.cb_cam.pack(side="left", padx=5)
        self.cb_cam.bind("<<ComboboxSelected>>", self.cam_chg)
        # タイマー設定の配置
        tk.Label(r1, text=" | タイマー設定 (1～180秒):", font=f_b, bg="white").pack(side="left", padx=(15,0))
        self.sc_t = tk.Scale(r1, from_=1, to=180, orient="horizontal", length=300, bg="white", highlightthickness=0, font=f_b, command=lambda e: self.on_setting_change())
        self.sc_t.set(self.config.getint('Settings', 'timer', fallback=5))
        self.sc_t.pack(side="left", padx=10)
        r2 = tk.Frame(adm, bg="white")
        r2.pack(fill="x", pady=(10, 0))
        tk.Checkbutton(r2, text="操作音を有効にする", variable=self.sound, font=f_b, bg="white", command=self.on_setting_change).pack(side="left", padx=10)
        tk.Label(r2, text=" | 動作モード:", font=f_b, bg="white").pack(side="left", padx=(10,0))
        tk.Radiobutton(r2, text="①クリック/注視でタイマー実行", variable=self.mode, value=1, font=f_b, bg="white", command=self.on_setting_change).pack(side="left", padx=5)
        tk.Radiobutton(r2, text="②マウスオーバーでタイマー実行", variable=self.mode, value=2, font=f_b, bg="white", command=self.on_setting_change).pack(side="left", padx=5)
        tk.Radiobutton(r2, text="③マウスポインターがボタン内にある間ON", variable=self.mode, value=3, font=f_b, bg="white", command=self.on_setting_change).pack(side="left", padx=5)
        # ボタンサイズ設定の配置
        tk.Label(r2, text=" | ボタンサイズ:", font=f_b, bg="white").pack(side="left", padx=(15,0))
        self.cb_size = ttk.Combobox(r2, textvariable=self.size_var, state="readonly", width=5, font=f_b)
        self.cb_size['values'] = ("特大", "大", "中", "小")
        self.cb_size.pack(side="left", padx=5)
        self.cb_size.bind("<<ComboboxSelected>>", self.resize_canvas)
        # 操作エリア
        self.canvas_container = tk.Frame(self.root, bg="#f0f0f0")
        self.canvas_container.place(relx=0.5, rely=0.6, anchor="center")
        btn_color = "#add8e6"
        btn_hl_color = "#87ceeb"
        
        w, h = self.sizes[self.size_var.get()]
        self.cv = tk.Canvas(self.canvas_container, width=w, height=h, bg=btn_color, highlightthickness=10, highlightbackground=btn_hl_color)
        self.cv.pack()
        self.id_i = self.cv.create_image(w//2, h//2, anchor="center")
        self.id_t = self.cv.create_text(w//2, h//2, text="マビーON", font=("Yu Gothic", 48, "bold"), fill="#333333", anchor="center")
        self.cv.bind("<Button-1>", self.on_start_drag)
        self.cv.bind("<B1-Motion>", self.on_drag)
        self.cv.bind("<ButtonRelease-1>", self.on_stop_drag)
        
        self.cv.bind("<Enter>", lambda e: self.ent())
        self.cv.bind("<Leave>", lambda e: self.lev())
        # ヘルプテキスト
        self.lbl_esc = tk.Label(self.root, text="※[マビーON]ボタンはマウスドラッグで移動可 / [F11]キー:全画面表示切替 / [1][2][3]キー:動作モード切替 / [←][→]キー:タイマー秒数設定", font=f_b, bg="#f0f0f0", fg="#555")
        self.lbl_esc.pack(side="bottom", pady=10)
    def on_start_drag(self, event):
        self._drag_start_x = event.x
        self._drag_start_y = event.y
        self._is_dragging = False
    def on_drag(self, event):
        if abs(event.x - self._drag_start_x) > 5 or abs(event.y - self._drag_start_y) > 5:
            self._is_dragging = True
            x = self.canvas_container.winfo_x() + (event.x - self._drag_start_x)
            y = self.canvas_container.winfo_y() + (event.y - self._drag_start_y)
            self.canvas_container.place(x=x, y=y, anchor="nw", relx=0, rely=0)
    def on_stop_drag(self, event):
        if not getattr(self, '_is_dragging', False):
            self.act()
        self._is_dragging = False
    def resize_canvas(self, event=None):
        self.on_setting_change()
        w, h = self.sizes[self.size_var.get()]
        self.cv.config(width=w, height=h)
        self.cv.coords(self.id_i, w//2, h//2)
        s = self.cb_cam.get()
        if s == "カメラなし":
            self.cv.coords(self.id_t, w//2, h//2)
            self.cv.itemconfig(self.id_t, font=("Yu Gothic", 48, "bold"))
        else:
            self.cv.coords(self.id_t, w//2, 40)
            self.cv.itemconfig(self.id_t, font=("Yu Gothic", 28, "bold"))
    def cam_chg(self, e=None):
        self.on_setting_change()
        w, h = self.sizes[self.size_var.get()]
        s = self.cb_cam.get()
        if self.cap: self.cap.release()
        if s == "カメラなし":
            self.cap = None
            self.cv.itemconfig(self.id_i, image="")
            self.cv.coords(self.id_t, w//2, h//2)
            self.cv.itemconfig(self.id_t, font=("Yu Gothic", 48, "bold"))
        else:
            self.cv.coords(self.id_t, w//2, 40)
            self.cv.itemconfig(self.id_t, font=("Yu Gothic", 28, "bold"))
            idx = 0 if s == "カメラ1" else 1
            self.cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
    def update_camera(self):
        try:
            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret:
                    w, h = self.sizes[self.size_var.get()]
                    frame = cv2.resize(cv2.flip(frame, 1), (w, h))
                    self.tk_img = ImageTk.PhotoImage(image=Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
                    self.cv.itemconfig(self.id_i, image=self.tk_img)
        except Exception: pass
        self.root.after(15, self.update_camera)
    def start_thread(self):
        def run():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.loop.create_task(self.keep())
            self.loop.run_forever()
        threading.Thread(target=run, daemon=True).start()
    async def keep(self):
        while True:
            await asyncio.sleep(2)
            if self.target_mac and (self.client is None or not self.client.is_connected):
                await self.do_connect()
    async def do_connect(self):
        self.up_s("接続中...", "orange")
        try:
            if self.client: await self.client.disconnect()
            self.client = BleakClient(self.target_mac, timeout=10.0)
            await self.client.connect()
            
            # --- MaBeeeの制御用UUIDを見つけるロジック ---
            found_uuid = None
            for service in self.client.services:
                for char in service.characteristics:
                    cid = char.uuid.lower()
                    if "write" in char.properties:
                        if "b9f53006" in cid or "ad11aa24" in cid:
                            found_uuid = char.uuid
                            break
                if found_uuid: break
            
            if found_uuid:
                self.active_char_uuid = found_uuid
                self.up_s("接続完了", "green")
                # 初期化: PWM 0% 送信
                try:
                    data = await self.client.read_gatt_char(found_uuid)
                    val = bytearray(data)
                    if len(val) >= 2: val[1] = 0
                    else: val = bytearray([0x01, 0x00, 0x00, 0x00, 0x00])
                    await self.client.write_gatt_char(found_uuid, bytes(val))
                except:
                    try: await self.client.write_gatt_char(found_uuid, bytearray([0x01, 0x00, 0x00, 0x00, 0x00]))
                    except: pass
            else:
                self.up_s("窓口不明", "red")
        except Exception as e:
            self.up_s("再試行中...", "red")
    def up_s(self, t, c):
        if self.root: self.root.after(0, lambda: self.lbl_s.config(text=t, fg=c))
    def scan(self):
        if not self.loop: return
        self.up_s("スキャン中...", "blue")
        async def do():
            try:
                ds = await BleakScanner.discover(timeout=5.0)
                nms, found = [], []
                for d in ds:
                    if d.name and "mabeee" in d.name.lower():
                        found.append(d.address)
                        nms.append(f"{d.name} ({d.address})")
                self.root.after(0, lambda: self.update_dev_list(nms, found))
                self.up_s("スキャン完了", "black")
            except Exception: pass
        asyncio.run_coroutine_threadsafe(do(), self.loop)
    def update_dev_list(self, nms, found):
        self.cb_dev.config(values=nms); self.found_devs = found
    def conn(self):
        i = self.cb_dev.current()
        if i >= 0: 
            self.target_mac = self.found_devs[i]
            if self.loop: asyncio.run_coroutine_threadsafe(self.do_connect(), self.loop)
    def send(self, on):
        if not self.client or not self.client.is_connected or not self.active_char_uuid: return
        
        pwm = 100 if on else 0
        
        async def do_send():
            try:
                # 現在の特性値を読み取り、PWM値(index 1)を更新して書き込む（MaBeeeのプロトコルに準拠）
                data = await self.client.read_gatt_char(self.active_char_uuid)
                val = bytearray(data)
                if len(val) >= 2:
                    val[1] = pwm
                else:
                    val = bytearray([0x01, pwm, 0x00, 0x00, 0x00])
                await self.client.write_gatt_char(self.active_char_uuid, bytes(val))
            except Exception as e:
                # 読み取り等失敗時は直接フォールバック送信
                try: 
                    val = bytearray([0x01, pwm, 0x00, 0x00, 0x00])
                    await self.client.write_gatt_char(self.active_char_uuid, bytes(val))
                except: pass
        asyncio.run_coroutine_threadsafe(do_send(), self.loop)
    def act(self):
        if self.mode.get() == 1: self.run_t()
    def ent(self):
        if self.mode.get() == 2: self.run_t()
        elif self.mode.get() == 3:
            self.send(True)
            if self.sound.get(): winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
            self.cv.itemconfig(self.id_t, text="実行中", fill="#FFFFFF")
            self.cv.config(highlightbackground="#F44336", bg="#F44336")
    def lev(self):
        if self.mode.get() == 3:
            self.send(False)
            if self.sound.get(): winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
            self.cv.itemconfig(self.id_t, text="マビーON", fill="#333333")
            self.cv.config(highlightbackground="#87ceeb", bg="#add8e6")
    def run_t(self):
        if self.is_running: return
        self.is_running = True
        self.send(True)
        if self.sound.get(): winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
        self.remaining = self.sc_t.get()
        self.cv.config(highlightbackground="#F44336", bg="#F44336")
        self.cv.itemconfig(self.id_t, fill="#FFFFFF")
        self.update_timer()
    def update_timer(self):
        if self.remaining > 0:
            self.cv.itemconfig(self.id_t, text=f"実行中 {self.remaining}秒")
            self.remaining -= 1
            self.root.after(1000, self.update_timer)
        else: 
            self.fin_t()
    def fin_t(self):
        self.send(False)
        self.cv.itemconfig(self.id_t, text="マビーON", fill="#333333")
        self.cv.config(highlightbackground="#87ceeb", bg="#add8e6")
        self.is_running = False
if __name__ == "__main__":
    r = tk.Tk()
    a = App(r)
    r.mainloop()
