import re, time, threading
import pyautogui, pytesseract, keyboard
from PIL import Image, ImageOps, ImageFilter
import tkinter as tk
from sympy import symbols

# ==== EDIT THIS PATH IF NEEDED ====
pytesseract.pytesseract.tesseract_cmd = r"D:\Program Files\Tesseract-OCR\tesseract.exe"

x = symbols('x')

# Globals for the capture region (x, y, w, h)
region = [100, 200, 600, 180]  # default; will be overwritten after calibration
p1 = None  # top-left
p2 = None  # bottom-right
stop_flag = False

# --- GUI ---
root = tk.Tk()
root.title("Equation Solver")
root.attributes("-topmost", True)
root.configure(bg="black")

lbl_eq = tk.Label(root, text="Calibrate with F8/F9 →", font=("Consolas", 24), fg="white", bg="black", justify="left")
lbl_eq.pack(padx=12, pady=(12, 6), anchor="w")

lbl_ans = tk.Label(root, text="Answer: —", font=("Consolas", 28, "bold"), fg="white", bg="black", justify="left")
lbl_ans.pack(padx=12, pady=6, anchor="w")

lbl_reg = tk.Label(root, text="Region: ?", font=("Consolas", 12), fg="gray90", bg="black", justify="left")
lbl_reg.pack(padx=12, pady=(0, 12), anchor="w")

def fmt_region(r):
    return f"Region (x,y,w,h): {r[0]}, {r[1]}, {r[2]}, {r[3]}"

lbl_reg.config(text=fmt_region(region))

# --- Calibration hotkeys ---
def set_top_left():
    global p1
    p1 = pyautogui.position()
    lbl_eq.config(text=f"Top-left set: {p1}. Now move to bottom-right and press F9.")

def set_bottom_right():
    global p1, p2, region
    p2 = pyautogui.position()
    if p1 is None:
        lbl_eq.config(text="Set top-left first with F8.")
        return
    x0, y0 = p1
    x1, y1 = p2
    x_min, y_min = min(x0, x1), min(y0, y1)
    w, h = abs(x1 - x0), abs(y1 - y0)
    # minimum sensible size
    w = max(w, 200)
    h = max(h, 80)
    region = [x_min, y_min, w, h]
    lbl_reg.config(text=fmt_region(region))
    lbl_eq.config(text="Calibrated. Solving… (Press F8/F9 to recalibrate)")

keyboard.add_hotkey("F8", set_top_left)
keyboard.add_hotkey("F9", set_bottom_right)

# --- OCR + solve ---
def clean_text(t: str) -> str:
    # Normalize common OCR variants
    t = t.replace("×", "*").replace("·", "*").replace("x", "*").replace("X", "*")
    t = t.replace("÷", "/")
    # Fix common slash confusions
    t = t.replace("I/", "/").replace("|/", "/").replace("l/", "/")
    # Normalize equals and dashes
    t = t.replace("＝", "=").replace("—", "-").replace("–", "-")
    # Decimal comma -> dot
    t = re.sub(r'(?<=\d),(?=\d)', '.', t)
    # Remove stray unicode spaces
    t = t.replace("\u2009", " ").replace("\u00a0", " ")
    # Collapse spaces
    t = re.sub(r'\s+', ' ', t).strip()
    return t

# --- Regex + solver ---
num = r'[-+]?\d+(?:[.,]\d+)?'   # supports negative + decimals with comma/dot
OPS = r'[+\-*/]'
Q   = r'[?]'

# A op B = ?
pat1 = re.compile(rf'({num})\s*({OPS})\s*({num})\s*=\s*{Q}')
# A op ? = C
pat2 = re.compile(rf'({num})\s*({OPS})\s*{Q}\s*=\s*({num})')
# ? op B = C   <-- your case
pat3 = re.compile(rf'{Q}\s*({OPS})\s*({num})\s*=\s*({num})')

def f2(v):
    try:
        return f"{float(v):.6g}"
    except:
        return str(v)

def parse_float(s):
    return float(s.replace(',', '.'))

def solve_equation(txt):
    txt = clean_text(txt)

    # Try: A op B = ?
    m = pat1.search(txt)
    if m:
        a, op, b = parse_float(m.group(1)), m.group(2), parse_float(m.group(3))
        if op == '+': ans = a + b
        elif op == '-': ans = a - b
        elif op == '*': ans = a * b
        elif op == '/': ans = a / b if b != 0 else float('inf')
        return txt, ans

    # Try: A op ? = C
    m = pat2.search(txt)
    if m:
        a, op, c = parse_float(m.group(1)), m.group(2), parse_float(m.group(3))
        if op == '+': ans = c - a
        elif op == '-': ans = a - c
        elif op == '*': ans = c / a if a != 0 else float('inf')
        elif op == '/': ans = a / c if c != 0 else float('inf')
        return txt, ans

    # Try: ? op B = C   (e.g., "? / 95 = 59")
    m = pat3.search(txt)
    if m:
        op, b, c = m.group(1), parse_float(m.group(2)), parse_float(m.group(3))
        if op == '+': ans = c - b             # x + b = c
        elif op == '-': ans = c + b           # x - b = c  -> x = c + b
        elif op == '*': ans = c / b if b != 0 else float('inf')   # x*b = c
        elif op == '/': ans = c * b           # x / b = c   -> x = c*b
        return txt, ans

    return None, None

def ocr_once():
    # Grab region
    x, y, w, h = region
    img = pyautogui.screenshot(region=(x, y, w, h))
    # Preprocess for light text on dark bg
    im = ImageOps.grayscale(img)
    # Try binarization to reduce halos
    im = ImageOps.autocontrast(im)
    im = im.filter(ImageFilter.SHARPEN)
    # Assume single line of text (works great for "… = ?")
    txt = pytesseract.image_to_string(im, config="--oem 3 --psm 7")
    return txt

def loop():
    last_shown = ""
    while not stop_flag:
        try:
            raw = ocr_once()
            s, ans = solve_equation(raw or "")
            if s:
                msg_eq = s
                msg_ans = f"Answer: {f2(ans)}"
            else:
                msg_eq = "No equation detected"
                msg_ans = "Answer: —"
            # Update UI only if changed (keeps it snappy)
            combined = msg_eq + "|" + msg_ans
            if combined != last_shown:
                lbl_eq.config(text=msg_eq)
                lbl_ans.config(text=msg_ans)
                last_shown = combined
        except Exception as e:
            lbl_eq.config(text=f"Error: {e}")
            lbl_ans.config(text="Answer: —")
        time.sleep(0.15)  # ~150 ms
    print("Loop stopped.")

thr = threading.Thread(target=loop, daemon=True)
thr.start()

def on_close():
    global stop_flag
    stop_flag = True
    try:
        keyboard.unhook_all()
    except:
        pass
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()
