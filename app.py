#!/usr/bin/env python3
"""Vaishnav Bairagi Samaj — Community Website
Flask + SQLite. Public site + member registration + admin panel.
All CSS/JS/fonts/images are inlined into each page so the site works
even in environments that only allow top-level HTML documents.
"""
import os, re, io, base64, sqlite3, hashlib, datetime
from functools import wraps
from flask import (Flask, request, jsonify, render_template, redirect,
                   url_for, flash, session, g)
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "database.db")

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "bairagi123")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "vbsamaj-secret-2026")

# ---------------------------------------------------------------- inline assets
def _b64(path, mime):
    with open(path, "rb") as f:
        return "data:" + mime + ";base64," + base64.b64encode(f.read()).decode()

def build_assets():
    static = os.path.join(BASE, "static")
    with open(os.path.join(static, "css", "style.css"), encoding="utf-8") as f:
        css = f.read()
    # swap file-based @font-face blocks for embedded subset woff2 fonts
    fonts_css = ""
    for fname, family, weight in (
        ("RozhaOne.subset.woff2", "Rozha One", "400"),
        ("NotoDevanagari.subset.woff2", "Noto Deva", "100 900"),
    ):
        uri = _b64(os.path.join(static, "fonts", fname), "font/woff2")
        fonts_css += ('@font-face{font-family:"%s";src:url("%s") format("woff2");'
                      'font-weight:%s;font-display:swap}\n' % (family, uri, weight))
    css = re.sub(r"@font-face\s*\{[^}]*\}\s*", "", css)
    with open(os.path.join(static, "js", "main.js"), encoding="utf-8") as f:
        js = f.read()
    return {
        "STYLE": fonts_css + css,
        "SCRIPT": js,
        "LOGO": _b64(os.path.join(static, "img", "vaishnav-bairagi-samaj-logo-512.png"), "image/png"),
    }

ASSETS = build_assets()

@app.context_processor
def inject_assets():
    return {"ASSETS": ASSETS}

STATES = [
    "Andhra Pradesh (आंध्र प्रदेश)", "Bihar (बिहार)", "Chhattisgarh (छत्तीसगढ़)",
    "Delhi (दिल्ली)", "Gujarat (गुजरात)", "Haryana (हरियाणा)",
    "Himachal Pradesh (हिमाचल प्रदेश)", "Jharkhand (झारखंड)",
    "Karnataka (कर्नाटक)", "Madhya Pradesh (मध्य प्रदेश)",
    "Maharashtra (महाराष्ट्र)", "Odisha (ओडिशा)", "Punjab (पंजाब)",
    "Rajasthan (राजस्थान)", "Tamil Nadu (तमिलनाडु)", "Telangana (तेलंगाना)",
    "Uttar Pradesh (उत्तर प्रदेश)", "Uttarakhand (उत्तराखंड)",
    "West Bengal (पश्चिम बंगाल)", "Other (अन्य)",
]

PROFESSIONS = [
    "किसान / Farmer", "व्यापार / Business", "सरकारी सेवा / Govt. Service",
    "शिक्षक / Teacher", "डॉक्टर / Doctor", "वकील / Advocate",
    "इंजीनियर / Engineer", "पुजारी-प्रचारक / Priest-Preacher",
    "छात्र / Student", "स्वरोजगार / Self-employed", "अन्य / Other",
]

MAHA_DISTRICTS = [
    "अकोला", "अमरावती", "छत्रपती संभाजीनगर", "ठाणे", "नागपुर", "नंदुरबार", "नांदेड",
    "नाशिक", "पुणे", "परभणी", "बीड", "बुलडाणा", "मुंबई", "यवतमाळ", "रत्नागिरी",
    "जलगांव", "जालना", "धुळे", "सांगली", "सातारा", "सिंधुदुर्ग", "सोलापूर",
    "कोल्हापूर", "लातूर", "वर्धा", "वाशिम", "हिंगोली", "अन्य",
]

