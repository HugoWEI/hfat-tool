import re, time, threading
import pyautogui, pytesseract, keyboard
from PIL import Image, ImageOps, ImageFilter
import tkinter as tk
from fractions import Fraction
import numpy as np

# ---- EDIT if Tesseract is in a different folder ----
pytesseract.pytesseract.tesseract_cmd = r"D:\Program Files\Tesseract-OCR\tesseract.exe"

# =================== UI / CALIBRATION ===================
region = [200, 200, 800, 200]   # default; set via F8/F9
p1 = None
stop_flag = False

root = tk.Tk()
root.title("OCR Math Solver")
root.attributes("-topmost", True)
root.configure(bg="black")

lbl_eq = tk.Label(root, text="Calibrate with F8 (top-left) / F9 (bottom-right)", font=("Consolas", 20), fg="white", bg="black", justify="left")
lbl_eq.pack(padx=12, pady=(10, 6), anchor="w")
lbl_ans = tk.Label(root, text="Answer: —", font=("Consolas", 28, "bold"), fg="white", bg="black", justify="left")
lbl_ans.pack(padx=12, pady=6, anchor="w")
lbl_reg = tk.Label(root, text="", font=("Consolas", 12), fg="gray90", bg="black")
lbl_reg.pack(padx=12, pady=(0,10), anchor="w")

def fmt_region(r): return f"Region (x,y,w,h): {r[0]}, {r[1]}, {r[2]}, {r[3]}"
lbl_reg.config(text=fmt_region(region))

def set_top_left():
    global p1
    p1 = pyautogui.position()
    lbl_eq.config(text=f"Top-left set: {p1}. Now move to bottom-right and press F9.")

def set_bottom_right():
    global p1, region
    if p1 is None:
        lbl_eq.config(text="Press F8 at the top-left first.")
        return
    p2 = pyautogui.position()
    x0,y0 = p1
    x1,y1 = p2
    x, y = min(x0,x1), min(y0,y1)
    w, h = max(220, abs(x1-x0)), max(80, abs(y1-y0))
    region[:] = [x,y,w,h]
    lbl_reg.config(text=fmt_region(region))
    lbl_eq.config(text="Calibrated. Watching… (F8/F9 to recalibrate)")

keyboard.add_hotkey("F8", set_top_left)
keyboard.add_hotkey("F9", set_bottom_right)

# =================== OCR HELPERS ===================

def clean_text(t: str) -> str:
    # normalize characters and spacing for both equations & sequences
    t = t.replace("×","*").replace("·","*").replace("x","*").replace("X","*")
    t = t.replace("÷","/").replace("＝","=").replace("—","-").replace("–","-").replace("…"," ")
    t = t.replace("\u2009"," ").replace("\u00a0"," ")  # thin/nbsp
    # decimal comma -> dot
    t = re.sub(r'(?<=\d),(?=\d)', '.', t)
    # collapse multiple spaces
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def ocr_once():
    x,y,w,h = region
    shot = pyautogui.screenshot(region=(x,y,w,h))
    im = ImageOps.grayscale(shot)
    im = ImageOps.autocontrast(im)
    im = im.filter(ImageFilter.SHARPEN)
    # Both single-line and block modes try; whichever gives more digits wins
    txt7 = pytesseract.image_to_string(im, config="--oem 3 --psm 7 tessedit_char_whitelist=0123456789.-/*=,?/")
    txt6 = pytesseract.image_to_string(im, config="--oem 3 --psm 6 tessedit_char_whitelist=0123456789.-/*=,?/")
    t7, t6 = clean_text(txt7), clean_text(txt6)
    # pick the one with more number-like chars
    score7 = len(re.findall(r'[0-9]', t7))
    score6 = len(re.findall(r'[0-9]', t6))
    return t7 if score7 >= score6 else t6

# =================== EQUATION SOLVER ===================

def parse_float(s): return float(s.replace(',', '.'))

num = r'[-+]?\d+(?:[.]\d+)?'
OPS = r'[+\-*/]'
Q = r'\?'
pat1 = re.compile(rf'({num})\s*({OPS})\s*({num})\s*=\s*{Q}$')
pat2 = re.compile(rf'({num})\s*({OPS})\s*{Q}\s*=\s*({num})$')
pat3 = re.compile(rf'^{Q}\s*({OPS})\s*({num})\s*=\s*({num})$')

def solve_equation_line(line: str):
    line = clean_text(line)
    for p in (pat1, pat2, pat3):
        m = p.search(line)
        if m: break
    if not m: return None
    if p is pat1:
        a,op,b = parse_float(m.group(1)), m.group(2), parse_float(m.group(3))
        ans = {'+':a+b,'-':a-b,'*':a*b,'/':a/b if b!=0 else float('inf')}[op]
    elif p is pat2:
        a,op,c = parse_float(m.group(1)), m.group(2), parse_float(m.group(3))
        ans = {'+':c-a,'-':a-c,'*':(c/a if a!=0 else float('inf')),'/':(a/c if c!=0 else float('inf'))}[op]
    else:  # pat3  "? op b = c"
        op,b,c = m.group(1), parse_float(m.group(2)), parse_float(m.group(3))
        ans = {'+':c-b,'-':c+b,'*':(c/b if b!=0 else float('inf')),'/':c*b}[op]
    return ans

# =================== SEQUENCE SOLVER (with fraction support) ===================

