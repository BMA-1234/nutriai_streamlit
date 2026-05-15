"""
WellPlate — AI nutrition coach
Runs in LOCAL MODE (SQLite, no login required) when Supabase is not configured.
Runs in CLOUD MODE (Supabase auth + cloud DB + Stripe) when credentials are set.

── Supabase SQL (run once when you're ready to go cloud) ─────────────────────
CREATE TABLE profiles (
  id UUID REFERENCES auth.users PRIMARY KEY,
  name TEXT DEFAULT 'User', age INTEGER DEFAULT 30,
  height_cm REAL DEFAULT 170, weight_kg REAL DEFAULT 70,
  calorie_goal INTEGER DEFAULT 2000, protein_goal_g INTEGER DEFAULT 120,
  carbs_goal_g INTEGER DEFAULT 250, fat_goal_g INTEGER DEFAULT 65,
  water_goal_ml INTEGER DEFAULT 2500, activity_level TEXT DEFAULT 'moderate',
  dietary_pref TEXT DEFAULT 'none', blood_group TEXT DEFAULT 'unknown',
  subscription TEXT DEFAULT 'free',
  stripe_customer_id TEXT, ai_calls_this_month INTEGER DEFAULT 0,
  ai_calls_reset_date TEXT DEFAULT to_char(CURRENT_DATE,'YYYY-MM-DD')
);
CREATE TABLE meals (
  id TEXT PRIMARY KEY, user_id UUID REFERENCES auth.users NOT NULL,
  date TEXT NOT NULL, meal_type TEXT NOT NULL DEFAULT 'snack',
  food_name TEXT NOT NULL, calories REAL DEFAULT 0,
  protein_g REAL DEFAULT 0, carbs_g REAL DEFAULT 0,
  fat_g REAL DEFAULT 0, fiber_g REAL DEFAULT 0,
  notes TEXT DEFAULT '', created_at TEXT NOT NULL
);
CREATE TABLE water_log (
  id TEXT PRIMARY KEY, user_id UUID REFERENCES auth.users NOT NULL,
  date TEXT NOT NULL, amount_ml INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE weight_log (
  id TEXT PRIMARY KEY, user_id UUID REFERENCES auth.users NOT NULL,
  date TEXT NOT NULL, weight_kg REAL NOT NULL,
  notes TEXT DEFAULT '', created_at TEXT NOT NULL
);
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE meals ENABLE ROW LEVEL SECURITY;
ALTER TABLE water_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE weight_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own profile" ON profiles   FOR ALL USING (auth.uid() = id);
CREATE POLICY "own meals"   ON meals      FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own water"   ON water_log  FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "own weight"  ON weight_log FOR ALL USING (auth.uid() = user_id);
──────────────────────────────────────────────────────────────────────────────
"""

import streamlit as st
import sqlite3, json, uuid, requests, hashlib, os
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date, timedelta
from pathlib import Path

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="WellPlate", page_icon="🥗",
                   layout="wide", initial_sidebar_state="expanded")

# ── CSS ────────────────────────────────────────────────────────────────────────
st.markdown("""<style>
:root {
  --green:#2E7D32;--green-light:#43A047;--green-bg:#E8F5E9;
  --teal:#00838F;--amber:#FF8F00;--blue:#1565C0;--red:#C62828;
  --surface:#F7FBF7;--card:#FFFFFF;--outline:#78909C;--cal-color:#FF6F00;
}
section[data-testid="stSidebar"]{background:linear-gradient(180deg,#1B5E20 0%,#2E7D32 60%,#388E3C 100%)}
section[data-testid="stSidebar"] *{color:white!important}
section[data-testid="stSidebar"] hr{border-color:rgba(255,255,255,0.25)!important}
.metric-card{background:var(--card);border-radius:16px;padding:18px 20px;
  border:1px solid #E8F5E9;box-shadow:0 2px 8px rgba(46,125,50,.07)}
.metric-label{font-size:12px;color:var(--outline);font-weight:600;letter-spacing:.8px;text-transform:uppercase}
.metric-value{font-size:32px;font-weight:800;line-height:1.1}
.metric-sub{font-size:12px;color:var(--outline);margin-top:2px}
.macro-bar-wrap{margin-bottom:12px}
.macro-bar-label{display:flex;justify-content:space-between;font-size:13px;font-weight:600;margin-bottom:4px}
.macro-bar-bg{height:10px;background:#F0F4F0;border-radius:5px;overflow:hidden}
.macro-bar-fill{height:10px;border-radius:5px}
.meal-item{display:flex;align-items:center;gap:12px;padding:10px 14px;
  background:var(--card);border:1px solid #E8F5E9;border-radius:12px;margin-bottom:8px}
.meal-icon{font-size:22px}
.meal-name{font-weight:600;font-size:14px;color:#1A2E1A}
.meal-meta{font-size:12px;color:var(--outline);margin-top:1px}
.meal-kcal{font-size:16px;font-weight:700;color:var(--cal-color);margin-left:auto;white-space:nowrap}
.food-result{padding:10px 14px;border:1px solid #E8F5E9;border-radius:10px;margin-bottom:6px}
.food-result-name{font-weight:600;font-size:14px}
.food-result-brand{font-size:11px;color:var(--outline)}
.food-result-macros{font-size:12px;color:#455A64;margin-top:3px}
.chat-user{background:var(--green-bg);border-radius:16px 16px 4px 16px;
  padding:12px 16px;margin:6px 0 6px 40px;font-size:14px;line-height:1.6}
.chat-ai{background:var(--card);border:1px solid #E8F5E9;border-radius:16px 16px 16px 4px;
  padding:12px 16px;margin:6px 40px 6px 0;font-size:14px;line-height:1.6}
.chat-meta{font-size:11px;color:var(--outline);margin-bottom:3px}
.sec-header{font-size:13px;font-weight:700;color:var(--green);letter-spacing:.8px;
  text-transform:uppercase;margin-bottom:10px;display:flex;align-items:center;gap:6px}
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:600}
.badge-cal{background:#FFF3E0;color:#E65100}
.badge-pro{background:#E3F2FD;color:#1565C0}
.badge-carb{background:#FFF8E1;color:#E65100}
.badge-fat{background:#FCE4EC;color:#C62828}
.app-header{display:flex;align-items:center;gap:12px;padding-bottom:16px}
.app-logo{background:linear-gradient(135deg,#2E7D32,#43A047);border-radius:12px;
  width:42px;height:42px;display:flex;align-items:center;justify-content:center;font-size:22px}
.streak{background:linear-gradient(135deg,#FF6F00,#FF8F00);color:white;
  border-radius:20px;padding:4px 14px;font-size:13px;font-weight:700;
  display:inline-flex;align-items:center;gap:5px}
.premium-badge{background:linear-gradient(135deg,#7B1FA2,#AB47BC);color:white;
  border-radius:20px;padding:3px 12px;font-size:11px;font-weight:700}
.local-banner{background:#E3F2FD;border:1px solid #90CAF9;border-radius:10px;
  padding:10px 16px;font-size:13px;color:#1565C0;margin-bottom:16px}
.upgrade-card{background:linear-gradient(135deg,#1B5E20,#2E7D32);color:white;
  border-radius:16px;padding:24px;text-align:center}
#MainMenu{visibility:hidden}footer{visibility:hidden}
.stDeployButton{display:none}div[data-testid="stToolbar"]{display:none}
.stButton>button{border-radius:10px!important;font-weight:600!important}
</style>""", unsafe_allow_html=True)

# ── Mode detection ─────────────────────────────────────────────────────────────
_secrets = getattr(st, "secrets", {})
USE_SUPABASE = bool(_secrets.get("SUPABASE_URL","") and _secrets.get("SUPABASE_ANON_KEY",""))

# ══════════════════════════════════════════════════════════════════════════════
# LOCAL MODE — SQLite backend
# ══════════════════════════════════════════════════════════════════════════════
DB_PATH = Path(__file__).parent / "wellplate.db"

def _conn():
    c = sqlite3.connect(DB_PATH); c.row_factory = sqlite3.Row; return c