# ---------------------------------------------------------------- database
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(DB)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        father_name TEXT,
        phone TEXT,
        email TEXT,
        village TEXT NOT NULL,
        district TEXT,
        state TEXT NOT NULL,
        profession TEXT NOT NULL,
        details TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        location TEXT,
        event_date TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT,
        message TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS committee (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        role TEXT NOT NULL,
        name TEXT NOT NULL,
        place TEXT,
        phone TEXT,
        sort_order INTEGER DEFAULT 99
    );
    CREATE TABLE IF NOT EXISTS gallery (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        caption TEXT,
        filename TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS rsvp (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        phone TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    if os.environ.get("SEED_DEMO") == "1" and db.execute("SELECT COUNT(*) c FROM members").fetchone()[0] == 0:
        seed = [
            # name, father/guardian, phone, email, village, district, state, profession, details, status
            ("कमलाबाई गोपाळराव पाटील", "श्री. गोपाळराव पाटील", "9822010101", "", "बुलडाणा", "बुलडाणा",
             "Maharashtra (महाराष्ट्र)", "किसान / Farmer", "सोयाबीन-कापूस शेती, गटप्रमुख", "approved"),
            ("सुंदराबाई विठ्ठलदास वैष्णव", "श्री. विठ्ठलदास वैष्णव", "9422070707", "", "नागपुर", "नागपुर",
             "Maharashtra (महाराष्ट्र)", "व्यापार / Business", "किराणा व किराणा सामान व्यवसाय", "approved"),
            ("डॉ. मीरा नारायण शर्मा", "डॉ. नारायण शर्मा", "9890040404", "meera@example.com", "अंबड", "छत्रपती संभाजीनगर",
             "Maharashtra (महाराष्ट्र)", "डॉक्टर / Doctor", "सामान्य चिकित्सा, मोफत आरोग्य शिबिरे", "approved"),
            ("शारदाबाई पांडुरंग देशमुख", "श्री. पांडुरंग देशमुख", "9860050505", "", "सोलापूर", "सोलापूर",
             "Maharashtra (महाराष्ट्र)", "शिक्षक / Teacher", "प्राथमिक शाळा मुख्याध्यापिका — २० वर्षे सेवा", "approved"),
            ("कौसल्यादेवी राजाराम महाराज", "श्री. राजाराम महाराज", "9145030303", "", "अकोला", "अकोला",
             "Maharashtra (महाराष्ट्र)", "पुजारी-प्रचारक / Priest-Preacher", "कीर्तन-प्रवचन, भजनी मंडळ प्रमुख", "approved"),
            ("रुक्मिणी बाळू भोसले", "श्री. बाळू भोसले", "9769090909", "", "नाशिक", "नाशिक",
             "Maharashtra (महाराष्ट्र)", "स्वरोजगार / Self-employed", "पापड-मसाले घरगुती उद्योग", "approved"),
            ("वर्षा संतोष खाडे", "श्री. संतोष खाडे", "9096080808", "", "अमरावती", "अमरावती",
             "Maharashtra (महाराष्ट्र)", "छात्र / Student", "B.Sc. अंतिम वर्ष", "pending"),
            ("मंगल प्रकाश जाधव", "श्री. प्रकाश जाधव", "9372020202", "", "कोल्हापूर", "कोल्हापूर",
             "Maharashtra (महाराष्ट्र)", "व्यापार / Business", "दुग्ध व्यवसाय", "pending"),
        ]
        db.executemany("""INSERT INTO members
            (name, father_name, phone, email, village, district, state, profession, details, status)
            VALUES (?,?,?,?,?,?,?,?,?,?)""", seed)
    if os.environ.get("SEED_DEMO") == "1" and db.execute("SELECT COUNT(*) c FROM events").fetchone()[0] == 0:
        ev = [
            ("महिला दीपावली मिलन समारोह", "समस्त बहनों सहित दीपावली मिलन, भजन संध्या एवं सामूहिक भोजन।",
             "समाज भवन, बुलडाणा", "2026-10-20"),
            ("भजन-कीर्तन संध्या", "बहनों के भजनी मंडळ द्वारा कीर्तन एवं गीता पाठ।",
             "राम मंदिर परिसर, नागपुर", "2026-11-30"),
            ("वार्षिक महिला महासभा अधिवेशन", "वार्षिक रिपोर्ट, नवीन पदाधिकारिणी नियुक्ति एवं बहनों का सम्मान समारोह।",
             "समाज भवन, बुलडाणा", "2026-12-14"),
        ]
        db.executemany("INSERT INTO events (title, description, location, event_date) VALUES (?,?,?,?)", ev)
    db.commit()
    db.close()

def _admin_token():
    """Daily rotating key, works even where browsers block cookies."""
    today = datetime.date.today().isoformat()
    return hashlib.sha256((app.secret_key + today).encode()).hexdigest()[:24]

def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if session.get("admin"):
            return f(*a, **kw)
        if request.values.get("k") == _admin_token():
            return f(*a, **kw)
        return redirect(url_for("admin_login"))
    return wrapper

# ---------------------------------------------------------------- public pages
@app.route("/")
def home():
    db = get_db()
    stats = {
        "members": db.execute("SELECT COUNT(*) c FROM members WHERE status='approved'").fetchone()["c"],
        "villages": db.execute("SELECT COUNT(DISTINCT village) c FROM members WHERE status='approved'").fetchone()["c"],
        "professions": db.execute("SELECT COUNT(DISTINCT profession) c FROM members WHERE status='approved'").fetchone()["c"],
        "states": db.execute("SELECT COUNT(DISTINCT state) c FROM members WHERE status='approved'").fetchone()["c"],
    }
    latest = db.execute("""SELECT name, village, district, state, profession
                           FROM members WHERE status='approved'
                           ORDER BY id DESC LIMIT 3""").fetchall()
    notices = db.execute("SELECT text FROM announcements ORDER BY id DESC LIMIT 10").fetchall()
    return render_template("index.html", stats=stats, latest=latest, notices=notices)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/committee")
def committee_page():
    rows = get_db().execute("SELECT * FROM committee ORDER BY sort_order, id").fetchall()
    return render_template("committee.html", members=rows)

@app.route("/gallery")
def gallery_page():
    photos = get_db().execute("SELECT * FROM gallery ORDER BY id DESC LIMIT 60").fetchall()
    return render_template("gallery.html", photos=photos)

@app.route("/id-card/<int:mid>")
def id_card(mid):
    m = get_db().execute("SELECT * FROM members WHERE id=? AND status='approved'", (mid,)).fetchone()
    if not m:
        flash("यह सदस्य उपलब्ध नहीं / Member not available", "error")
        return redirect(url_for("directory"))
    return render_template("id_card.html", m=m)

UPLOAD_DIR = os.path.join(BASE, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.route("/photo/<int:pid>")
def photo_serve(pid):
    """Serve gallery photos from disk."""
    row = get_db().execute("SELECT filename FROM gallery WHERE id=?", (pid,)).fetchone()
    if not row:
        return "not found", 404
    from flask import send_from_directory
    return send_from_directory(UPLOAD_DIR, row["filename"])

@app.route("/directory")
def directory():
    return render_template("directory.html", states=STATES, professions=PROFESSIONS,
                           districts=MAHA_DISTRICTS)

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        village = f.get("village", "").strip()
        state = f.get("state", "").strip()
        profession = f.get("profession", "").strip()
        phone = f.get("phone", "").strip()
        email = f.get("email", "").strip()
        errors = []
        if not name: errors.append("कृपया अपना नाम लिखें / Please enter your name")
        if not village: errors.append("कृपया गाँव/शहर लिखें / Please enter village/city")
        if not state: errors.append("कृपया राज्य चुनें / Please select state")
        if not profession: errors.append("कृपया पेशा चुनें / Please select profession")
        if phone and not re.fullmatch(r"[0-9+\s-]{10,15}", phone):
            errors.append("फ़ोन नंबर सही नहीं है / Invalid phone number")
        if errors:
            for e in errors: flash(e, "error")
            return render_template("register.html", states=STATES, professions=PROFESSIONS, districts=MAHA_DISTRICTS, old=f)
        get_db().execute("""INSERT INTO members
            (name, father_name, phone, email, village, district, state, profession, details, status)
            VALUES (?,?,?,?,?,?,?,?,?, 'pending')""",
            (name, f.get("father_name", "").strip(), phone, email, village,
             f.get("district", "").strip(), state, profession, f.get("details", "").strip()))
        get_db().commit()
        return render_template("thankyou.html", name=name)
    return render_template("register.html", states=STATES, professions=PROFESSIONS, districts=MAHA_DISTRICTS)

@app.route("/events")
def events_page():
    evs = get_db().execute("SELECT * FROM events ORDER BY event_date").fetchall()
    counts = {r["event_id"]: r["c"] for r in get_db().execute(
        "SELECT event_id, COUNT(*) c FROM rsvp GROUP BY event_id").fetchall()}
    return render_template("events.html", events=evs, rsvp_counts=counts)

@app.route("/events/<int:eid>/rsvp", methods=["POST"])
def event_rsvp(eid):
    f = request.form
    name = f.get("name", "").strip()
    if name:
        get_db().execute("INSERT INTO rsvp (event_id, name, phone) VALUES (?,?,?)",
                         (eid, name, f.get("phone", "").strip()))
        get_db().commit()
        flash("🙏 धन्यवाद %s! आपकी उपस्थिति दर्ज हो गई। / Your RSVP is recorded!" % name, "success")
    else:
        flash("कृपया नाम लिखें / Please enter your name", "error")
    return redirect(url_for("events_page") + "#event-%d" % eid)

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        f = request.form
        name = f.get("name", "").strip()
        message = f.get("message", "").strip()
        if name and message:
            get_db().execute("INSERT INTO messages (name, phone, message) VALUES (?,?,?)",
                             (name, f.get("phone", "").strip(), message))
            get_db().commit()
            flash("आपका संदेश मिल गया है। धन्यवाद! / Message received. Thank you!", "success")
        else:
            flash("कृपया नाम व संदेश लिखें / Please fill name and message", "error")
        return redirect(url_for("contact"))
    return render_template("contact.html")

# ---------------------------------------------------------------- api
@app.route("/api/members")
def api_members():
    q = request.args.get("q", "").strip()
    state = request.args.get("state", "").strip()
    profession = request.args.get("profession", "").strip()
    place = request.args.get("place", "").strip()   # city / village filter
    sql = """SELECT name, village, district, state, profession, details, created_at
             FROM members WHERE status='approved'"""
    args = []
    if q:
        sql += " AND (name LIKE ? OR village LIKE ? OR district LIKE ? OR profession LIKE ?)"
        like = f"%{q}%"
        args += [like, like, like, like]
    if state:
        sql += " AND state = ?"; args.append(state)
    if profession:
        sql += " AND profession = ?"; args.append(profession)
    if place:
        sql += " AND (village LIKE ? OR district LIKE ?)"
        like = f"%{place}%"
        args += [like, like]
    sql += " ORDER BY name COLLATE NOCASE LIMIT 500"
    rows = get_db().execute(sql, args).fetchall()
    return jsonify([dict(r) for r in rows])

# ---------------------------------------------------------------- admin
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if (request.form.get("username") == ADMIN_USER and
                request.form.get("password") == ADMIN_PASSWORD):
            session["admin"] = True
            # redirect WITH key → admin keeps working even if cookies are blocked
            return redirect(url_for("admin_dashboard", k=_admin_token()))
        flash("गलत उपयोगकर्ता नाम या पासवर्ड / Wrong username or password", "error")
    return render_template("login.html")

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin_login"))

@app.route("/admin")
@login_required
def admin_dashboard():
    db = get_db()
    stats = {
        "pending": db.execute("SELECT COUNT(*) c FROM members WHERE status='pending'").fetchone()["c"],
        "approved": db.execute("SELECT COUNT(*) c FROM members WHERE status='approved'").fetchone()["c"],
        "rejected": db.execute("SELECT COUNT(*) c FROM members WHERE status='rejected'").fetchone()["c"],
        "messages": db.execute("SELECT COUNT(*) c FROM messages").fetchone()["c"],
    }
    pending = db.execute("SELECT * FROM members WHERE status='pending' ORDER BY id").fetchall()
    members = db.execute("SELECT * FROM members WHERE status='approved' ORDER BY name LIMIT 1000").fetchall()
    rejected = db.execute("SELECT * FROM members WHERE status='rejected' ORDER BY id DESC LIMIT 30").fetchall()
    evs = db.execute("SELECT * FROM events ORDER BY event_date").fetchall()
    msgs = db.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 50").fetchall()
    ann = db.execute("SELECT * FROM announcements ORDER BY id DESC LIMIT 20").fetchall()
    comm = db.execute("SELECT * FROM committee ORDER BY sort_order, id").fetchall()
    photos = db.execute("SELECT * FROM gallery ORDER BY id DESC LIMIT 60").fetchall()
    rsvp_counts = {r["event_id"]: r["c"] for r in db.execute(
        "SELECT event_id, COUNT(*) c FROM rsvp GROUP BY event_id").fetchall()}
    k = request.values.get("k", "")
    if k != _admin_token():
        k = ""  # session-authenticated user → no key needed in forms
    return render_template("admin.html", stats=stats, pending=pending,
                           members=members, rejected=rejected, events=evs,
                           messages=msgs, announcements=ann, committee=comm,
                           photos=photos, rsvp_counts=rsvp_counts, k=k,
                           today=datetime.date.today().strftime("%d %b %Y"))

@app.route("/admin/members/<int:mid>/<action>", methods=["POST"])
@login_required
def member_action(mid, action):
    if action in ("approve", "reject"):
        get_db().execute("UPDATE members SET status=? WHERE id=?",
                         ("approved" if action == "approve" else "rejected", mid))
    elif action == "delete":
        get_db().execute("DELETE FROM members WHERE id=?", (mid,))
    get_db().commit()
    return redirect(url_for("admin_dashboard", k=_admin_token()))

@app.route("/admin/events", methods=["POST"])
@login_required
def add_event():
    f = request.form
    if f.get("title", "").strip() and f.get("event_date", "").strip():
        get_db().execute("INSERT INTO events (title, description, location, event_date) VALUES (?,?,?,?)",
                         (f["title"].strip(), f.get("description", "").strip(),
                          f.get("location", "").strip(), f["event_date"].strip()))
        get_db().commit()
    return redirect(url_for("admin_dashboard", k=_admin_token()))

@app.route("/admin/events/<int:eid>/delete", methods=["POST"])
@login_required
def delete_event(eid):
    get_db().execute("DELETE FROM events WHERE id=?", (eid,))
    get_db().commit()
    return redirect(url_for("admin_dashboard", k=_admin_token()))

@app.route("/admin/messages/<int:mid>/delete", methods=["POST"])
@login_required
def delete_message(mid):
    get_db().execute("DELETE FROM messages WHERE id=?", (mid,))
    get_db().commit()
    return redirect(url_for("admin_dashboard", k=_admin_token()))

# ---- announcements (सूचना बोर्ड) ----
@app.route("/admin/announcements", methods=["POST"])
@login_required
def add_announcement():
    text = request.form.get("text", "").strip()
    if text:
        get_db().execute("INSERT INTO announcements (text) VALUES (?)", (text,))
        get_db().commit()
    return redirect(url_for("admin_dashboard", k=_admin_token()) + "#announce")

@app.route("/admin/announcements/<int:aid>/delete", methods=["POST"])
@login_required
def delete_announcement(aid):
    get_db().execute("DELETE FROM announcements WHERE id=?", (aid,))
    get_db().commit()
    return redirect(url_for("admin_dashboard", k=_admin_token()) + "#announce")

# ---- committee (कार्यकारिणी) ----
ROLES = ["अध्यक्षा", "उपाध्यक्षा", "सचिव", "सह-सचिव", "कोषाध्यक्षा", "योजना प्रमुख", "सदस्या"]

@app.route("/admin/committee", methods=["POST"])
@login_required
def add_committee():
    f = request.form
    name, role = f.get("name", "").strip(), f.get("role", "").strip()
    if name and role:
        order = ROLES.index(role) + 1 if role in ROLES else 99
        get_db().execute("""INSERT INTO committee (role, name, place, phone, sort_order)
                            VALUES (?,?,?,?,?)""",
                         (role, name, f.get("place", "").strip(),
                          f.get("phone", "").strip(), order))
        get_db().commit()
    return redirect(url_for("admin_dashboard", k=_admin_token()) + "#committee")

@app.route("/admin/committee/<int:cid>/delete", methods=["POST"])
@login_required
def delete_committee(cid):
    get_db().execute("DELETE FROM committee WHERE id=?", (cid,))
    get_db().commit()
    return redirect(url_for("admin_dashboard", k=_admin_token()) + "#committee")

# ---- gallery (फोटो गॅलरी) ----
@app.route("/admin/gallery", methods=["POST"])
@login_required
def upload_photo():
    f = request.files.get("photo")
    caption = request.form.get("caption", "").strip()
    if f and f.filename:
        ext = os.path.splitext(f.filename)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            flash("सिर्फ JPG/PNG फोटो डालें / Only JPG or PNG photos", "error")
            return redirect(url_for("admin_dashboard", k=_admin_token()) + "#gallery")
        img = Image.open(f.stream)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((1400, 1400), Image.LANCZOS)
        fname = "g_%d.jpg" % int(datetime.datetime.now().timestamp())
        img.save(os.path.join(UPLOAD_DIR, fname), "JPEG", quality=82, optimize=True)
        get_db().execute("INSERT INTO gallery (caption, filename) VALUES (?,?)", (caption, fname))
        get_db().commit()
    else:
        flash("फोटो चुनें / Please choose a photo", "error")
    return redirect(url_for("admin_dashboard", k=_admin_token()) + "#gallery")

@app.route("/admin/gallery/<int:pid>/delete", methods=["POST"])
@login_required
def delete_photo(pid):
    row = get_db().execute("SELECT filename FROM gallery WHERE id=?", (pid,)).fetchone()
    if row:
        try:
            os.remove(os.path.join(UPLOAD_DIR, row["filename"]))
        except OSError:
            pass
        get_db().execute("DELETE FROM gallery WHERE id=?", (pid,))
        get_db().commit()
    return redirect(url_for("admin_dashboard", k=_admin_token()) + "#gallery")

init_db()  # idempotent — safe under gunicorn too

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