def parse_token(tok: str):
    tok = tok.strip()
    if tok == "?": return None
    tok = re.sub(r'(?<=\d),(?=\d)', '.', tok)
    if re.fullmatch(r'[-+]?\d+/\d+', tok):
        n,d = tok.split('/')
        return Fraction(int(n), int(d))
    return Fraction(tok)  # Fraction parses ints/decimals as exact rationals

def grab_sequence_from_text(text: str):
    # pick the line with most numbers ending before a '?' OR just commas
    lines = text.splitlines() or [text]
    best, best_count = None, -1
    for L in lines:
        L2 = clean_text(L)
        if '?' not in L2 and ',' not in L2 and ' ' not in L2: 
            continue
        toks = re.findall(r'[-+]?\d+(?:[.]\d+)?(?:/\d+)?', L2.split('?')[0])
        if len(toks) > best_count:
            best = toks
            best_count = len(toks)
    if not best or len(best) < 3: return None
    try:
        seq = [parse_token(t) for t in best]
        if any(v is None for v in seq): return None
        return seq
    except Exception:
        return None

def diffs(seq):  return [seq[i+1]-seq[i] for i in range(len(seq)-1)]
def ratios(seq):
    out=[]
    for i in range(len(seq)-1):
        if seq[i]==0: return None
        out.append(seq[i+1] / seq[i])
    return out
def is_const(vals): 
    if not vals: return False
    m = sum(vals, Fraction(0,1))/len(vals)
    return all(v==m for v in vals)
def const(vals): return sum(vals, Fraction(0,1))/len(vals)

def h_arith(seq):
    d = diffs(seq)
    return seq[-1] + const(d) if is_const(d) else None

def h_geom(seq):
    r = ratios(seq)
    return seq[-1]*const(r) if r and is_const(r) else None

def h_quad(seq):
    if len(seq)<4: return None
    d1 = diffs(seq); d2 = diffs(d1)
    if is_const(d2):
        return seq[-1] + d1[-1] + const(d2)
    return None

def h_diff_geom(seq):
    d = diffs(seq)
    if len(d)<3: return None
    rr = ratios(d)
    if rr and is_const(rr):
        r = const(rr)
        return seq[-1] + d[-1]*r
    return None

def h_interleaved(seq):
    a = seq[0::2]; b = seq[1::2]
    def one(sub): return h_arith(sub) or h_geom(sub) or h_quad(sub) or h_diff_geom(sub)
    na, nb = one(a), one(b)
    if na is None or nb is None: return None
    return na if len(seq)%2==0 else nb

def h_frac_components(seq):
    if not any(x.denominator!=1 for x in seq): return None
    nums = [Fraction(x.numerator,1) for x in seq]
    dens = [Fraction(x.denominator,1) for x in seq]
    def one(sub): return h_arith(sub) or h_geom(sub) or h_quad(sub) or h_diff_geom(sub)
    nnext = one(nums); dnext = one(dens)
    if nnext is None and dnext is None: return None
    if nnext is None: nnext = nums[-1]
    if dnext is None: dnext = dens[-1]
    if dnext == 0: return None
    return Fraction(nnext, dnext)

def h_repeat(seq, max_p=4):
    n=len(seq)
    for p in range(1, min(max_p, n//2)+1):
        if all(seq[i]==seq[i-p] for i in range(p,n)):
            return seq[-p]
    return None

def h_poly(seq, max_deg=3):
    # Newton forward (finite-difference) with Fractions
    table = [seq[:]]
    for _ in range(max_deg):
        prev = table[-1]
        if len(prev)<2: break
        table.append(diffs(prev))
    nxt = table[0][-1]
    for k in range(1, len(table)):
        nxt += table[k][-1]
    return nxt

def solve_sequence(seq):
    for h in (h_arith, h_geom, h_quad, h_diff_geom, h_interleaved, h_frac_components, h_repeat):
        out = h(seq)
        if out is not None: return out
    return h_poly(seq)

def fmt(fr: Fraction):
    fr = fr.limit_denominator()
    return str(fr.numerator) if fr.denominator==1 else f"{fr.numerator}/{fr.denominator}"

# =================== MAIN LOOP ===================

def main_loop():
    last = ""
    while not stop_flag:
        try:
            text = ocr_once()
            # Try equations first (only if the whole line looks like an equation)
            line = text.strip().replace(',', ', ')
            if '=' in line and '?' in line:
                ans = solve_equation_line(line)
                if ans is not None:
                    show = f"{line}\nAnswer: {ans:.6g}"
                    if show != last:
                        lbl_eq.config(text=line)
                        lbl_ans.config(text=f"Answer: {ans:.6g}")
                        last = show
                    time.sleep(0.15)
                    continue

            # Try sequences
            seq = grab_sequence_from_text(text)
            if seq:
                nxt = solve_sequence(seq)
                out = fmt(nxt)
                seq_str = " ".join([fmt(s) for s in seq]) + " ?"
                show = f"{seq_str}\nAnswer: {out}"
                if show != last:
                    lbl_eq.config(text=seq_str)
                    lbl_ans.config(text=f"Answer: {out}")
                    last = show
            else:
                if last != "none":
                    lbl_eq.config(text="No equation/sequence detected")
                    lbl_ans.config(text="Answer: —")
                    last = "none"
        except Exception as e:
            lbl_eq.config(text=f"Error: {e}")
            lbl_ans.config(text="Answer: —")
        time.sleep(0.15)

thr = threading.Thread(target=main_loop, daemon=True)
thr.start()

def on_close():
    global stop_flag
    stop_flag = True
    try: keyboard.unhook_all()
    except: pass
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_close)
root.mainloop()