def _init_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS profile (
          id INTEGER PRIMARY KEY DEFAULT 1,
          name TEXT DEFAULT 'User', age INTEGER DEFAULT 30,
          height_cm REAL DEFAULT 170, weight_kg REAL DEFAULT 70,
          calorie_goal INTEGER DEFAULT 2000, protein_goal_g INTEGER DEFAULT 120,
          carbs_goal_g INTEGER DEFAULT 250, fat_goal_g INTEGER DEFAULT 65,
          water_goal_ml INTEGER DEFAULT 2500, activity_level TEXT DEFAULT 'moderate',
          dietary_pref TEXT DEFAULT 'none', blood_group TEXT DEFAULT 'unknown',
          subscription TEXT DEFAULT 'free',
          ai_calls_this_month INTEGER DEFAULT 0,
          ai_calls_reset_date TEXT DEFAULT ''
        );
        INSERT OR IGNORE INTO profile (id) VALUES (1);
        CREATE TABLE IF NOT EXISTS meals (
          id TEXT PRIMARY KEY, date TEXT NOT NULL, meal_type TEXT NOT NULL DEFAULT 'snack',
          food_name TEXT NOT NULL, calories REAL DEFAULT 0,
          protein_g REAL DEFAULT 0, carbs_g REAL DEFAULT 0,
          fat_g REAL DEFAULT 0, fiber_g REAL DEFAULT 0,
          notes TEXT DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS water_log (
          id TEXT PRIMARY KEY, date TEXT NOT NULL,
          amount_ml INTEGER NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS weight_log (
          id TEXT PRIMARY KEY, date TEXT NOT NULL,
          weight_kg REAL NOT NULL, notes TEXT DEFAULT '', created_at TEXT NOT NULL
        );
        """)
    try:  # migration: add blood_group to existing DBs
        with _conn() as c:
            c.execute("ALTER TABLE profile ADD COLUMN blood_group TEXT DEFAULT 'unknown'")
    except Exception:
        pass

if not USE_SUPABASE:
    _init_db()

def _local_get_profile():
    with _conn() as c:
        r = c.execute("SELECT * FROM profile WHERE id=1").fetchone()
    return dict(r) if r else {}

def _local_save_profile(data):
    p = _local_get_profile(); p.update(data)
    with _conn() as c:
        c.execute("""UPDATE profile SET name=?,age=?,height_cm=?,weight_kg=?,
          calorie_goal=?,protein_goal_g=?,carbs_goal_g=?,fat_goal_g=?,
          water_goal_ml=?,activity_level=?,dietary_pref=?,blood_group=?,
          subscription=?,ai_calls_this_month=?,ai_calls_reset_date=? WHERE id=1""",
          (p.get("name","User"),p.get("age",30),p.get("height_cm",170),p.get("weight_kg",70),
           p.get("calorie_goal",2000),p.get("protein_goal_g",120),p.get("carbs_goal_g",250),
           p.get("fat_goal_g",65),p.get("water_goal_ml",2500),p.get("activity_level","moderate"),
           p.get("dietary_pref","none"),p.get("blood_group","unknown"),
           p.get("subscription","free"),
           p.get("ai_calls_this_month",0),p.get("ai_calls_reset_date","")))

def _local_get_meals(day):
    with _conn() as c:
        rows = c.execute("SELECT * FROM meals WHERE date=? ORDER BY created_at",(day,)).fetchall()
    return [dict(r) for r in rows]

def _local_log_meal(meal):
    with _conn() as c:
        c.execute("""INSERT INTO meals (id,date,meal_type,food_name,calories,protein_g,
          carbs_g,fat_g,fiber_g,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
          (meal["id"],meal["date"],meal["meal_type"],meal["food_name"],meal["calories"],
           meal["protein_g"],meal["carbs_g"],meal["fat_g"],meal.get("fiber_g",0),
           meal.get("notes",""),meal["created_at"]))

def _local_delete_meal(mid):
    with _conn() as c: c.execute("DELETE FROM meals WHERE id=?",(mid,))

def _local_get_water(day):
    with _conn() as c:
        r = c.execute("SELECT COALESCE(SUM(amount_ml),0) as t FROM water_log WHERE date=?",(day,)).fetchone()
    return int(r["t"])

def _local_add_water(day, ml):
    with _conn() as c:
        c.execute("INSERT INTO water_log (id,date,amount_ml,created_at) VALUES (?,?,?,?)",
                  (str(uuid.uuid4()),day,ml,datetime.now().isoformat()))

def _local_meals_range(days):
    start = (date.today()-timedelta(days=days)).isoformat()
    with _conn() as c:
        rows = c.execute("SELECT * FROM meals WHERE date>=? ORDER BY date,created_at",(start,)).fetchall()
    return [dict(r) for r in rows]

def _local_weight_range(days):
    start = (date.today()-timedelta(days=days)).isoformat()
    with _conn() as c:
        rows = c.execute("SELECT * FROM weight_log WHERE date>=? ORDER BY date",(start,)).fetchall()
    return [dict(r) for r in rows]

def _local_save_weight(day, kg):
    with _conn() as c:
        c.execute("INSERT INTO weight_log (id,date,weight_kg,notes,created_at) VALUES (?,?,?,?,?)",
                  (str(uuid.uuid4()),day,kg,"",datetime.now().isoformat()))

# ══════════════════════════════════════════════════════════════════════════════
# CLOUD MODE — Supabase backend
# ══════════════════════════════════════════════════════════════════════════════
def get_sb():
    if not USE_SUPABASE: return None
    try:
        from supabase import create_client
        return create_client(_secrets.get("SUPABASE_URL",""), _secrets.get("SUPABASE_ANON_KEY",""))
    except: return None

def _hash_pw(password, salt=None):
    if salt is None: salt = os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return f"{salt}${h.hex()}"

def _verify_pw(password, stored):
    try:
        salt, _ = stored.split("$", 1)
        return _hash_pw(password, salt) == stored
    except: return False

def sign_up(email, password, name):
    sb = get_sb()
    if not sb: return False, "Supabase not configured."
    try:
        existing = sb.table("profiles").select("id").eq("email", email).execute()
        if existing.data: return False, "Email already registered. Please sign in."
        user_id = str(uuid.uuid4())
        sb.table("profiles").insert({
            "id": user_id, "email": email,
            "password_hash": _hash_pw(password), "name": name or "User"
        }).execute()
        st.session_state.access_token = user_id
        st.session_state.user_id = user_id
        st.session_state.user_email = email
        return True, ""
    except Exception as e: return False, str(e)

def sign_in(email, password):
    sb = get_sb()
    if not sb: return False, "Supabase not configured."
    try:
        res = sb.table("profiles").select("id,password_hash").eq("email", email).execute()
        if not res.data: return False, "Email not found. Please create an account."
        user = res.data[0]
        if not _verify_pw(password, user["password_hash"]):
            return False, "Wrong password."
        st.session_state.access_token = user["id"]
        st.session_state.user_id = user["id"]
        st.session_state.user_email = email
        return True, ""
    except Exception as e: return False, str(e)

def sign_out():
    st.session_state.update({"access_token":None,"refresh_token":None,
        "user_id":None,"user_email":None,"chat_history":[],"onboarded":False})
    st.session_state.page = "auth" if USE_SUPABASE else "dashboard"

def _uid(): return st.session_state.get("user_id","")

def _dp():
    return {"name":"User","age":30,"height_cm":170,"weight_kg":70,"calorie_goal":2000,
            "protein_goal_g":120,"carbs_goal_g":250,"fat_goal_g":65,"water_goal_ml":2500,
            "activity_level":"moderate","dietary_pref":"none","blood_group":"unknown",
            "subscription":"free","ai_calls_this_month":0,
            "ai_calls_reset_date":date.today().isoformat()}

# ── Unified DB interface ───────────────────────────────────────────────────────
def _use_local():
    uid = _uid()
    return not USE_SUPABASE or uid == "local" or not uid

def get_profile():
    if _use_local(): return _local_get_profile() or _dp()
    sb = get_sb()
    if not sb or not _uid(): return _dp()
    try:
        res = sb.table("profiles").select("*").eq("id",_uid()).execute()
        return res.data[0] if res.data else _dp()
    except: return _dp()

def save_profile(data):
    if _use_local(): _local_save_profile(data); return
    sb = get_sb()
    if sb and _uid():
        safe = {k:v for k,v in data.items() if k not in ("id","email","password_hash")}
        try: sb.table("profiles").update(safe).eq("id", _uid()).execute()
        except: pass

def get_meals(day):
    if _use_local(): return _local_get_meals(day)
    sb = get_sb()
    if not sb or not _uid(): return []
    try:
        r = sb.table("meals").select("*").eq("user_id",_uid()).eq("date",day).order("created_at").execute()
        return r.data or []
    except: return []

def log_meal(meal):
    if _use_local(): _local_log_meal(meal); return
    sb = get_sb()
    if sb and _uid():
        try: sb.table("meals").insert({**meal,"user_id":_uid()}).execute()
        except: pass

def delete_meal(mid):
    if _use_local(): _local_delete_meal(mid); return
    sb = get_sb()
    if sb and _uid():
        try: sb.table("meals").delete().eq("id",mid).eq("user_id",_uid()).execute()
        except: pass

def get_water_today(day):
    if _use_local(): return _local_get_water(day)
    sb = get_sb()
    if not sb or not _uid(): return 0
    try:
        r = sb.table("water_log").select("amount_ml").eq("user_id",_uid()).eq("date",day).execute()
        return sum(x.get("amount_ml",0) for x in (r.data or []))
    except: return 0

def add_water(day, ml):
    if _use_local(): _local_add_water(day, ml); return
    sb = get_sb()
    if sb and _uid():
        try:
            sb.table("water_log").insert({"id":str(uuid.uuid4()),"user_id":_uid(),
                "date":day,"amount_ml":ml,"created_at":datetime.now().isoformat()}).execute()
        except: pass

def get_meals_range(days):
    if _use_local(): return _local_meals_range(days)
    sb = get_sb()
    if not sb or not _uid(): return []
    start = (date.today()-timedelta(days=days)).isoformat()
    try:
        r = sb.table("meals").select("*").eq("user_id",_uid()).gte("date",start).order("date").execute()
        return r.data or []
    except: return []

def get_weight_range(days):
    if _use_local(): return _local_weight_range(days)
    sb = get_sb()
    if not sb or not _uid(): return []
    start = (date.today()-timedelta(days=days)).isoformat()
    try:
        r = sb.table("weight_log").select("*").eq("user_id",_uid()).gte("date",start).order("date").execute()
        return r.data or []
    except: return []

def get_streak():
    meals = get_meals_range(90)
    if not meals: return 0
    dates = sorted(set(m["date"] for m in meals), reverse=True)
    streak, check = 0, date.today()
    for ds in dates:
        d = date.fromisoformat(ds)
        if d == check or d == check - timedelta(days=1):
            streak += 1; check = d - timedelta(days=1)
        else: break
    return streak

def get_achievements():
    meals = get_meals_range(365); streak = get_streak()
    badges = []
    if len(meals) >= 1:  badges.append({"icon":"🌱","label":"First Meal","color":"#E8F5E9","border":"#A5D6A7"})
    if len(meals) >= 10: badges.append({"icon":"🍽️","label":"10 Meals","color":"#E3F2FD","border":"#90CAF9"})
    if len(meals) >= 50: badges.append({"icon":"🏆","label":"50 Meals","color":"#FFF8E1","border":"#FFE082"})
    if streak >= 3:  badges.append({"icon":"🔥","label":f"{streak}-Day Streak","color":"#FFF3E0","border":"#FFCC80"})
    if streak >= 7:  badges.append({"icon":"⚡","label":"Week Warrior","color":"#FFF9C4","border":"#FFF176"})
    if streak >= 30: badges.append({"icon":"💎","label":"Monthly Master","color":"#F3E5F5","border":"#CE93D8"})
    return badges

# ── Subscription / AI usage ────────────────────────────────────────────────────
FREE_AI_LIMIT = 30

def check_ai_usage():
    p = get_profile()
    if p.get("subscription") == "premium": return True, ""
    reset = p.get("ai_calls_reset_date","")
    this_month = date.today().strftime("%Y-%m")
    if not reset or reset[:7] != this_month:
        save_profile({"ai_calls_this_month":0,"ai_calls_reset_date":date.today().isoformat()})
        p["ai_calls_this_month"] = 0
    calls = p.get("ai_calls_this_month",0)
    if calls >= FREE_AI_LIMIT:
        return False, f"Free limit reached ({FREE_AI_LIMIT} AI calls/month). Upgrade to Premium for unlimited."
    save_profile({"ai_calls_this_month": calls+1})
    return True, ""

def _get_secret(key, default=""):
    try: return st.secrets.get(key, default)
    except: return default

def create_checkout_url(email):
    try:
        import stripe
        stripe.api_key = _get_secret("STRIPE_SECRET_KEY")
        if not stripe.api_key: return None
        app_url = _get_secret("APP_URL","https://wellplate.streamlit.app")
        s = stripe.checkout.Session.create(
            customer_email=email, payment_method_types=["card"],
            line_items=[{"price":_get_secret("STRIPE_PRICE_ID"),"quantity":1}],
            mode="subscription",
            success_url=f"{app_url}?stripe_success=1&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{app_url}?stripe_cancel=1")
        return s.url
    except: return None

def verify_stripe_session(session_id):
    try:
        import stripe
        stripe.api_key = _get_secret("STRIPE_SECRET_KEY")
        if not stripe.api_key: return False
        s = stripe.checkout.Session.retrieve(session_id)
        if s.payment_status == "paid":
            save_profile({"subscription":"premium","stripe_customer_id":s.customer})
            return True
    except: pass
    return False

# ── AI ─────────────────────────────────────────────────────────────────────────
OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL = "nvidia/nemotron-3-super-120b-a12b:free"

def call_ai(messages, max_tokens=800):
    key = st.session_state.get("api_key","")
    if not key: raise ValueError("No API key — go to ⚙️ Settings.")
    resp = requests.post(OPENROUTER_URL, timeout=60, headers={
        "Authorization":f"Bearer {key}","Content-Type":"application/json",
        "HTTP-Referer":"https://wellplate.app"},
        json={"model":OPENROUTER_MODEL,"max_tokens":max_tokens,"messages":messages})
    if resp.status_code != 200:
        try: msg = resp.json().get("error",{}).get("message",resp.text)
        except: msg = resp.text
        raise RuntimeError(f"API error {resp.status_code}: {msg}")
    return resp.json()["choices"][0]["message"]["content"]

def ai_analyze_meal(description):
    ok, msg = check_ai_usage()
    if not ok: raise RuntimeError(msg)
    text = call_ai([{"role":"user","content":
        f'Analyze this meal. Return ONLY JSON:\n{{"food_name":"...","serving_description":"...","calories":0,"protein_g":0,"carbs_g":0,"fat_g":0,"fiber_g":0}}\nMeal: {description}'}],
        max_tokens=300)
    return json.loads(text.strip().replace("```json","").replace("```","").strip())

def ai_chat(user_msg, history, p, today_meals):
    ok, msg = check_ai_usage()
    if not ok: raise RuntimeError(msg)
    meals_txt = "\n".join(f"  - {m['meal_type'].title()}: {m['food_name']} ({int(m['calories'])} kcal)"
                          for m in today_meals) or "  No meals logged yet."
    total_cal = sum(m["calories"] for m in today_meals)
    system = f"""You are WellPlate, a friendly expert nutrition coach.
Today: {date.today().strftime('%A, %B %d %Y')}
User: {p.get('name','User')}, goal {p.get('calorie_goal',2000)} kcal/day
Consumed: {int(total_cal)} kcal ({int(p.get('calorie_goal',2000)-total_cal)} remaining)
Today's meals:\n{meals_txt}
Give practical, warm, concise advice. Bullet points. Under 200 words."""
    messages = [{"role":"system","content":system}]
    for h in history[-6:]:
        messages += [{"role":"user","content":h["user"]},{"role":"assistant","content":h["ai"]}]
    messages.append({"role":"user","content":user_msg})
    return call_ai(messages, max_tokens=400)

def search_food(query):
    try:
        resp = requests.get("https://world.openfoodfacts.org/cgi/search.pl",
            params={"search_terms":query,"json":1,"page_size":8,
                    "fields":"product_name,nutriments,serving_size,brands"}, timeout=8)
        results = []
        for p in resp.json().get("products",[]):
            n = p.get("nutriments",{}); name = p.get("product_name","").strip()
            if not name: continue
            kcal = n.get("energy-kcal_100g") or n.get("energy-kcal",0)
            results.append({"name":name,"brand":p.get("brands","").split(",")[0].strip(),
                "serving":p.get("serving_size","100g"),
                "calories_100g":round(float(kcal or 0),1),
                "protein_100g":round(float(n.get("proteins_100g",0) or 0),1),
                "carbs_100g":round(float(n.get("carbohydrates_100g",0) or 0),1),
                "fat_100g":round(float(n.get("fat_100g",0) or 0),1),
                "fiber_100g":round(float(n.get("fiber_100g",0) or 0),1)})
        return results
    except: return []

# ── UI helpers ─────────────────────────────────────────────────────────────────
MEAL_ICONS = {"breakfast":"🌅","lunch":"☀️","dinner":"🌙","snack":"🍎"}

BLOOD_TYPE_DIET = {
    "A": {
        "label": "Type A — The Agrarian", "emoji": "🌿",
        "desc": "Thrives on a plant-rich diet. Sensitive digestive system, benefits from organic, fresh foods.",
        "beneficial": ["Tofu","Tempeh","Seafood","Sardines","Salmon","Legumes","Lentils","Beans",
                       "Grains (oats, rye)","Vegetables","Garlic","Ginger","Green tea","Berries","Plums"],
        "avoid": ["Red meat","Pork","Dairy (milk, ice cream)","Kidney beans","Lima beans",
                  "Wheat (excess)","Corn","Potatoes","Peppers","Vinegar"],
    },
    "B": {
        "label": "Type B — The Nomad", "emoji": "🥛",
        "desc": "Balanced omnivore. Tolerates dairy well and benefits from a varied diet.",
        "beneficial": ["Lamb","Mutton","Venison","Rabbit","Dairy (yogurt, cheese)","Eggs",
                       "Oats","Millet","Rice","Green vegetables","Pineapple","Ginger"],
        "avoid": ["Chicken","Pork","Corn","Lentils","Peanuts","Sesame seeds",
                  "Wheat","Buckwheat","Tomatoes","Coconut"],
    },
    "AB": {
        "label": "Type AB — The Enigma", "emoji": "⚗️",
        "desc": "Combines A and B traits. Adapts to many foods but has a sensitive digestive system.",
        "beneficial": ["Tofu","Tempeh","Seafood (tuna, salmon, sardines)","Dairy (yogurt, kefir)",
                       "Green vegetables","Garlic","Ginger","Grapes","Cherries","Pineapple","Kelp"],
        "avoid": ["Red meat","Chicken","Corn","Kidney beans","Buckwheat",
                  "Peppers","Bananas","Mushrooms","Vinegar","Alcohol"],
    },
    "O": {
        "label": "Type O — The Hunter", "emoji": "🥩",
        "desc": "High-protein diet. Benefits from lean meats, fish, and vegetables.",
        "beneficial": ["Lean beef","Lamb","Fish","Cod","Herring","Mackerel","Kelp","Broccoli",
                       "Spinach","Sweet potatoes","Plums","Figs","Walnuts","Olive oil"],
        "avoid": ["Wheat","Corn","Oats","Dairy (milk, cheese)","Lentils","Kidney beans",
                  "Peanuts","Cabbage","Cauliflower","Avocado (excess)","Coffee"],
    },
}
TODAY = date.today().isoformat()

def totals(meals):
    return {"calories":sum(m["calories"] for m in meals),
            "protein":sum(m["protein_g"] for m in meals),
            "carbs":sum(m["carbs_g"] for m in meals),
            "fat":sum(m["fat_g"] for m in meals),
            "fiber":sum(m["fiber_g"] for m in meals)}

def pct(val, goal):
    return min(100, round(val/goal*100,1)) if goal > 0 else 0

def macro_bar(label, val, goal, color, unit="g"):
    p = pct(val,goal); over = val>goal; bc = "#EF5350" if over else color
    st.markdown(f"""<div class="macro-bar-wrap">
      <div class="macro-bar-label">
        <span style="color:{color}">{label}</span>
        <span style="color:{'#EF5350' if over else '#455A64'}">{val:.0f}{unit}/{goal:.0f}{unit}</span>
      </div>
      <div class="macro-bar-bg"><div class="macro-bar-fill" style="width:{p}%;background:{bc}"></div></div>
    </div>""", unsafe_allow_html=True)

def calorie_donut(consumed, goal):
    over = consumed > goal
    fig = go.Figure(go.Pie(
        labels=["Consumed","Remaining"] if not over else ["Consumed","Over"],
        values=[consumed,abs(goal-consumed)], hole=0.72,
        marker_colors=["#FF6F00","#E8F5E9"] if not over else ["#EF5350","#FFCDD2"],
        textinfo="none", hoverinfo="skip", sort=False))
    fig.update_layout(margin=dict(t=0,b=0,l=0,r=0), height=180, showlegend=False,
        annotations=[dict(text=f"<b>{int(consumed)}</b><br><span style='font-size:10px'>kcal</span>",
                          x=0.5,y=0.5,font_size=18,showarrow=False)],
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    return fig

# ── Session state ──────────────────────────────────────────────────────────────
_secret_key = _secrets.get("OPENROUTER_API_KEY","")
_default_page = "dashboard" if not USE_SUPABASE else "auth"

DEFAULTS = {"page":_default_page,"api_key":_secret_key,"access_token":None,
            "refresh_token":None,"user_id":None,"user_email":None,
            "chat_history":[],"food_results":[],"selected_food":None,
            "log_date":TODAY,"onboarded":False,"quick_log_type":None}
for k,v in DEFAULTS.items():
    if k not in st.session_state: st.session_state[k] = v

# ── Handle Stripe return ───────────────────────────────────────────────────────
_qp = st.query_params
if _qp.get("stripe_success") and _qp.get("session_id"):
    if verify_stripe_session(_qp["session_id"]):
        st.success("🎉 Welcome to Premium! Unlimited AI analyses unlocked.")
    st.query_params.clear()

# ── Auth gate (cloud mode only) ────────────────────────────────────────────────
if USE_SUPABASE and not (st.session_state.get("access_token") and st.session_state.get("user_id")):
    st.session_state.page = "auth"

# ══════════════════════════════════════════════════════════════════════════════
# AUTH PAGE (cloud mode only)
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.page == "auth":
    _, col, _ = st.columns([1,1.2,1])
    with col:
        st.markdown("""<div style='text-align:center;padding:40px 0 24px'>
          <div style='font-size:52px'>🥗</div>
          <div style='font-size:28px;font-weight:800;color:#1B5E20;margin-top:8px'>WellPlate</div>
          <div style='font-size:14px;color:#78909C;margin-top:4px'>Your AI Nutrition Coach</div>
        </div>""", unsafe_allow_html=True)
        tab_in,tab_up = st.tabs(["Sign In","Create Account"])
        with tab_in:
            with st.form("login"):
                em = st.text_input("Email",placeholder="you@example.com")
                pw = st.text_input("Password",type="password")
                if st.form_submit_button("Sign In",type="primary",use_container_width=True):
                    if em and pw:
                        ok,msg = sign_in(em.strip(),pw)
                        if ok: st.session_state.page="dashboard"; st.rerun()
                        else: st.error(msg)
                    else: st.warning("Enter email and password.")
        with tab_up:
            with st.form("signup"):
                sn=st.text_input("Name",placeholder="Alex")
                se=st.text_input("Email",placeholder="you@example.com")
                sp=st.text_input("Password (min 6 chars)",type="password")
                sp2=st.text_input("Confirm password",type="password")
                if st.form_submit_button("Create Account",type="primary",use_container_width=True):
                    if not all([sn,se,sp]): st.warning("Fill in all fields.")
                    elif sp != sp2: st.error("Passwords don't match.")
                    elif len(sp)<6: st.error("Password must be at least 6 chars.")
                    else:
                        ok,msg = sign_up(se.strip(),sp,sn.strip())
                        if ok:
                            if msg: st.info(msg)
                            else: st.session_state.page="onboarding"; st.rerun()
                        else: st.error(msg)
        st.divider()
        st.markdown("<div style='text-align:center;font-size:13px;color:#78909C;margin-bottom:10px'>or</div>", unsafe_allow_html=True)
        if st.button("💻 Continue as Guest (local mode)", use_container_width=True):
            st.session_state.update({
                "access_token": "local", "refresh_token": "local",
                "user_id": "local", "user_email": "guest",
            })
            st.session_state.page = "dashboard"
            st.rerun()
        st.markdown("<div style='text-align:center;margin-top:16px;font-size:12px;color:#90A4AE'>"
                    "Free forever · AI-powered · No credit card required</div>", unsafe_allow_html=True)
    st.stop()

# ── Past this point: user is in (local or cloud) ───────────────────────────────
profile = get_profile()

# ── Local mode banner ──────────────────────────────────────────────────────────
if not USE_SUPABASE:
    st.markdown("""<div class="local-banner">
      💻 <b>Local Mode</b> — data saved on this machine only.
      To enable accounts & cloud sync, add <code>SUPABASE_URL</code> and <code>SUPABASE_ANON_KEY</code> to your secrets.
    </div>""", unsafe_allow_html=True)

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    p_sub = profile.get("subscription","free")
    ai_used = profile.get("ai_calls_this_month",0)
    st.markdown(f"""
    <div style='padding:16px 0 4px 0;display:flex;align-items:center;gap:10px'>
      <div style='background:rgba(255,255,255,0.15);border-radius:10px;padding:6px 8px;font-size:20px'>🥗</div>
      <div>
        <div style='font-size:20px;font-weight:800;letter-spacing:-0.3px'>WellPlate</div>
        <div style='font-size:10px;opacity:.7;letter-spacing:1px;text-transform:uppercase'>AI Nutrition Coach</div>
      </div>
      {'<span class="premium-badge" style="margin-inline-start:auto">⭐ Premium</span>' if p_sub=="premium" else ""}
    </div>
    <div style='margin:10px 0 12px;padding:10px 12px;background:rgba(255,255,255,0.1);border-radius:10px;font-size:13px'>
      Welcome back, <b>{profile.get('name','there')}</b> 👋
    </div>
    <hr/>""", unsafe_allow_html=True)
    nav = st.radio("Nav",["🏠  Dashboard","🍽️  Log Meal","🤖  AI Chat",
        "📊  Progress","👤  Profile & Goals","⚙️  Settings"],label_visibility="collapsed")
    page_map={"🏠  Dashboard":"dashboard","🍽️  Log Meal":"log","🤖  AI Chat":"chat",
              "📊  Progress":"progress","👤  Profile & Goals":"profile","⚙️  Settings":"settings"}
    st.session_state.page = page_map[nav]
    streak=get_streak(); today_meals=get_meals(TODAY)
    t=totals(today_meals); water=get_water_today(TODAY)
    st.markdown(f"""<hr/><div style='font-size:12px;opacity:.85;line-height:2'>
      🔥 <b>{streak}</b> day streak<br/>🍽️ <b>{len(today_meals)}</b> meals<br/>
      ⚡ <b>{int(t['calories'])}</b>/{profile.get('calorie_goal',2000)} kcal<br/>
      💧 <b>{water}</b>/{profile.get('water_goal_ml',2500)} ml
    </div>""", unsafe_allow_html=True)
    if p_sub == "free":
        st.markdown(f"<hr/><div style='font-size:11px;opacity:.85'>🤖 <b>{max(0,FREE_AI_LIMIT-ai_used)}</b> free AI calls left</div>",unsafe_allow_html=True)
    if USE_SUPABASE:
        st.markdown("<hr/>",unsafe_allow_html=True)
        if st.button("🚪 Sign Out",use_container_width=True): sign_out(); st.rerun()

# ── First-time user → onboarding ───────────────────────────────────────────────
if not st.session_state.onboarded and st.session_state.page not in ("auth","onboarding"):
    if profile.get("name","User") == "User" and len(get_meals_range(365)) == 0:
        st.session_state.page = "onboarding"

# ══════════════════════════════════════════════════════════════════════════════
# ONBOARDING
# ══════════════════════════════════════════════════════════════════════════════
if st.session_state.page == "onboarding":
    st.markdown("""<div style='text-align:center;padding:30px 0 10px'>
      <div style='font-size:56px'>🥗</div>
      <div style='font-size:32px;font-weight:800;color:#1B5E20;margin-top:8px'>Welcome to WellPlate</div>
      <div style='font-size:16px;color:#555;margin-top:6px'>Set up your profile in 30 seconds.</div>
    </div>""", unsafe_allow_html=True)
    st.markdown("<br/>",unsafe_allow_html=True)
    with st.form("onboarding"):
        c1,c2 = st.columns(2)
        with c1:
            ob_name=st.text_input("Your name",placeholder="e.g. Alex")
            ob_height=st.number_input("Height (cm)",value=170,min_value=100,max_value=250)
            ob_goal=st.selectbox("Your goal",["Lose weight","Maintain weight","Gain muscle","Eat healthier"])
        with c2:
            ob_age=st.number_input("Age",value=25,min_value=10,max_value=100)
            ob_weight=st.number_input("Weight (kg)",value=70.0,min_value=20.0,max_value=300.0,step=0.5)
            ob_act=st.selectbox("Activity",["sedentary","light","moderate","active","very_active"],index=2,
                format_func=lambda x:{"sedentary":"🪑 Sedentary","light":"🚶 Light",
                    "moderate":"🏃 Moderate","active":"💪 Active","very_active":"⚡ Very active"}[x])
        cal_map={"Lose weight":1700,"Maintain weight":2000,"Gain muscle":2400,"Eat healthier":2000}
        pro_map={"Lose weight":130,"Maintain weight":120,"Gain muscle":160,"Eat healthier":120}
        if st.form_submit_button("🚀 Get Started",type="primary",use_container_width=True):
            save_profile({"name":ob_name.strip() or "User","age":ob_age,"height_cm":ob_height,
                "weight_kg":ob_weight,"activity_level":ob_act,
                "calorie_goal":cal_map[ob_goal],"protein_goal_g":pro_map[ob_goal]})
            st.session_state.onboarded=True; st.session_state.page="dashboard"; st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "dashboard":
    today_meals=get_meals(TODAY); t=totals(today_meals)
    water=get_water_today(TODAY); p=profile
    cal_goal=p.get("calorie_goal",2000); streak=get_streak()

    st.markdown(f"""<div class="app-header">
      <div class="app-logo">🥗</div>
      <div><div style='font-size:22px;font-weight:800;color:#1B5E20'>WellPlate</div>
        <div style='font-size:12px;color:#78909C'>{date.today().strftime('%A, %B %d %Y')}</div></div>
      <div style='margin-left:auto'><span class="streak">🔥 {streak} day streak</span></div>
    </div>""", unsafe_allow_html=True)

    badges = get_achievements()
    if badges:
        bhtml="".join(f"<span style='display:inline-flex;align-items:center;gap:5px;"
            f"background:{b['color']};border:1px solid {b['border']};border-radius:20px;"
            f"padding:5px 14px;font-size:12px;font-weight:700;margin-right:8px'>{b['icon']} {b['label']}</span>"
            for b in badges)
        st.markdown(f"<div style='margin-bottom:14px'>{bhtml}</div>",unsafe_allow_html=True)

    st.markdown('<div class="sec-header">⚡ Quick Log</div>',unsafe_allow_html=True)
    ql_cols=st.columns(5)
    for col,(lbl,mtype) in zip(ql_cols,[("🌅 Breakfast","breakfast"),("☀️ Lunch","lunch"),
            ("🌙 Dinner","dinner"),("🍎 Snack","snack"),("🤖 AI Analyse","ai")]):
        with col:
            if st.button(lbl,use_container_width=True,key=f"ql_{mtype}"):
                st.session_state.page="log"; st.session_state.quick_log_type=mtype; st.rerun()
    st.markdown("<br/>",unsafe_allow_html=True)

    col_ring,col_macros,col_water = st.columns([1.4,2,1.4])
    with col_ring:
        st.markdown('<div class="sec-header">⚡ Calories</div>',unsafe_allow_html=True)
        st.plotly_chart(calorie_donut(t["calories"],cal_goal),use_container_width=True,config={"displayModeBar":False})
        rem=cal_goal-t["calories"]; color="#EF5350" if rem<0 else "#2E7D32"
        st.markdown(f"<div style='text-align:center;font-size:13px;color:{color};font-weight:600'>"
                    f"{int(abs(rem))} kcal {'over' if rem<0 else 'remaining'}</div>",unsafe_allow_html=True)
    with col_macros:
        st.markdown('<div class="sec-header">💪 Macros</div>',unsafe_allow_html=True)
        macro_bar("Protein",t["protein"],p.get("protein_goal_g",120),"#1565C0")
        macro_bar("Carbs",t["carbs"],p.get("carbs_goal_g",250),"#FF8F00")
        macro_bar("Fat",t["fat"],p.get("fat_goal_g",65),"#C62828")
        macro_bar("Fiber",t["fiber"],25,"#2E7D32")
    with col_water:
        st.markdown('<div class="sec-header">💧 Water</div>',unsafe_allow_html=True)
        wg=p.get("water_goal_ml",2500); glasses=water//250
        st.markdown(f"""<div style='text-align:center;padding:8px 0'>
          <div style='font-size:36px;font-weight:800;color:#00838F'>{water}</div>
          <div style='font-size:12px;color:#78909C'>of {wg} ml</div>
          <div style='margin:8px 0;font-size:20px'>{'💧'*min(glasses,8)}</div>
        </div>""",unsafe_allow_html=True)
        wfig=go.Figure(go.Bar(x=["Water"],y=[water],marker_color="#00ACC1",
                              text=[f"{int(pct(water,wg))}%"],textposition="outside"))
        wfig.add_hline(y=wg,line_dash="dash",line_color="#B2EBF2")
        wfig.update_layout(height=100,margin=dict(t=20,b=0,l=0,r=0),
            yaxis=dict(range=[0,max(wg*1.2,100)],visible=False),xaxis_visible=False,
            paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",showlegend=False)
        st.plotly_chart(wfig,use_container_width=True,config={"displayModeBar":False})
        wc1,wc2,wc3=st.columns(3)
        with wc1:
            if st.button("+250ml",use_container_width=True): add_water(TODAY,250); st.rerun()
        with wc2:
            if st.button("+500ml",use_container_width=True): add_water(TODAY,500); st.rerun()
        with wc3:
            if st.button("+1L",use_container_width=True): add_water(TODAY,1000); st.rerun()

    st.divider()
    col_meals,col_summary=st.columns([3,1])
    with col_meals:
        st.markdown('<div class="sec-header">🍽️ Today\'s Meals</div>',unsafe_allow_html=True)
        if not today_meals:
            st.markdown("""<div style='text-align:center;padding:30px 20px;color:#78909C;
                background:#F7FBF7;border-radius:12px;border:1px dashed #C8E6C9'>
              <div style='font-size:40px'>🥗</div>
              <div style='font-weight:700;font-size:16px;color:#2E7D32;margin-top:10px'>Start tracking your nutrition</div>
              <div style='font-size:13px;margin-top:5px'>Log your first meal to see your daily breakdown</div>
            </div>""",unsafe_allow_html=True)
            st.markdown("<div style='height:10px'></div>",unsafe_allow_html=True)
            if st.button("🍽️ Log My First Meal",type="primary",use_container_width=True):
                st.session_state.page="log"; st.rerun()
        else:
            for m in today_meals:
                icon=MEAL_ICONS.get(m["meal_type"],"🍽️")
                dc1,dc2=st.columns([10,1])
                with dc1:
                    st.markdown(f"""<div class="meal-item">
                      <span class="meal-icon">{icon}</span>
                      <div><div class="meal-name">{m['food_name']}</div>
                        <div class="meal-meta">{m['meal_type'].title()} · P:{m['protein_g']:.0f}g C:{m['carbs_g']:.0f}g F:{m['fat_g']:.0f}g</div>
                      </div>
                      <div class="meal-kcal">{int(m['calories'])} kcal</div>
                    </div>""",unsafe_allow_html=True)
                with dc2:
                    if st.button("✕",key=f"del_{m['id']}"): delete_meal(m["id"]); st.rerun()
    with col_summary:
        st.markdown('<div class="sec-header">📊 Today</div>',unsafe_allow_html=True)
        by_type={}
        for m in today_meals: by_type[m["meal_type"]]=by_type.get(m["meal_type"],0)+m["calories"]
        if by_type:
            fig=px.pie(values=list(by_type.values()),names=[k.title() for k in by_type],
                color_discrete_sequence=["#FF6F00","#43A047","#1565C0","#FF8F00"],hole=0.5)
            fig.update_layout(height=200,margin=dict(t=0,b=0,l=0,r=0),showlegend=True,
                legend=dict(font_size=11),paper_bgcolor="rgba(0,0,0,0)")
            fig.update_traces(textinfo="percent",textfont_size=10)
            st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})
        st.markdown(f"""<div style='margin-top:8px;line-height:2.2'>
          <span class="badge badge-cal">⚡ {int(t['calories'])} kcal</span><br/>
          <span class="badge badge-pro">🥩 {int(t['protein'])}g protein</span><br/>
          <span class="badge badge-carb">🌾 {int(t['carbs'])}g carbs</span><br/>
          <span class="badge badge-fat">🥑 {int(t['fat'])}g fat</span>
        </div>""",unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════════════════
# LOG MEAL
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "log":
    st.markdown("## 🍽️ Log a Meal")
    log_date=st.date_input("Date",value=date.fromisoformat(st.session_state.log_date))
    st.session_state.log_date=log_date.isoformat()
    _ql=st.session_state.get("quick_log_type")
    _types=["breakfast","lunch","dinner","snack"]
    _di=_types.index(_ql) if _ql in _types else 0
    meal_type=st.selectbox("Meal type",_types,index=_di,
        format_func=lambda x:f"{MEAL_ICONS[x]} {x.title()}")
    st.session_state.quick_log_type=None
    tab_search,tab_ai,tab_manual=st.tabs(["🔍  Search Food","🤖  AI Analysis","✏️  Manual Entry"])

    def add_meal_form(food_name="",cal=0,pro=0,carb=0,fat=0,fib=0,kp=""):
        with st.form(f"add_{kp}"):
            fc1,fc2=st.columns([3,1])
            with fc1: name=st.text_input("Food name",value=food_name)
            with fc2: grams=st.number_input("Grams",value=100,min_value=1,step=10)
            nc1,nc2,nc3,nc4=st.columns(4); f=grams/100
            with nc1: calories=st.number_input("Calories",value=round(cal*f,1),min_value=0.0)
            with nc2: protein=st.number_input("Protein g",value=round(pro*f,1),min_value=0.0)
            with nc3: carbs=st.number_input("Carbs g",value=round(carb*f,1),min_value=0.0)
            with nc4: fat_v=st.number_input("Fat g",value=round(fat*f,1),min_value=0.0)
            fiber=st.number_input("Fiber g",value=round(fib*f,1),min_value=0.0)
            if st.form_submit_button("✅ Add to Log",type="primary",use_container_width=True):
                if not name.strip(): st.warning("Enter a food name.")
                else:
                    log_meal({"id":str(uuid.uuid4()),"date":st.session_state.log_date,
                        "meal_type":meal_type,"food_name":name,"calories":calories,
                        "protein_g":protein,"carbs_g":carbs,"fat_g":fat_v,"fiber_g":fiber,
                        "notes":"","created_at":datetime.now().isoformat()})
                    st.success(f"✅ Logged: **{name}** — {int(calories)} kcal"); st.rerun()

    with tab_search:
        sq1,sq2=st.columns([5,1])
        with sq1: search_q=st.text_input("",placeholder="Search food…",label_visibility="collapsed")
        with sq2: do_search=st.button("Search",type="primary",use_container_width=True)
        if do_search and search_q:
            with st.spinner("Searching…"):
                st.session_state.food_results=search_food(search_q)
                st.session_state.selected_food=None
        if st.session_state.food_results:
            st.markdown(f"<div style='font-size:12px;color:#78909C;margin-bottom:8px'>{len(st.session_state.food_results)} results</div>",unsafe_allow_html=True)
            for i,food in enumerate(st.session_state.food_results):
                cf,cs=st.columns([8,2])
                with cf:
                    st.markdown(f"""<div class="food-result">
                      <div class="food-result-name">{food['name']}</div>
                      {('<div class="food-result-brand">'+food['brand']+'</div>') if food['brand'] else ''}
                      <div class="food-result-macros">Per 100g — ⚡{food['calories_100g']} kcal · P:{food['protein_100g']}g C:{food['carbs_100g']}g F:{food['fat_100g']}g</div>
                    </div>""",unsafe_allow_html=True)
                with cs:
                    if st.button("Select",key=f"sel_{i}",use_container_width=True):
                        st.session_state.selected_food=food; st.rerun()
        if st.session_state.selected_food:
            f=st.session_state.selected_food; st.divider()
            st.markdown(f"**Selected:** {f['name']}")
            add_meal_form(f['name'],f['calories_100g'],f['protein_100g'],f['carbs_100g'],f['fat_100g'],f['fiber_100g'],"search")

    with tab_ai:
        st.markdown("Describe what you ate — AI estimates the breakdown.")
        desc=st.text_area("",height=120,placeholder="e.g. A bowl of oatmeal with banana and peanut butter",label_visibility="collapsed")
        if st.button("🤖 Analyse with AI",type="primary"):
            if not desc.strip(): st.warning("Describe your meal.")
            elif not st.session_state.api_key: st.error("No API key — go to ⚙️ Settings.")
            else:
                with st.spinner("Analysing…"):
                    try: st.session_state["ai_meal_result"]=ai_analyze_meal(desc)
                    except json.JSONDecodeError: st.error("AI returned invalid format. Try rephrasing.")
                    except Exception as e: st.error(str(e))
        if st.session_state.get("ai_meal_result"):
            r=st.session_state.ai_meal_result
            st.success(f"**{r.get('food_name','')}** — {r.get('serving_description','')}")
            add_meal_form(r.get("food_name",""),r.get("calories",0),r.get("protein_g",0),
                         r.get("carbs_g",0),r.get("fat_g",0),r.get("fiber_g",0),"ai")

    with tab_manual:
        add_meal_form(kp="manual")

# ══════════════════════════════════════════════════════════════════════════════
# AI CHAT
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "chat":
    st.markdown("## 🤖 AI Nutrition Chat")
    today_meals=get_meals(TODAY); t=totals(today_meals)
    prompts=["What should I eat for dinner?","Am I hitting my protein goals?",
             "Suggest a high-protein breakfast","How can I reduce calories today?","Analyse my diet today"]
    qp_cols=st.columns(len(prompts)); selected_prompt=None
    for i,(col,pr) in enumerate(zip(qp_cols,prompts)):
        with col:
            if st.button(pr,key=f"qp_{i}",use_container_width=True): selected_prompt=pr
    st.divider()
    if not st.session_state.chat_history:
        st.markdown("""<div style='text-align:center;padding:40px 20px;color:#78909C'>
          <div style='font-size:42px'>🤖</div>
          <div style='font-weight:600;margin-top:10px'>WellPlate is ready to help</div>
          <div style='font-size:13px;margin-top:4px'>Ask about nutrition, get meal ideas, or get a diet analysis</div>
        </div>""",unsafe_allow_html=True)
    else:
        for h in st.session_state.chat_history:
            st.markdown(f'<div class="chat-meta">You</div><div class="chat-user">{h["user"]}</div>',unsafe_allow_html=True)
            st.markdown(f'<div class="chat-meta">🤖 WellPlate</div><div class="chat-ai">{h["ai"]}</div>',unsafe_allow_html=True)
    user_input=st.chat_input("Ask WellPlate anything about your nutrition…")
    final_input=selected_prompt or user_input
    if final_input:
        if not st.session_state.api_key: st.error("No API key — go to ⚙️ Settings.")
        else:
            with st.spinner("Thinking…"):
                try:
                    reply=ai_chat(final_input,st.session_state.chat_history,profile,today_meals)
                    st.session_state.chat_history.append({"user":final_input,"ai":reply}); st.rerun()
                except Exception as e: st.error(str(e))
    if st.session_state.chat_history:
        if st.button("🗑️ Clear chat"): st.session_state.chat_history=[]; st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# PROGRESS
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "progress":
    st.markdown("## 📊 Progress")
    col_range,_=st.columns([1,3])
    with col_range: days=st.selectbox("Range",[7,14,30,90],format_func=lambda d:f"Last {d} days")
    meals_range=get_meals_range(days); weight_range=get_weight_range(days)
    day_data={}
    for d_off in range(days,-1,-1):
        d=(date.today()-timedelta(days=d_off)).isoformat()
        day_data[d]={"calories":0,"protein":0,"carbs":0,"fat":0}
    for m in meals_range:
        if m["date"] in day_data:
            day_data[m["date"]]["calories"]+=m["calories"]
            day_data[m["date"]]["protein"]+=m["protein_g"]
            day_data[m["date"]]["carbs"]+=m["carbs_g"]
            day_data[m["date"]]["fat"]+=m["fat_g"]
    dl=list(day_data.keys())
    cal_l=[day_data[d]["calories"] for d in dl]; pro_l=[day_data[d]["protein"] for d in dl]
    carb_l=[day_data[d]["carbs"] for d in dl]; fat_l=[day_data[d]["fat"] for d in dl]
    cal_goal=profile.get("calorie_goal",2000)
    logged=sum(1 for c in cal_l if c>0); avg_cal=sum(cal_l)/logged if logged else 0
    sc1,sc2,sc3,sc4=st.columns(4)
    with sc1: st.markdown(f'<div class="metric-card"><div class="metric-label">Avg Calories</div><div class="metric-value" style="color:#FF6F00">{int(avg_cal)}</div><div class="metric-sub">goal:{cal_goal}</div></div>',unsafe_allow_html=True)
    avg_pro=sum(pro_l)/logged if logged else 0
    with sc2: st.markdown(f'<div class="metric-card"><div class="metric-label">Avg Protein</div><div class="metric-value" style="color:#1565C0">{int(avg_pro)}g</div><div class="metric-sub">goal:{profile.get("protein_goal_g",120)}g</div></div>',unsafe_allow_html=True)
    with sc3: st.markdown(f'<div class="metric-card"><div class="metric-label">Days Logged</div><div class="metric-value" style="color:#2E7D32">{logged}</div><div class="metric-sub">of {days} days</div></div>',unsafe_allow_html=True)
    with sc4:
        st2=get_streak()
        st.markdown(f'<div class="metric-card"><div class="metric-label">Streak</div><div class="metric-value" style="color:#FF8F00">🔥{st2}</div><div class="metric-sub">days in a row</div></div>',unsafe_allow_html=True)
    st.markdown("<br/>",unsafe_allow_html=True)
    col_c,col_m=st.columns(2)
    with col_c:
        st.markdown('<div class="sec-header">⚡ Daily Calories</div>',unsafe_allow_html=True)
        fig=go.Figure(go.Bar(x=dl,y=cal_l,marker_color=["#EF5350" if c>cal_goal else "#43A047" for c in cal_l]))
        fig.add_hline(y=cal_goal,line_dash="dash",line_color="#FF8F00",annotation_text=f"Goal ({cal_goal})")
        fig.update_layout(height=280,margin=dict(t=10,b=0,l=0,r=0),
            paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(showticklabels=days<=14),yaxis_title="kcal",showlegend=False)
        st.plotly_chart(fig,use_container_width=True,config={"displayModeBar":False})
    with col_m:
        st.markdown('<div class="sec-header">💪 Macro Split</div>',unsafe_allow_html=True)
        avg_carb=sum(carb_l)/logged if logged else 0; avg_fat=sum(fat_l)/logged if logged else 0
        if avg_pro+avg_carb+avg_fat>0:
            fig2=go.Figure(go.Pie(labels=["Protein","Carbs","Fat"],
                values=[avg_pro*4,avg_carb*4,avg_fat*9],
                marker_colors=["#1565C0","#FF8F00","#C62828"],hole=0.55,
                textinfo="label+percent",textfont_size=12))
            fig2.update_layout(height=280,margin=dict(t=0,b=0,l=0,r=10),
                paper_bgcolor="rgba(0,0,0,0)",
                annotations=[dict(text=f"<b>{int(avg_cal)}</b><br>avg kcal",x=0.5,y=0.5,font_size=13,showarrow=False)])
            st.plotly_chart(fig2,use_container_width=True,config={"displayModeBar":False})
        else: st.info("Log meals to see macro breakdown.")
    st.markdown('<div class="sec-header">📈 Macro Trends</div>',unsafe_allow_html=True)
    fig3=go.Figure()
    fig3.add_trace(go.Scatter(x=dl,y=pro_l,name="Protein",line=dict(color="#1565C0",width=2),fill="tozeroy",fillcolor="rgba(21,101,192,.08)"))
    fig3.add_trace(go.Scatter(x=dl,y=carb_l,name="Carbs",line=dict(color="#FF8F00",width=2)))
    fig3.add_trace(go.Scatter(x=dl,y=fat_l,name="Fat",line=dict(color="#C62828",width=2)))
    fig3.update_layout(height=250,margin=dict(t=10,b=0,l=0,r=0),
        paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",yaxis_title="grams",
        xaxis=dict(showticklabels=days<=14),legend=dict(orientation="h",yanchor="bottom",y=1.02))
    st.plotly_chart(fig3,use_container_width=True,config={"displayModeBar":False})
    st.divider()
    col_wt,col_wlog=st.columns([3,1])
    with col_wt:
        st.markdown('<div class="sec-header">⚖️ Weight Trend</div>',unsafe_allow_html=True)
        if weight_range:
            fig4=px.line(weight_range,x="date",y="weight_kg",markers=True,color_discrete_sequence=["#2E7D32"])
            fig4.update_traces(line_width=2.5,marker_size=7)
            fig4.update_layout(height=220,margin=dict(t=0,b=0,l=0,r=0),
                paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(0,0,0,0)",yaxis_title="kg",xaxis_title="")
            st.plotly_chart(fig4,use_container_width=True,config={"displayModeBar":False})
        else: st.info("No weight entries yet.")
    with col_wlog:
        st.markdown('<div class="sec-header">Log Weight</div>',unsafe_allow_html=True)
        wd=st.date_input("Date",value=date.today(),key="wdate")
        wv=st.number_input("Weight (kg)",value=float(profile.get("weight_kg",70)),min_value=20.0,max_value=300.0,step=0.1)
        if st.button("💾 Save",use_container_width=True,type="primary"):
            if USE_SUPABASE:
                sb=get_sb()
                if sb:
                    try:
                        sb.table("weight_log").insert({"id":str(uuid.uuid4()),"user_id":_uid(),
                            "date":wd.isoformat(),"weight_kg":wv,"notes":"",
                            "created_at":datetime.now().isoformat()}).execute()
                        st.success("Saved!"); st.rerun()
                    except Exception as e: st.error(str(e))
            else:
                _local_save_weight(wd.isoformat(), wv); st.success("Saved!"); st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# PROFILE & GOALS
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "profile":
    st.markdown("## 👤 Profile & Goals")
    p=profile
    tab_personal,tab_goals,tab_diet,tab_blood=st.tabs(["👤 Personal","🎯 Daily Goals","🥦 Diet","🩸 Blood Type"])
    with tab_personal:
        with st.form("profile_form"):
            c1,c2=st.columns(2)
            with c1:
                name=st.text_input("Name",value=p.get("name","User"))
                height=st.number_input("Height (cm)",value=float(p.get("height_cm",170)),min_value=100.0,max_value=250.0,step=0.5)
                act=st.selectbox("Activity",["sedentary","light","moderate","active","very_active"],
                    index=["sedentary","light","moderate","active","very_active"].index(p.get("activity_level","moderate")),
                    format_func=lambda x:{"sedentary":"🪑 Sedentary","light":"🚶 Light","moderate":"🏃 Moderate","active":"💪 Active","very_active":"⚡ Very active"}[x])
            with c2:
                age=st.number_input("Age",value=int(p.get("age",30)),min_value=10,max_value=120)
                weight=st.number_input("Weight (kg)",value=float(p.get("weight_kg",70)),min_value=20.0,max_value=300.0,step=0.5)
            if st.form_submit_button("💾 Save Profile",type="primary"):
                save_profile({"name":name,"age":age,"height_cm":height,"weight_kg":weight,"activity_level":act})
                st.success("Saved!"); st.rerun()
        h=p.get("height_cm",170)/100; w=p.get("weight_kg",70); bmi=w/(h*h)
        bmi_cat="Underweight" if bmi<18.5 else "Normal" if bmi<25 else "Overweight" if bmi<30 else "Obese"
        bmi_col="#1565C0" if bmi<18.5 else "#2E7D32" if bmi<25 else "#FF8F00" if bmi<30 else "#C62828"
        st.markdown(f'<div class="metric-card" style="margin-top:16px;max-width:300px"><div class="metric-label">BMI</div><div class="metric-value" style="color:{bmi_col}">{bmi:.1f}</div><div class="metric-sub">{bmi_cat}</div></div>',unsafe_allow_html=True)
    with tab_goals:
        with st.form("goals"):
            gc1,gc2=st.columns(2)
            with gc1:
                cal_g=st.number_input("Calories (kcal)",value=int(p.get("calorie_goal",2000)),min_value=500,max_value=10000)
                pro_g=st.number_input("Protein (g)",value=int(p.get("protein_goal_g",120)),min_value=0,max_value=500)
                water_g=st.number_input("Water (ml)",value=int(p.get("water_goal_ml",2500)),min_value=500,max_value=10000,step=250)
            with gc2:
                carb_g=st.number_input("Carbs (g)",value=int(p.get("carbs_goal_g",250)),min_value=0,max_value=1000)
                fat_g=st.number_input("Fat (g)",value=int(p.get("fat_goal_g",65)),min_value=0,max_value=500)
            st.caption(f"Macro total: {pro_g*4+carb_g*4+fat_g*9} kcal (goal: {cal_g})")
            if st.form_submit_button("💾 Save Goals",type="primary"):
                save_profile({"calorie_goal":cal_g,"protein_goal_g":pro_g,"carbs_goal_g":carb_g,"fat_goal_g":fat_g,"water_goal_ml":water_g})
                st.success("Saved!"); st.rerun()
    with tab_diet:
        with st.form("diet"):
            pref=st.selectbox("Dietary preference",
                ["none","vegetarian","vegan","pescatarian","keto","paleo","gluten_free","halal","kosher"],
                index=["none","vegetarian","vegan","pescatarian","keto","paleo","gluten_free","halal","kosher"].index(p.get("dietary_pref","none")),
                format_func=lambda x:{"none":"🍽️ No restriction","vegetarian":"🥦 Vegetarian","vegan":"🌱 Vegan",
                    "pescatarian":"🐟 Pescatarian","keto":"🥑 Keto","paleo":"🍖 Paleo",
                    "gluten_free":"🌾 Gluten-free","halal":"☪️ Halal","kosher":"✡️ Kosher"}[x])
            if st.form_submit_button("💾 Save",type="primary"):
                save_profile({"dietary_pref":pref}); st.success("Saved!")
    with tab_blood:
        BG_OPTIONS = ["unknown","A+","A-","B+","B-","AB+","AB-","O+","O-"]
        current_bg = p.get("blood_group","unknown")
        if current_bg not in BG_OPTIONS: current_bg = "unknown"
        with st.form("blood_form"):
            bg = st.selectbox("Blood Group",BG_OPTIONS,
                index=BG_OPTIONS.index(current_bg),
                format_func=lambda x: "❓ Unknown" if x=="unknown" else f"🩸 {x}")
            if st.form_submit_button("💾 Save Blood Group",type="primary"):
                save_profile({"blood_group":bg}); st.success("Saved!"); st.rerun()
        # Derive base type (A/B/AB/O) ignoring Rh factor
        base = None
        for t in ["AB","A","B","O"]:
            if current_bg.startswith(t):
                base = t; break
        if base and base in BLOOD_TYPE_DIET:
            d = BLOOD_TYPE_DIET[base]
            st.markdown(f"### {d['emoji']} {d['label']}")
            st.info(d["desc"])
            col_b, col_a = st.columns(2)
            with col_b:
                st.markdown("**✅ Beneficial foods**")
                for food in d["beneficial"]:
                    st.markdown(f"- {food}")
            with col_a:
                st.markdown("**❌ Foods to avoid**")
                for food in d["avoid"]:
                    st.markdown(f"- {food}")
            st.caption("Based on the Blood Type Diet theory (D'Adamo). Consult a healthcare professional before making dietary changes.")
        elif current_bg == "unknown":
            st.info("Select your blood group above to see personalized food recommendations.")

# ══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════════════════════
elif st.session_state.page == "settings":
    st.markdown("## ⚙️ Settings")
    p=profile; p_sub=p.get("subscription","free"); ai_used=p.get("ai_calls_this_month",0)
    tab_api,tab_plan,tab_data=st.tabs(["🤖 AI API","⭐ Plan","🗄️ Data"])
    with tab_api:
        api_key=st.text_input("OpenRouter API Key",value=st.session_state.api_key,type="password",placeholder="sk-or-…")
        st.caption("Free key at [openrouter.ai](https://openrouter.ai) — uses `nvidia/nemotron-3-super-120b-a12b:free`")
        if st.button("💾 Save Key",type="primary"): st.session_state.api_key=api_key.strip(); st.success("Saved.")
        st.divider()
        if st.button("🔌 Test Connection"):
            with st.spinner("Testing…"):
                try:
                    r=call_ai([{"role":"user","content":"Reply with exactly: OK"}],max_tokens=10)
                    st.success(f"Connected — `{r.strip()}`")
                except Exception as e: st.error(str(e))
    with tab_plan:
        if p_sub == "premium":
            st.markdown("""<div class="upgrade-card">
              <div style='font-size:32px'>⭐</div>
              <div style='font-size:22px;font-weight:800;margin-top:8px'>You're on Premium</div>
              <div style='font-size:14px;margin-top:6px;opacity:.9'>Unlimited AI analyses · All features unlocked</div>
            </div>""",unsafe_allow_html=True)
        else:
            used_pct=int(ai_used/FREE_AI_LIMIT*100)
            st.markdown(f"""<div style='background:#F7FBF7;border:1px solid #E8F5E9;border-radius:16px;padding:20px;margin-bottom:20px'>
              <div style='font-size:14px;font-weight:600;color:#555'>Free Plan — {ai_used}/{FREE_AI_LIMIT} AI calls used this month</div>
              <div style='height:8px;background:#E8F5E9;border-radius:4px;margin-top:10px'>
                <div style='height:8px;background:{"#EF5350" if used_pct>80 else "#43A047"};border-radius:4px;width:{used_pct}%'></div>
              </div>
            </div>
            <div class="upgrade-card">
              <div style='font-size:28px'>⭐</div>
              <div style='font-size:22px;font-weight:800;margin-top:8px'>Upgrade to Premium</div>
              <div style='font-size:14px;margin-top:6px;opacity:.9'>Unlimited AI · No monthly limits</div>
              <div style='font-size:28px;font-weight:800;margin-top:12px'>$4.99 <span style='font-size:14px;font-weight:400'>/month</span></div>
            </div>""",unsafe_allow_html=True)
            st.markdown("<br/>",unsafe_allow_html=True)
            if st.button("⭐ Upgrade to Premium",type="primary",use_container_width=True):
                sk = _get_secret("STRIPE_SECRET_KEY")
                pid = _get_secret("STRIPE_PRICE_ID")
                if not sk or not pid:
                    st.error(f"Secrets missing — SK: {'✅' if sk else '❌'} | Price ID: {'✅' if pid else '❌'}")
                else:
                    url=create_checkout_url(st.session_state.get("user_email",""))
                    if url: st.link_button("Complete Payment on Stripe →", url)
                    else: st.error("Stripe error — check that STRIPE_PRICE_ID is a valid recurring price ID.")
    with tab_data:
        all_meals=get_meals_range(365)
        mode_label = "☁️ Cloud (Supabase)" if USE_SUPABASE else "💻 Local (SQLite)"
        account = st.session_state.get('user_email','Local') if USE_SUPABASE else "Local Mode"
        st.markdown(f"""| | |\n|---|---|\n| **App** | WellPlate |\n| **Mode** | {mode_label} |
| **Account** | {account} |\n| **Plan** | {'⭐ Premium' if p_sub=='premium' else 'Free'} |
| **Meals logged** | {len(all_meals)} |""")
        st.divider()
        if all_meals:
            import json as _json
            st.download_button("⬇️ Export meals as JSON",
                data=_json.dumps(all_meals,indent=2),
                file_name=f"wellplate_export_{date.today()}.json",mime="application/json")
        st.divider()
        st.markdown('<div style="color:#EF5350;font-size:11px;font-weight:700;letter-spacing:1px;text-transform:uppercase">Danger Zone</div>',unsafe_allow_html=True)
        if st.button("🗑️ Delete ALL my data",type="secondary"):
            if USE_SUPABASE:
                sb=get_sb()
                if sb:
                    try:
                        sb.table("meals").delete().eq("user_id",_uid()).execute()
                        sb.table("water_log").delete().eq("user_id",_uid()).execute()
                        st.success("Cleared."); st.rerun()
                    except Exception as e: st.error(str(e))
            else:
                with _conn() as c:
                    c.execute("DELETE FROM meals"); c.execute("DELETE FROM water_log")
                st.success("All data cleared."); st.rerun()

