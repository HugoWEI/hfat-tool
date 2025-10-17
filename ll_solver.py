import os, re, time, threading, json
import tkinter as tk
import keyboard, pyautogui, pytesseract
from PIL import Image, ImageOps, ImageFilter

import os, google.generativeai as genai
genai.configure(api_key="AIzaSyA7XsGCGHV0d8tjS8zFnp3Au9bmTROW_hk")
for m in genai.list_models():
    if "generateContent" in m.supported_generation_methods:
        print(m.name)

d

# ---------- CONFIG ----------
# Tesseract path (edit if different)
pytesseract.pytesseract.tesseract_cmd = r"D:\Program Files\Tesseract-OCR\tesseract.exe"

GEMINI_MODEL = "gemini-1.5-flash"   # fast; switch to "gemini-1.5-pro" for tougher problems
TEMPERATURE = 0.0                   # deterministic for tests
MAX_PROMPT_CHARS = 800              # keep latency low

# ---------- UI ----------
region = [250, 250, 900, 260]   # (x,y,w,h) set via F8/F9
p1 = None
stop_flag = False

root = tk.Tk()
root.title("OCR → Gemini Solver")
root.attributes("-topmost", True)
root.configure(bg="black")
lbl_q = tk.Label(root, text="Calibrate with F8 (top-left) / F9 (bottom-right)", font=("Consolas", 18), fg="white", bg="black", justify="left", wraplength=900)
lbl_q.pack(padx=12, pady=(10, 6), anchor="w")
lbl_a = tk.Label(root, text="Answer: —", font=("Consolas", 26, "bold"), fg="white", bg="black", justify="left", wraplength=900)
lbl_a.pack(padx=12, pady=6, anchor="w")
lbl_reg = tk.Label(root, text="", font=("Consolas", 11), fg="gray90", bg="black")
lbl_reg.pack(padx=12, pady=(0,10), anchor="w")
def fmt_region(r): return f"Region (x,y,w,h): {r[0]}, {r[1]}, {r[2]}, {r[3]}"
lbl_reg.config(text=fmt_region(region))

def set_top_left():
    global p1
    p1 = pyautogui.position()
    lbl_q.config(text=f"Top-left set {p1}. Move to bottom-right and press F9.")

def set_bottom_right():
    global p1, region
    if p1 is None:
        lbl_q.config(text="Press F8 at the top-left first.")
        return
    x0,y0 = p1; x1,y1 = pyautogui.position()
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
    # Try both line/block; choose the longer
    txt7 = pytesseract.image_to_string(im, config="--oem 3 --psm 7")
    txt6 = pytesseract.image_to_string(im, config="--oem 3 --psm 6")
    t7, t6 = clean_text(txt7), clean_text(txt6)
    return t7 if len(t7) >= len(t6) else t6

# ---------- Local tiny fallbacks (fast) ----------
def quick_expected_first_ace(text: str):
    t = text.lower()
    if re.search(r'(expected|average|mean).*(until|before).*first.*ace', t):
        N = 52
        m = re.search(r'(\d+)\s*[- ]?card', t)
        if m: N = int(m.group(1))
        return (N+1)/(4+1)
    return None

def quick_hypergeom_exact_aces(text: str):
    # Very narrow: "remove r ... draw n ... probability ... exactly k aces"
    # (We still prefer Gemini for generality.)
    return None

# ---------- Gemini ----------
def ask_gemini(question_text: str) -> dict:
    """
    Returns a dict: {"answer": "...", "reason": "..."}.
    Uses JSON responses for easy parsing in the UI.
    """
    import google.generativeai as genai

    api_key = "AIzaSyA7XsGCGHV0d8tjS8zFnp3Au9bmTROW_hk"
    if not api_key:
        raise RuntimeError("Set GOOGLE_API_KEY environment variable.")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        GEMINI_MODEL,
        generation_config={
            "temperature": TEMPERATURE,
            "response_mime_type": "application/json",
        },
        system_instruction=(
            "You are a fast math assistant. Solve probability/combinatorics/number-sequence/"
            "card/dice/urn questions concisely. Prefer exact forms (reduced fraction or integer), "
            "otherwise a decimal with 4–6 significant digits. "
            "If multiple choice is present, output the best numeric/string that matches an option. "
            "Return JSON with keys: answer (string), reason (<=120 chars). No extra keys."
        )
    )

    prompt = (
        "Question:\n"
        f"{question_text[:MAX_PROMPT_CHARS]}\n\n"
        "Output JSON only. Examples:\n"
        '{"answer":"31/6","reason":"Expected max rolling d6 until 4"}\n'
        '{"answer":"10.6","reason":"(N+1)/(K+1) with N=52,K=4"}\n'
        '{"answer":"0.00342","reason":"marginalized removal; hypergeometric"}\n'
    )

    resp = model.generate_content(prompt)
    txt = resp.text.strip()
    # Sometimes models wrap code blocks; strip them
    if txt.startswith("```"):
        txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.S)
    try:
        data = json.loads(txt)
        if "answer" in data and "reason" in data:
            return data
    except Exception:
        pass
    # Fallback: return whole text as answer
    return {"answer": txt, "reason": "LLM free-form"}

# ---------- MAIN LOOP ----------
def main_loop():
    last = ""
    while not stop_flag:
        try:
            q = ocr_once()
            if not q:
                time.sleep(0.2); continue
            # Quickly catch a couple of common forms w/out API (super fast)
            ans = quick_expected_first_ace(q)
            if ans is not None:
                show = f"{q}\nAnswer: {ans:.6g}  (rule (N+1)/(K+1))"
                if show != last:
                    lbl_q.config(text=q)
                    lbl_a.config(text=f"Answer: {ans:.6g}  (rule (N+1)/(K+1))")
                    last = show
                time.sleep(0.15); continue

            # Call Gemini
            data = ask_gemini(q)
            show = f"{q}\nAnswer: {data.get('answer','—')}   [{data.get('reason','')}]"
            if show != last:
                lbl_q.config(text=q)
                lbl_a.config(text=f"Answer: {data.get('answer','—')}   [{data.get('reason','')}]")
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
