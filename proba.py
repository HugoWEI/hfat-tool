import re, time, threading
from math import comb
from mpmath import mp
import pyautogui, pytesseract, keyboard
from PIL import Image, ImageOps, ImageFilter
import tkinter as tk

# ==== EDIT if Tesseract lives elsewhere ====
pytesseract.pytesseract.tesseract_cmd = r"D:\Program Files\Tesseract-OCR\tesseract.exe"

# ---------- UI + calibration ----------
region = [250, 250, 900, 260]
p1 = None
stop_flag = False

root = tk.Tk()
root.title("OCR Probability Solver")
root.attributes("-topmost", True)
root.configure(bg="black")

lbl_q = tk.Label(root, text="Calibrate with F8 (top-left) / F9 (bottom-right)", font=("Consolas", 18), fg="white", bg="black", justify="left", wraplength=900)
lbl_q.pack(padx=12, pady=(10, 6), anchor="w")
lbl_a = tk.Label(root, text="Answer: —", font=("Consolas", 26, "bold"), fg="white", bg="black", justify="left")
lbl_a.pack(padx=12, pady=6, anchor="w")
lbl_reg = tk.Label(root, text="", font=("Consolas", 11), fg="gray90", bg="black")
lbl_reg.pack(padx=12, pady=(0,10), anchor="w")

def fmt_region(r): return f"Region (x,y,w,h): {r[0]}, {r[1]}, {r[2]}, {r[3]}"
lbl_reg.config(text=fmt_region(region))

def set_top_left():
    global p1
    p1 = pyautogui.position()
    lbl_q.config(text=f"Top-left set at {p1}. Move to bottom-right and press F9.")

def set_bottom_right():
    global p1, region
    if p1 is None:
        lbl_q.config(text="Press F8 at top-left first.")
        return
    p2 = pyautogui.position()
    x0,y0 = p1; x1,y1 = p2
    x,y = min(x0,x1), min(y0,y1)
    w,h = max(320, abs(x1-x0)), max(120, abs(y1-y0))
    region[:] = [x,y,w,h]
    lbl_reg.config(text=fmt_region(region))
    lbl_q.config(text="Calibrated. Watching… (F8/F9 to recalibrate)")

keyboard.add_hotkey("F8", set_top_left)
keyboard.add_hotkey("F9", set_bottom_right)

# ---------- OCR ----------
def clean_text(t: str) -> str:
    t = t.replace("\u2009"," ").replace("\u00a0"," ")
    t = t.replace("—","-").replace("–","-").replace("…"," ")
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def ocr_once():
    x,y,w,h = region
    shot = pyautogui.screenshot(region=(x,y,w,h))
    im = ImageOps.grayscale(shot)
    im = ImageOps.autocontrast(im)
    im = im.filter(ImageFilter.SHARPEN)
    # Try single-line and block modes
    txt7 = pytesseract.image_to_string(im, config="--oem 3 --psm 7")
    txt6 = pytesseract.image_to_string(im, config="--oem 3 --psm 6")
    t7, t6 = clean_text(txt7), clean_text(txt6)
    # prefer the longer (usually more complete) line
    return t7 if len(t7) >= len(t6) else t6

# ---------- Combinatorics helpers ----------
mp.dps = 50  # high precision

def C(n,k): 
    if k<0 or k>n: return mp.mpf(0)
    return mp.ncr(n,k)

def hypergeom_pmf(N,K,n,k):
    # P(X=k) with population N, successes K, draws n
    return (C(K,k)*C(N-K,n-k))/C(N,n)

# ---------- Parsers ----------
def extract_deck_size(text):
    # default 52 unless "32-card" or "32 cards"
    m = re.search(r'(\d+)\s*[- ]?card', text, flags=re.I)
    if m: 
        return int(m.group(1))
    # fallback “deck of 52 cards / 32 cards”
    m = re.search(r'deck.*?(52|32)', text, flags=re.I)
    if m: return int(m.group(1))
    return 52

def count_target_category(text):
    """
    Identify the 'success' category and how many are in a fresh deck.
    Currently handles: aces (4), hearts (13), spades/diamonds/clubs (13),
    face cards (JQK=12), red (26), black (26).
    """
    t = text.lower()
    if "ace" in t: return ("aces", 4)
    if "heart" in t: return ("hearts", 13)
    if "spade" in t: return ("spades", 13)
    if "diamond" in t: return ("diamonds", 13)
    if "club" in t: return ("clubs", 13)
    if "face card" in t or "face-card" in t or "court card" in t: return ("face cards", 12)
    if "red card" in t or "reds" in t: return ("red", 26)
    if "black card" in t or "blacks" in t: return ("black", 26)
    # default if unspecified but 'ace' not found
    return ("aces", 4)

def extract_numbers_basic(text):
    # draw n cards; exactly/at least/at most k successes
    m_draw = re.search(r'draw\s+(\d+)\s+card', text, flags=re.I)
    n = int(m_draw.group(1)) if m_draw else None

    # exactly k
    m_exact = re.search(r'(?:exactly|=)\s*(\d+)\s+(?:ace|aces|success|hearts|spades|diamonds|clubs|face)', text, flags=re.I)
    k_exact = int(m_exact.group(1)) if m_exact else None

    # at least / at most
    m_atleast = re.search(r'at\s*least\s*(\d+)\s+(?:ace|aces|success|hearts|spades|diamonds|clubs|face)', text, flags=re.I)
    m_atmost  = re.search(r'at\s*most\s*(\d+)\s+(?:ace|aces|success|hearts|spades|diamonds|clubs|face)', text, flags=re.I)
    k_atleast = int(m_atleast.group(1)) if m_atleast else None
    k_atmost  = int(m_atmost.group(1))  if m_atmost  else None

    # remove/burn r cards unseen
    m_remove = re.search(r'(remove|burn|discard|take out)\s+(\d+)\s+card', text, flags=re.I)
    r = int(m_remove.group(2)) if m_remove else 0

    return n, k_exact, k_atleast, k_atmost, r

# Replace is_expected_until_first(...) with a more robust matcher:
EXPECTED_PAT = re.compile(
    r'(expected|average|mean)\s+(number|#)?\s*of\s*cards.*?(before|until)\s+the\s*first\s+(ace|success)',
    flags=re.I
)

def is_expected_until_first(text: str) -> bool:
    t = text.lower()
    # a few common paraphrases
    if EXPECTED_PAT.search(t): return True
    if re.search(r'how many cards.*?(until|before)\s+the\s*first\s+(ace|success)', t): return True
    if re.search(r'expected draws? .* first (ace|success)', t): return True
    return False

def solve_expected_until_first(text: str) -> str:
    N = extract_deck_size(text)   # auto 52 unless it sees “32-card”, etc.
    _, K = count_target_category(text)  # “aces” → 4
    value = (N + 1) / (K + 1)
    return f"E(draws until first ace) = (N+1)/(K+1) = ({N}+1)/({K}+1) = {value:.6g}"


def solve_hypergeom(text):
    N = extract_deck_size(text)
    cat, K = count_target_category(text)
    n, k_exact, k_atleast, k_atmost, r = extract_numbers_basic(text)
    if n is None:
        return None
    # If removal r > 0 and not specified as "non-aces", assume removed uniformly at random unseen.
    # Then marginalize over how many successes were removed.
    if r > 0:
        # distribution of j successes removed ~ Hypergeom(N,K,r)
        denom = C(N, r)
        # remaining deck size:
        Nr = N - r
        def prob_exact(k):
            if k>n: return mp.mpf(0)
            tot = mp.mpf(0)
            for j in range(0, min(K, r)+1):
                # j successes removed; r-j failures removed
                if j> K or r-j > (N-K): 
                    continue
                p_rem = (C(K,j)*C(N-K, r-j))/denom
                Kr = K - j
                Fr = (N - K) - (r - j)
                if k>Kr or n-k>Fr: 
                    continue
                p_draw = (C(Kr, k)*C(Fr, n-k))/C(Nr, n)
                tot += p_rem * p_draw
            return tot
    else:
        def prob_exact(k):
            if k>n: return mp.mpf(0)
            return hypergeom_pmf(N, K, n, k)

    if k_exact is not None:
        p = prob_exact(k_exact)
        return f"P(exactly {k_exact} {cat} in {n} cards) = {p:.8g}"

    if k_atleast is not None:
        s = mp.nsum(lambda kk: prob_exact(kk), [k_atleast, n])
        return f"P(≥{k_atleast} {cat} in {n} cards) = {s:.8g}"

    if k_atmost is not None:
        s = mp.nsum(lambda kk: prob_exact(kk), [0, k_atmost])
        return f"P(≤{k_atmost} {cat} in {n} cards) = {s:.8g}"

    # Fallback: if the text literally says “probability to get k aces” without qualifier
    m_k = re.search(r'probabilit[y|é].*?\b(\d+)\b\s+(?:ace|aces)', text, flags=re.I)
    if m_k:
        k = int(m_k.group(1))
        p = prob_exact(k)
        return f"P({k} {cat} in {n}) = {p:.8g}"

    return None

def solve_text(text):
    # Try “expected number … before the first ace”
    if is_expected_until_first(text):
        return solve_expected_until_first(text)

    # Try deck draw problems (hypergeometric), including removal
    ans = solve_hypergeom(text)
    if ans:
        return ans

    return "Couldn’t match a known pattern yet."

# ---------- Main loop ----------
def main_loop():
    last = ""
    while not stop_flag:
        try:
            t = ocr_once()
            if not t: 
                time.sleep(0.2); 
                continue
            ans = solve_text(t)
            show = f"{t}\n{ans}"
            if show != last:
                lbl_q.config(text=t)
                lbl_a.config(text=ans)
                last = show
        except Exception as e:
            lbl_q.config(text=f"Error: {e}")
            lbl_a.config(text="Answer: —")
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
