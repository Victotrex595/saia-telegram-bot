import os
import re
import sys
import time
import json
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from html import escape, unescape
import httpx
import urllib.parse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

GLOBAL_BOT = None

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/get-cookie":
            query = urllib.parse.parse_qs(parsed.query)
            token = query.get("token", [""])[0]
            expected_token = get_config("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN)
            if token and token == expected_token:
                cookie = GLOBAL_BOT.scraper.session_cookie if (GLOBAL_BOT and hasattr(GLOBAL_BOT, "scraper")) else MOODLE_SESSION
                self.send_response(200)
                self.send_header("Content-type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "ok", "moodle_session": cookie}).encode("utf-8"))
                return
            else:
                self.send_response(401)
                self.send_header("Content-type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Unauthorized: Token invalido.")
                return

        # Ruta de chequeo de salud para Render / Koyeb
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"SAIA Telegram Bot is running 24/7!")

    def log_message(self, format, *args):
        pass

def start_health_server():
    port = int(os.getenv("PORT", 8080))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        server.serve_forever()
    except Exception:
        pass

threading.Thread(target=start_health_server, daemon=True).start()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(SCRIPT_DIR, "saia_state.json")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

def get_config(key, default=None):
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                val = json.load(f).get(key.lower())
                if val:
                    return str(val).strip()
        except Exception:
            pass
    val = os.getenv(key)
    if val:
        return val.strip()
    return default

MOODLE_SESSION = get_config("MOODLE_SESSION", "a98fbkev364chb1s4d9qfv0pir")
TELEGRAM_BOT_TOKEN = get_config("TELEGRAM_BOT_TOKEN", "8916730385:AAEvY26U3Mkc5vDq2XBgJNXpbJAU6Ej-e4o")
TELEGRAM_CHAT_ID = str(get_config("TELEGRAM_CHAT_ID", "1452296186"))
COURSE_IDS = ["27752", "27753", "27604", "27611", "27755", "26639"]
BASE_URL = "https://saia2.psm.edu.ve"

SUBJECT_BUTTONS = [
    ("💰 Ing. Económica", "mat_27752"),
    ("⚡ Lab. de Física", "mat_27753"),
    ("🔬 Metodología II", "mat_27604"),
    ("📊 Planif. Sistemas", "mat_27611"),
    ("💻 Prog. No Numérica", "mat_27755"),
    ("📡 Teoría de la Info", "mat_26639"),
]

MOD_TYPE_NAMES = {
    "assign": "Tarea",
    "quiz": "Cuestionario",
    "forum": "Foro",
    "workshop": "Taller",
    "lesson": "Lección",
    "glossary": "Glosario",
    "wiki": "Wiki",
    "data": "Base de datos",
    "h5pactivity": "H5P",
    "scorm": "Paquete SCORM",
    "lti": "Herramienta externa",
    "choice": "Consulta"
}

EVALUABLE_MOD_REGEX = r'(assign|quiz|forum|workshop|lesson|glossary|wiki|data|h5pactivity|scorm|lti|choice)'

MESES = {
    "enero": 1, "ene": 1, "feb": 2, "febrero": 2, "mar": 3, "marzo": 3,
    "abr": 4, "abril": 4, "may": 5, "mayo": 5, "jun": 6, "junio": 6,
    "jul": 7, "julio": 7, "ago": 8, "agosto": 8, "sep": 9, "sept": 9, "septiembre": 9,
    "oct": 10, "octubre": 10, "nov": 11, "noviembre": 11, "dic": 12, "diciembre": 12
}

def clean_text(text):
    if not text:
        return ""
    text = unescape(re.sub(r"<[^>]+>", " ", text)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()

def sanitize_course_name(name):
    clean = re.sub(r"\s+202\d-\d\s+[A-Z]\b", "", name)
    clean = re.sub(r"\s*/\s*", " / ", clean)
    return clean.strip()

def simplify_activity_title(title):
    t = title
    t = re.sub(r'I+ERA\s+ACTIVIDAD\s+EVALUATIVA\s+CORRESPONDIENTE\s+AL\s+\w+\s+CORTE\s*[\.\-:]*\s*', '', t, flags=re.I)
    t = re.sub(r'ACTIVIDAD\s+EVALUATIVA\s*[\.\-:]*\s*', '', t, flags=re.I)
    t = re.sub(r'VALOR\s+\d+\s+PUNTOS\s*', '', t, flags=re.I)
    t = re.sub(r'\s+', ' ', t).strip(' .:-')
    if t.isupper():
        t = t.capitalize()
    return t

def clean_calendar_event_title(raw_title):
    t = raw_title.strip()
    action = "due"
    if t.lower().startswith("se abre "):
        action = "open"
        t = t[8:].strip()
    elif t.lower().startswith("se cierra "):
        action = "close"
        t = t[10:].strip()
    elif t.lower().startswith("vencimiento de "):
        action = "due"
        t = t[15:].strip()
    elif t.lower().startswith("cierre de "):
        action = "close"
        t = t[10:].strip()
    elif t.lower().startswith("apertura de "):
        action = "open"
        t = t[12:].strip()
    return t, action

def parse_spanish_date(date_str):
    if not date_str:
        return None
    d = date_str.lower().strip()
    m = re.search(r'(\d{1,2})\s+(?:de\s+)?([a-záéíóú]+)(?:\s+(?:de\s+)?(\d{4}))?(?:[^\d]*(\d{1,2}):(\d{2}))?', d)
    if not m:
        return None
    day = int(m.group(1))
    mes_str = m.group(2).strip()
    month = MESES.get(mes_str)
    if not month:
        for k, v in MESES.items():
            if mes_str.startswith(k):
                month = v
                break
    if not month:
        return None

    year_str = m.group(3)
    tz_vzla = timezone(timedelta(hours=-4))
    now = datetime.now(tz_vzla)
    year = int(year_str) if year_str else now.year
    hour = int(m.group(4)) if m.group(4) else 23
    minute = int(m.group(5)) if m.group(5) else 59
    try:
        return datetime(year, month, day, hour, minute, tzinfo=tz_vzla)
    except Exception:
        return None

def extract_activity_dates_from_html(html):
    fechas = {"apertura": None, "cierre": None}
    if not html:
        return fechas

    patron = r'(?:<strong>\s*)?(Apertura|Abre|Abrió|Cierre|Cierra|Cerró|Vence|Vencimiento|Fecha de entrega|Fecha límite)\s*:(?:\s*</strong>)?\s*([^<\n\r]+)'
    for m in re.finditer(patron, html, re.I):
        tipo_lbl = m.group(1).lower()
        val = re.sub(r'<[^>]+>', ' ', m.group(2)).strip()
        val = re.sub(r'\s+', ' ', val).strip(' .:-')
        if any(w in tipo_lbl for w in ["apertura", "abre", "abrió"]):
            fechas["apertura"] = val
        elif any(w in tipo_lbl for w in ["cierre", "cierra", "cerró", "vence", "vencimiento", "fecha de entrega", "fecha límite"]):
            fechas["cierre"] = val

    if not fechas["cierre"]:
        m_due = re.search(r'<th[^>]*>(?:Fecha de entrega|Fecha límite)</th>\s*<td[^>]*>(.*?)</td>', html, re.I | re.S)
        if m_due:
            fechas["cierre"] = clean_text(m_due.group(1))

    if not fechas["cierre"]:
        m_txt = re.search(r'este cuestionario se cerr[oó] el\s*([^<\.]+)', html, re.I)
        if not m_txt:
            m_txt = re.search(r'este cuestionario se cerrar[aá] el\s*([^<\.]+)', html, re.I)
        if m_txt:
            fechas["cierre"] = clean_text(m_txt.group(1))

    return fechas

def format_date_compact(date_str, tiempo_str):
    if date_str:
        m = re.search(r'(?:([a-záéíóú]+)[,\s]+)?(\d{1,2})\s+(?:de\s+)?([a-záéíóú]{3})[a-záéíóú]*(?:[^\d]*\d{4})?(?:[^\d]*(\d{1,2}:\d{2}))?', date_str, re.I)
        if m:
            dia_sem = m.group(1).lower() if m.group(1) else ""
            num_dia = m.group(2)
            mes = m.group(3).lower()
            hora = f", {m.group(4)}" if m.group(4) else ""
            if dia_sem and dia_sem in ["lunes", "martes", "miércoles", "miercoles", "jueves", "viernes", "sábado", "sabado", "domingo"]:
                clean_dia = dia_sem.replace("é", "e").replace("á", "a")[:3]
                return f"📅 <b>{clean_dia} {num_dia} {mes}{hora}</b>"
            return f"📅 <b>{num_dia} {mes}{hora}</b>"
        return f"📅 <b>{date_str}</b>"

    if tiempo_str and tiempo_str != "-" and not tiempo_str.startswith("//"):
        m = re.search(r'(\d+\s*d[ií]as?(?:\s*\d+\s*horas?)?)', tiempo_str)
        if m:
            return f"⏱️ En {m.group(1)}"
        return f"⏱️ {tiempo_str}"
    return "📅 Sin fecha"

def detect_changes(old_state, current_state):
    alerts = []
    if not old_state or not old_state.get("courses"):
        return ["✨ <b>Inicio del sistema:</b> Primer registro guardado."]

    old_courses = {c["id"]: c for c in old_state.get("courses", [])}

    for cur in current_state.get("courses", []):
        cid = cur["id"]
        cname = cur["name"]

        if cid not in old_courses:
            alerts.append(f"📚 Nueva materia registrada: <b>{escape(cname)}</b>")
            continue

        old = old_courses[cid]

        if cur.get("total") != old.get("total") and cur.get("total") != "Sin calificar":
            alerts.append(f"🎯 <b>Nota final en {escape(cname)}:</b> <code>{escape(str(cur.get('total')))}</code>")

        old_grades = {g["title"]: g["calificacion"] for g in old.get("grades", [])}
        for g in cur.get("grades", []):
            g_title = g["title"]
            g_nota = g["calificacion"]
            if g_title in old_grades:
                if g_nota != "-" and g_nota != old_grades[g_title]:
                    alerts.append(f"📝 <b>Nueva nota en {escape(cname)}:</b> {escape(simplify_activity_title(g_title))}: <code>{escape(g_nota)}</code>")
            elif g_nota != "-":
                alerts.append(f"📝 <b>Nueva nota en {escape(cname)}:</b> {escape(simplify_activity_title(g_title))}: <code>{escape(g_nota)}</code>")

        old_acts = {a["link"]: a for a in old.get("activities", [])}
        for a in cur.get("activities", []):
            alink = a["link"]
            if alink not in old_acts:
                alerts.append(f"🆕 <b>Nueva tarea en {escape(cname)}:</b> {escape(simplify_activity_title(a['title']))}")
            else:
                if not old_acts[alink].get("es_realizada") and a.get("es_realizada"):
                    alerts.append(f"✅ <b>Entregada en {escape(cname)}:</b> {escape(simplify_activity_title(a['title']))}")

    return alerts

def format_telegram_message_clean(current_state, alerts):
    tz_vzla = timezone(timedelta(hours=-4))
    ahora = datetime.now(tz_vzla).strftime("%d/%m · %I:%M %p")

    lines = []
    lines.append(f"🎓 <b>SAIA · {ahora}</b>")

    if alerts and not any("Primer registro" in a for a in alerts):
        lines.append("\n🚨 <b>NOVEDADES:</b>")
        for al in alerts:
            lines.append(f"• {al}")
    else:
        lines.append("ℹ️ <i>Sin cambios nuevos en SAIA.</i>")

    lines.append("\n⏳ <b>ACTIVIDADES PENDIENTES:</b>\n")

    total_pendientes_activas = 0

    for c in current_state.get("courses", []):
        cname = c["name"]
        pendientes_activas = [
            a for a in c.get("activities", [])
            if not a.get("es_realizada") and not a.get("es_atrasada")
        ]

        if not pendientes_activas:
            continue

        total_pendientes_activas += len(pendientes_activas)
        lines.append(f"📚 <b>{escape(cname)}</b>")

        for p in pendientes_activas:
            titulo_limpio = escape(simplify_activity_title(p["title"]))
            link = p["link"]
            fecha_str = format_date_compact(p.get("fecha_calendario"), p.get("tiempo"))
            lines.append(f"• <a href=\"{link}\">{titulo_limpio}</a> — {fecha_str}")
        lines.append("")

    if total_pendientes_activas == 0:
        lines.append("🎉 <b>¡No tienes actividades pendientes por entregar!</b>")
    else:
        lines.append(f"📊 <b>Total por entregar:</b> {total_pendientes_activas}")

    return "\n".join(lines).strip()

class SaiaEngine:
    def __init__(self, session_cookie):
        self.session_cookie = session_cookie
        self._init_client(session_cookie)

    def _init_client(self, cookie):
        self.client = httpx.Client(
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"},
            cookies={"MoodleSession": cookie},
            follow_redirects=False,
            timeout=25.0
        )

    def update_cookie(self, new_cookie):
        self.session_cookie = new_cookie
        try:
            self.client.close()
        except Exception:
            pass
        self._init_client(new_cookie)

    def verify_session(self, cookie=None):
        chk_cookie = cookie or self.session_cookie
        c = self.client if (cookie is None) else httpx.Client(
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            cookies={"MoodleSession": chk_cookie},
            follow_redirects=False,
            timeout=25.0
        )
        should_close = (cookie is not None)
        try:
            r = c.get(f"{BASE_URL}/my/")
            if r.status_code == 200 and "login" not in r.text.lower()[:300]:
                return True
            loc = r.headers.get("location", "").lower()
            if r.status_code == 303 or "login" in loc:
                return False
            return True
        except (httpx.TimeoutException, httpx.NetworkError):
            print("[Aviso] Lag de red temporal con SAIA durante la comprobación de sesión.", flush=True)
            return True
        except Exception as e:
            print(f"[Aviso] Error comprobando sesión: {e}", flush=True)
            return False
        finally:
            if should_close:
                try:
                    c.close()
                except Exception:
                    pass

    def scrape_all(self):
        print("Sincronizando datos desde SAIA en paralelo...", flush=True)
        if not self.verify_session():
            print("[Aviso] Sesión caducada antes de iniciar el raspado. Conservando estado previo.", flush=True)
            if os.path.exists(STATE_FILE):
                try:
                    with open(STATE_FILE, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
            return {"timestamp": datetime.now().isoformat(), "courses": []}

        cal_events = self.get_calendar()

        def scrape_single_course(cid):
            cname_raw, total, grades = self.get_course_grades(cid)
            cname = sanitize_course_name(cname_raw)
            acts = self.get_course_activities(cid, cal_events.get(cid, []), grades)
            return {
                "id": cid,
                "name": cname,
                "total": total,
                "grades": grades,
                "activities": acts
            }

        with ThreadPoolExecutor(max_workers=6) as executor:
            courses_data = list(executor.map(scrape_single_course, COURSE_IDS))

        state = {
            "timestamp": datetime.now().isoformat(),
            "courses": courses_data
        }

        # Guardar en disco sólo si se obtuvieron datos válidos
        if any(len(c.get("activities", [])) > 0 or c.get("total") != "Sin calificar" for c in courses_data):
            try:
                with open(STATE_FILE, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"Error guardando estado: {e}", flush=True)

        return state

    def get_calendar(self):
        events = {}
        for view_param in ["upcoming", "month"]:
            url = f"{BASE_URL}/calendar/view.php?view={view_param}"
            try:
                res = self.client.get(url)
                if res.status_code != 200:
                    continue
                html = res.text
                splits = re.split(r'(?=<div[^>]*data-type="event")', html)
                for block in splits[1:]:
                    cid_m = re.search(r'data-course-id="(\d+)"', block)
                    if not cid_m:
                        continue
                    cid = cid_m.group(1)

                    raw_title_m = re.search(r'data-event-title="([^"]*)"', block)
                    if not raw_title_m:
                        raw_title_m = re.search(r'<h3[^>]*class="[^"]*name[^"]*"[^>]*>(.*?)</h3>', block, re.S)
                    raw_title = clean_text(raw_title_m.group(1)) if raw_title_m else "Evento"
                    clean_title, event_action = clean_calendar_event_title(raw_title)

                    type_m = re.search(r'data-event-eventtype="([^"]*)"', block)
                    ev_type = type_m.group(1).lower() if type_m else event_action

                    date_m = re.search(r'<span[^>]*class="[^"]*date\b[^"]*"[^>]*>(.*?)</span>', block, re.S)
                    date_str = clean_text(date_m.group(1)) if date_m else ""
                    parsed_dt = parse_spanish_date(date_str)

                    link_m = re.search(r'<a[^>]*href="(https://saia2\.psm\.edu\.ve/mod/' + EVALUABLE_MOD_REGEX + r'/view\.php\?id=\d+[^"]*)"', block)
                    link = link_m.group(1).replace("&amp;", "&") if link_m else ""
                    act_id_m = re.search(r'[?&]id=(\d+)', link)
                    act_id = act_id_m.group(1) if act_id_m else ""

                    if cid not in events:
                        events[cid] = []

                    # Evitar duplicados exactos
                    exists = any(
                        e.get("act_id") == act_id and e.get("event_type") == ev_type
                        for e in events[cid] if act_id
                    )
                    if not exists:
                        events[cid].append({
                            "raw_title": raw_title,
                            "clean_title": clean_title,
                            "date": date_str,
                            "parsed_dt": parsed_dt,
                            "link": link,
                            "act_id": act_id,
                            "event_type": ev_type
                        })
            except Exception as e:
                print(f"Error consultando calendario ({view_param}): {e}", flush=True)

        return events

    def get_course_grades(self, cid):
        url = f"{BASE_URL}/grade/report/user/index.php?id={cid}"
        try:
            res = self.client.get(url)
            if res.status_code != 200:
                return f"Curso {cid}", "Sin calificar", []
            html = res.text
            h1_m = re.search(r'class="page-header-headings"[^>]*>.*?<h1>(.*?)</h1>', html, re.S)
            if not h1_m:
                h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
            cname = clean_text(h1_m.group(1)) if h1_m else f"Curso {cid}"

            items = []
            course_total = "Sin calificar"
            table_m = re.search(r'<table[^>]*class="[^"]*user-grade[^"]*"[^>]*>(.*?)</table>', html, re.S)
            if table_m:
                rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_m.group(1), re.S)
                for r in rows:
                    r_clean = re.sub(r'<div[^>]*class="[^"]*action-menu[^"]*"[^>]*>.*?</div>', '', r, flags=re.S)
                    if "total" in r_clean.lower() and "itemname" in r_clean:
                        tds = re.findall(r"<td[^>]*>(.*?)</td>", r_clean, re.S)
                        clean_tds = [clean_text(td) for td in tds]
                        if len(clean_tds) >= 3:
                            nota = clean_tds[1] if clean_tds[1] and clean_tds[1] != "-" else "Sin calificar"
                            rango = clean_tds[2] if clean_tds[2] else ""
                            course_total = f"{nota} / {rango.split('–')[-1].split('-')[-1].strip()}" if (rango and nota != "Sin calificar") else nota

                    item_m = re.search(r'<th[^>]*class="[^"]*item\b[^"]*"[^>]*>(.*?)</th>', r_clean, re.S)
                    if item_m:
                        th_html = item_m.group(1)
                        item_title = clean_text(th_html)
                        for prefix in ['Tarea', 'Cuestionario', 'Foro', 'Taller', 'Lección']:
                            if item_title.startswith(prefix):
                                item_title = item_title[len(prefix):].strip()

                        lnk_m = re.search(r'href="(https://saia2\.psm\.edu\.ve/mod/' + EVALUABLE_MOD_REGEX + r'/view\.php\?id=(\d+))"', th_html)
                        link = lnk_m.group(1) if lnk_m else ""
                        mod_type = lnk_m.group(2) if lnk_m else ""
                        act_id = lnk_m.group(3) if lnk_m else ""

                        tds = re.findall(r"<td[^>]*>(.*?)</td>", r_clean, re.S)
                        clean_tds = [clean_text(td) for td in tds]
                        pond = clean_tds[0] if len(clean_tds) > 0 else "-"
                        calif = clean_tds[1] if len(clean_tds) > 1 else "-"
                        is_graded = bool(calif and calif != "-")

                        items.append({
                            "title": item_title,
                            "ponderacion": pond,
                            "calificacion": calif,
                            "link": link,
                            "mod_type": mod_type,
                            "act_id": act_id,
                            "is_graded": is_graded
                        })
            return cname, course_total, items
        except Exception as e:
            print(f"Error en notas {cid}: {e}", flush=True)
            return f"Curso {cid}", "Sin calificar", []

    def get_course_activities(self, cid, cal_events, grade_items):
        discovered_links = {}

        # 1. Página principal de la materia
        main_url = f"{BASE_URL}/course/view.php?id={cid}"
        html_main = ""
        try:
            res = self.client.get(main_url)
            if res.status_code == 200:
                html_main = res.text
                for m in re.finditer(r'<a[^>]*href="(https://saia2\.psm\.edu\.ve/mod/' + EVALUABLE_MOD_REGEX + r'/view\.php\?id=(\d+))"[^>]*>(.*?)</a>', html_main, re.S):
                    link, m_type, m_id, raw_t = m.group(1), m.group(2), m.group(3), m.group(4)
                    if m_id not in discovered_links:
                        discovered_links[m_id] = {
                            "link": link,
                            "type": m_type,
                            "id": m_id,
                            "title": clean_text(raw_t),
                            "source": "course_main"
                        }
        except Exception as e:
            print(f"Error cargando curso {cid}: {e}", flush=True)

        # 1b. Pestañas / secciones separadas del curso (si existen: &section=1, &section=2, etc.)
        if html_main:
            sections = set(re.findall(r'course/view\.php\?id=' + cid + r'(?:&amp;|&)section=(\d+)', html_main))
            for s_num in sorted(sections, key=lambda x: int(x)):
                try:
                    s_url = f"{BASE_URL}/course/view.php?id={cid}&section={s_num}"
                    s_res = self.client.get(s_url)
                    if s_res.status_code == 200:
                        for m in re.finditer(r'<a[^>]*href="(https://saia2\.psm\.edu\.ve/mod/' + EVALUABLE_MOD_REGEX + r'/view\.php\?id=(\d+))"[^>]*>(.*?)</a>', s_res.text, re.S):
                            link, m_type, m_id, raw_t = m.group(1), m.group(2), m.group(3), m.group(4)
                            if m_id not in discovered_links:
                                discovered_links[m_id] = {
                                    "link": link,
                                    "type": m_type,
                                    "id": m_id,
                                    "title": clean_text(raw_t),
                                    "source": f"section_{s_num}"
                                }
                except Exception:
                    pass

        # 2. Índices nativos de Moodle (/mod/assign/index.php y /mod/quiz/index.php)
        for idx_type in ["assign", "quiz"]:
            try:
                idx_url = f"{BASE_URL}/mod/{idx_type}/index.php?id={cid}"
                idx_res = self.client.get(idx_url)
                if idx_res.status_code == 200:
                    for m in re.finditer(r'<a[^>]*href="(https://saia2\.psm\.edu\.ve/mod/' + idx_type + r'/view\.php\?id=(\d+))"[^>]*>(.*?)</a>', idx_res.text, re.S):
                        link, m_id, raw_t = m.group(1), m.group(2), m.group(3)
                        if m_id not in discovered_links:
                            discovered_links[m_id] = {
                                "link": link,
                                "type": idx_type,
                                "id": m_id,
                                "title": clean_text(raw_t),
                                "source": f"index_{idx_type}"
                            }
            except Exception:
                pass

        # 3. Libro de calificaciones
        for gi in grade_items:
            g_link = gi.get("link")
            g_id = gi.get("act_id")
            g_type = gi.get("mod_type")
            if g_id and g_id not in discovered_links and g_link:
                discovered_links[g_id] = {
                    "link": g_link,
                    "type": g_type or "assign",
                    "id": g_id,
                    "title": gi.get("title", ""),
                    "source": "gradebook"
                }

        # 4. Calendario
        for ev in cal_events:
            ev_id = ev.get("act_id")
            ev_link = ev.get("link")
            if ev_id and ev_id not in discovered_links and ev_link:
                ev_type_m = re.search(r'/mod/' + EVALUABLE_MOD_REGEX + r'/', ev_link)
                ev_type = ev_type_m.group(1) if ev_type_m else "assign"
                discovered_links[ev_id] = {
                    "link": ev_link,
                    "type": ev_type,
                    "id": ev_id,
                    "title": ev.get("clean_title", ""),
                    "source": "calendar"
                }

        # Proceso y verificación de cada actividad encontrada
        activities = []
        default_forums = ["avisos", "cartelera informativa", "café virtual", "cafe virtual", "alguna duda", "foro de dudas", "dudas", "preguntas al profesor"]

        for m_id, act_info in discovered_links.items():
            mod_type = act_info["type"]
            title = act_info["title"]
            link = act_info["link"]

            # Limpiar sufijos
            for sfx in ["Tarea", "Cuestionario", "Foro", "Taller"]:
                if title.endswith(sfx):
                    title = title[:-len(sfx)].strip()

            # Descartar foros de anuncios generales por defecto
            if mod_type == "forum":
                t_lower = title.lower()
                is_default_forum = any(df in t_lower for df in default_forums)
                is_in_gradebook = any(gi.get("act_id") == m_id for gi in grade_items)
                if is_default_forum and not is_in_gradebook:
                    continue

            # Revisar si ya tiene nota registrada en el Gradebook
            is_graded = False
            for gi in grade_items:
                if gi.get("act_id") == m_id and gi.get("is_graded"):
                    is_graded = True
                    break

            # Obtener detalles profundos de la actividad
            detail = self.check_activity_detail(link, mod_type, is_graded=is_graded)

            # Cruzar con eventos de calendario para obtener fechas de respaldo
            cal_deadline = None
            cal_open = None
            for ev in cal_events:
                ev_id = ev.get("act_id")
                ev_type = ev.get("event_type", "")
                if ev_id and ev_id == m_id:
                    if ev_type in ["close", "due"]:
                        cal_deadline = ev["date"]
                        break
                    elif ev_type == "open":
                        cal_open = ev["date"]

            # Si no hubo coincidencia por ID, buscar por título normalizado estricto
            if not cal_deadline:
                norm_act = re.sub(r'[^a-z0-9]', '', simplify_activity_title(title).lower())
                for ev in cal_events:
                    norm_ev = re.sub(r'[^a-z0-9]', '', simplify_activity_title(ev.get("clean_title", "")).lower())
                    if norm_act and norm_ev and (norm_act == norm_ev):
                        if ev.get("event_type") in ["close", "due"]:
                            cal_deadline = ev["date"]
                            break

            fecha_final = detail.get("fecha_entrega") or cal_deadline or cal_open

            # Si la actividad aún no estaba marcada como atrasada pero la fecha ya expiró
            if not detail.get("es_realizada") and not detail.get("es_atrasada") and fecha_final:
                dt_final = parse_spanish_date(fecha_final)
                tz_vzla = timezone(timedelta(hours=-4))
                if dt_final and dt_final < datetime.now(tz_vzla):
                    detail["es_atrasada"] = True

            type_name = MOD_TYPE_NAMES.get(mod_type, mod_type.capitalize())

            activities.append({
                "title": title,
                "type": type_name,
                "mod_type": mod_type,
                "link": link,
                "fecha_calendario": fecha_final,
                **detail
            })

        return activities

    def check_activity_detail(self, link, mod_type, is_graded=False):
        try:
            res = self.client.get(link)
            if res.status_code != 200:
                return {
                    "estado": "Sin datos",
                    "tiempo": "-",
                    "fecha_entrega": None,
                    "es_realizada": is_graded,
                    "es_atrasada": False
                }
            html = res.text
            html_lower = html.lower()
            dates = extract_activity_dates_from_html(html)

            if mod_type == "assign":
                entrega_m = re.search(r'<th[^>]*>Estado de la entrega</th>\s*<td[^>]*>(.*?)</td>', html, re.S | re.I)
                calif_m = re.search(r'<th[^>]*>Estado de la calificaci[^\"]*</th>\s*<td[^>]*>(.*?)</td>', html, re.S | re.I)
                tiempo_m = re.search(r'<th[^>]*>Tiempo restante</th>\s*<td[^>]*>(.*?)</td>', html, re.S | re.I)
                fecha_m = re.search(r'<th[^>]*>Fecha de entrega</th>\s*<td[^>]*>(.*?)</td>', html, re.S | re.I)

                estado = clean_text(entrega_m.group(1)) if entrega_m else "Sin envíos"
                calif_est = clean_text(calif_m.group(1)) if calif_m else "-"
                tiempo = clean_text(tiempo_m.group(1)) if tiempo_m else "-"
                fecha_entrega = clean_text(fecha_m.group(1)) if fecha_m else dates.get("cierre")

                estado_lower = estado.lower()
                calif_lower = calif_est.lower()

                es_realizada = (
                    is_graded
                    or ("enviado para calificar" in estado_lower)
                    or ("entregado" in estado_lower and "no entregado" not in estado_lower and "sin entrega" not in estado_lower)
                    or ("calificado" in calif_lower and "no calificado" not in calif_lower and "sin calificar" not in calif_lower)
                )

                tiempo_lower = tiempo.lower()
                es_atrasada = False
                if not es_realizada:
                    if "retrasada" in tiempo_lower or "overdue" in tiempo_lower or "hace" in tiempo_lower:
                        es_atrasada = True
                    elif fecha_entrega:
                        dt = parse_spanish_date(fecha_entrega)
                        tz_vzla = timezone(timedelta(hours=-4))
                        if dt and dt < datetime.now(tz_vzla):
                            es_atrasada = True

                return {
                    "estado": estado,
                    "tiempo": tiempo,
                    "fecha_entrega": fecha_entrega,
                    "es_realizada": es_realizada,
                    "es_atrasada": es_atrasada
                }

            elif mod_type == "quiz":
                fecha_cierre = dates.get("cierre")
                es_realizada = (
                    is_graded
                    or "reintentar el cuestionario" in html_lower
                    or "resumen de sus intentos anteriores" in html_lower
                    or "calificación final en este cuestionario" in html_lower
                    or "no se permiten más intentos" in html_lower
                    or ("revisión" in html_lower and "finalizado" in html_lower)
                )

                es_atrasada = False
                if not es_realizada:
                    if "este cuestionario está cerrado" in html_lower or "cuestionario cerrado" in html_lower or "cerró" in html_lower:
                        es_atrasada = True
                    elif fecha_cierre:
                        dt = parse_spanish_date(fecha_cierre)
                        tz_vzla = timezone(timedelta(hours=-4))
                        if dt and dt < datetime.now(tz_vzla):
                            es_atrasada = True

                tiempo = f"Cierra: {fecha_cierre}" if fecha_cierre else ("Cuestionario cerrado" if es_atrasada else "-")
                estado = "Realizado" if es_realizada else ("Vencido" if es_atrasada else "Pendiente")

                return {
                    "estado": estado,
                    "tiempo": tiempo,
                    "fecha_entrega": fecha_cierre,
                    "es_realizada": es_realizada,
                    "es_atrasada": es_atrasada
                }

            else:
                fecha_cierre = dates.get("cierre")
                es_realizada = is_graded
                es_atrasada = False
                if not es_realizada and fecha_cierre:
                    dt = parse_spanish_date(fecha_cierre)
                    tz_vzla = timezone(timedelta(hours=-4))
                    if dt and dt < datetime.now(tz_vzla):
                        es_atrasada = True

                return {
                    "estado": "Realizado" if es_realizada else "Pendiente",
                    "tiempo": f"Cierra: {fecha_cierre}" if fecha_cierre else "-",
                    "fecha_entrega": fecha_cierre,
                    "es_realizada": es_realizada,
                    "es_atrasada": es_atrasada
                }
        except Exception:
            return {
                "estado": "Error",
                "tiempo": "-",
                "fecha_entrega": None,
                "es_realizada": is_graded,
                "es_atrasada": False
            }

class InteractiveBot:
    def __init__(self):
        global GLOBAL_BOT
        GLOBAL_BOT = self
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.scraper = SaiaEngine(MOODLE_SESSION)
        self.last_update_id = 0
        self.state_lock = threading.Lock()

        self.tg_client = httpx.Client(
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=60.0)
        )
        self.load_state()
        self.setup_telegram_commands()
        self.start_heartbeat()
        self.start_daily_scheduler()

    def setup_telegram_commands(self):
        url = f"{self.api_url}/setMyCommands"
        commands = [
            {"command": "reporte", "description": "📊 Reporte diario y resumen de materias"},
            {"command": "pendientes", "description": "⏳ Ver actividades pendientes por entregar"},
            {"command": "calificaciones", "description": "📈 Ver libreta de calificaciones"},
            {"command": "materia", "description": "📚 Elegir una materia y ver detalles"},
            {"command": "vencidas", "description": "⚠️ Ver actividades vencidas"},
            {"command": "actualizar", "description": "🔄 Sincronizar SAIA en tiempo real"},
            {"command": "cookie", "description": "🔑 Cambiar / renovar cookie de SAIA"},
            {"command": "url", "description": "🌐 Ver URL en la nube y para Obsidian"},
            {"command": "help", "description": "ℹ️ Ayuda e instrucciones"}
        ]
        try:
            r = self.tg_client.post(url, json={"commands": commands})
            if r.status_code == 200:
                print("[Telegram] Menú de comandos y sugerencias registrado con éxito.", flush=True)
            else:
                print(f"[Telegram] Error registrando comandos: {r.status_code}", flush=True)
        except Exception as e:
            print(f"[Telegram] Error al registrar comandos: {e}", flush=True)

    def send_daily_report(self):
        print("[Scheduler] Generando reporte diario programado...", flush=True)
        try:
            old_state = dict(self.state) if self.state else {}
            new_state = self.scraper.scrape_all()
            with self.state_lock:
                self.state = new_state

            if not self.state.get("courses") or all(len(c.get("activities", [])) == 0 and c.get("total") == "Sin calificar" for c in self.state.get("courses", [])):
                if not self.scraper.verify_session():
                    alert_msg = (
                        "⚠️ <b>ALERTA SAIA:</b> La sesión ha caducado en la universidad.\n\n"
                        "No se pudo enviar el reporte automático completo.\n"
                        "Para reactivar el bot al instante, abre SAIA en tu navegador y envíame:\n"
                        "<code>/cookie tu_nueva_cookie</code>"
                    )
                    self.send_message(self.chat_id, alert_msg)
                    return

            alerts = detect_changes(old_state, new_state)
            msg = format_telegram_message_clean(new_state, alerts)
            self.send_message(self.chat_id, msg)
            print("[Scheduler] Reporte diario enviado a Telegram exitosamente.", flush=True)
        except Exception as e:
            print(f"[Scheduler] Error al enviar reporte diario: {e}", flush=True)

    def start_daily_scheduler(self):
        def scheduler_worker():
            tz_vzla = timezone(timedelta(hours=-4))
            last_sent_slot = None
            print("[Scheduler] Programador diario activo (8:00 AM y 8:00 PM hora Venezuela VET).", flush=True)
            while True:
                try:
                    now = datetime.now(tz_vzla)
                    if now.hour in (8, 20) and now.minute == 0:
                        slot_key = f"{now.strftime('%Y-%m-%d')}_{now.hour}"
                        if slot_key != last_sent_slot:
                            last_sent_slot = slot_key
                            print(f"[{now.strftime('%H:%M:%S')}] [Scheduler] Disparando reporte diario programado ({slot_key})...", flush=True)
                            self.send_daily_report()
                except Exception as e:
                    print(f"[Scheduler] Excepción en ciclo de reloj: {e}", flush=True)
                time.sleep(20)

        threading.Thread(target=scheduler_worker, daemon=True).start()

    def start_heartbeat(self):
        def heartbeat_worker():
            time.sleep(120)
            while True:
                wait_seconds = random.randint(25 * 60, 35 * 60) + random.randint(5, 55)
                mins = wait_seconds / 60.0
                try:
                    alive = self.scraper.verify_session()
                    now_str = datetime.now().strftime("%H:%M:%S")
                    if alive:
                        print(f"[{now_str}] [Heartbeat] Sesión activa. Verificando novedades de profesores...", flush=True)
                        old_state = dict(self.state) if self.state else {}
                        new_state = self.scraper.scrape_all()
                        with self.state_lock:
                            self.state = new_state
                        alerts = detect_changes(old_state, new_state)
                        if alerts and not any("Primer registro" in a for a in alerts):
                            print(f"[{now_str}] [Novedad] ¡Nuevas actividades/notas detectadas! Notificando...", flush=True)
                            notif = "🔔 <b>ACTUALIZACIÓN DETECTADA EN SAIA:</b>\n\n" + "\n".join(f"• {a}" for a in alerts)
                            self.send_message(self.chat_id, notif)
                        print(f"[{now_str}] [Heartbeat] Comprobación completa. Próxima en ~{mins:.1f} min.", flush=True)
                    else:
                        print(f"[{now_str}] [Heartbeat] ALERTA: La sesión SAIA ha caducado.", flush=True)
                        alert_msg = (
                            "⚠️ <b>ALERTA SAIA:</b> La sesión ha caducado en la universidad.\n\n"
                            "Para reactivar el bot al instante, abre SAIA en tu navegador y envíame:\n"
                            "<code>/cookie tu_nueva_cookie</code>"
                        )
                        self.send_message(self.chat_id, alert_msg)
                except Exception as e:
                    print(f"[Heartbeat] Error: {e}", flush=True)

                time.sleep(wait_seconds)

        threading.Thread(target=heartbeat_worker, daemon=True).start()

    def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    self.state = json.load(f)
                    # Si el estado tiene cursos, no bloquear el arranque
                    if self.state.get("courses"):
                        def initial_refresh():
                            time.sleep(5)
                            try:
                                if self.scraper.verify_session():
                                    print("[Inicio] Refrescando datos en segundo plano...", flush=True)
                                    fresh = self.scraper.scrape_all()
                                    with self.state_lock:
                                        self.state = fresh
                                    print("[Inicio] Datos iniciales sincronizados con éxito.", flush=True)
                            except Exception:
                                pass
                        threading.Thread(target=initial_refresh, daemon=True).start()
                        return
            except Exception:
                pass
        try:
            self.state = self.scraper.scrape_all()
        except Exception as e:
            print(f"Error cargando estado inicial: {e}", flush=True)
            self.state = {"timestamp": datetime.now().isoformat(), "courses": []}

    def ensure_fresh_state(self):
        # Si el estado tiene más de 15 minutos, actualizar
        ts_str = self.state.get("timestamp")
        needs_refresh = True
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str)
                if (datetime.now() - ts).total_seconds() < 900:
                    needs_refresh = False
            except Exception:
                pass
        if needs_refresh and self.scraper.verify_session():
            print("[Caché] Refrescando estado por antigüedad...", flush=True)
            new_s = self.scraper.scrape_all()
            with self.state_lock:
                self.state = new_s

    def send_message(self, chat_id, text, reply_markup=None):
        chunks = []
        if len(text) <= 4000:
            chunks.append(text)
        else:
            parts = text.split("\n\n")
            current_chunk = ""
            for p in parts:
                if len(current_chunk) + len(p) + 2 > 3800:
                    chunks.append(current_chunk)
                    current_chunk = p
                else:
                    current_chunk = (current_chunk + "\n\n" + p).strip()
            if current_chunk:
                chunks.append(current_chunk)

        last_id = None
        for i, ch in enumerate(chunks):
            payload = {
                "chat_id": chat_id,
                "text": ch,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            if reply_markup and i == len(chunks) - 1:
                payload["reply_markup"] = reply_markup
            try:
                res = self.tg_client.post(f"{self.api_url}/sendMessage", json=payload)
                if res.status_code == 200:
                    last_id = res.json().get("result", {}).get("message_id")
            except Exception as e:
                print(f"Error enviando mensaje: {e}", flush=True)
        return last_id

    def edit_message(self, chat_id, message_id, text, reply_markup=None):
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            self.tg_client.post(f"{self.api_url}/editMessageText", json=payload)
        except Exception as e:
            print(f"Error editando mensaje: {e}", flush=True)

    def answer_callback(self, callback_query_id):
        try:
            self.tg_client.post(f"{self.api_url}/answerCallbackQuery", json={"callback_query_id": callback_query_id})
        except Exception:
            pass

    def handle_command_start(self, chat_id):
        msg = (
            "👋 <b>¡Hola! Soy tu asistente de SAIA - PSM.</b>\n\n"
            "Puedes usar los siguientes comandos o el botón de <b>Menú</b>:\n\n"
            "• 📋 /reporte — Reporte general del día con cambios y pendientes\n"
            "• ⏳ /pendientes — Ver actividades vigentes por entregar\n"
            "• 📊 /calificaciones — Ver tus notas acumuladas de todas las materias\n"
            "• ⚠️ /vencidas — Ver tareas que ya expiraron\n"
            "• 📚 /materia — Elegir una materia y ver todos sus detalles\n"
            "• 🔄 /actualizar — Forzar una consulta a SAIA en tiempo real\n"
            "• 🔑 /cookie — Renovar la sesión de SAIA en 5 segundos\n"
            "• 🌐 /url — Ver tu URL en la nube y enlace para Obsidian"
        )
        self.send_message(chat_id, msg)

    def handle_command_reporte(self, chat_id):
        mid = self.send_message(
            chat_id,
            "📊 <b>Generando reporte diario con detección de novedades...</b>\n"
            "<i>Consultando SAIA en tiempo real...</i>"
        )
        try:
            old_state = dict(self.state) if self.state else {}
            new_state = self.scraper.scrape_all()
            with self.state_lock:
                self.state = new_state

            if not self.state.get("courses") or all(len(c.get("activities", [])) == 0 and c.get("total") == "Sin calificar" for c in self.state.get("courses", [])):
                if not self.scraper.verify_session():
                    msg = (
                        "⚠️ <b>Sesión de SAIA caducada</b>\n\n"
                        "La cookie actual ha expirado en el servidor universitario.\n"
                        "Por favor copia tu nueva cookie de SAIA y envíala con:\n"
                        "<code>/cookie tu_nueva_cookie</code>"
                    )
                    if mid:
                        self.edit_message(chat_id, mid, msg)
                    else:
                        self.send_message(chat_id, msg)
                    return

            alerts = detect_changes(old_state, new_state)
            msg = format_telegram_message_clean(new_state, alerts)
            if mid:
                self.edit_message(chat_id, mid, msg)
            else:
                self.send_message(chat_id, msg)
        except Exception as e:
            err = f"❌ Error generando reporte: {e}"
            if mid:
                self.edit_message(chat_id, mid, err)
            else:
                self.send_message(chat_id, err)

    def handle_command_pendientes(self, chat_id):
        self.ensure_fresh_state()
        lines = ["⏳ <b>ACTIVIDADES PENDIENTES VIGENTES:</b>\n"]
        total = 0
        for c in self.state.get("courses", []):
            cname = c["name"]
            pendientes = [a for a in c.get("activities", []) if not a.get("es_realizada") and not a.get("es_atrasada")]
            if not pendientes:
                continue
            total += len(pendientes)
            lines.append(f"📚 <b>{escape(cname)}</b>")
            for p in pendientes:
                titulo = escape(simplify_activity_title(p["title"]))
                fecha = format_date_compact(p.get("fecha_calendario"), p.get("tiempo"))
                lines.append(f"• <a href=\"{p['link']}\">{titulo}</a> — {fecha}")
            lines.append("")

        if total == 0:
            lines.append("🎉 <b>¡Al día! No tienes actividades pendientes por entregar.</b>")
        else:
            lines.append(f"📊 <b>Total por entregar:</b> {total}")
        self.send_message(chat_id, "\n".join(lines).strip())

    def handle_command_calificaciones(self, chat_id):
        self.ensure_fresh_state()
        lines = ["📊 <b>LIBRETA DE CALIFICACIONES:</b>\n"]
        for c in self.state.get("courses", []):
            cname = escape(c["name"])
            total = c.get("total", "Sin calificar")
            lines.append(f"📘 <b>{cname}</b>")
            lines.append(f"🎯 <b>Total Acumulado:</b> <code>{escape(total)}</code>")

            calificados = [it for it in c.get("grades", []) if it.get("calificacion") != "-"]
            if calificados:
                for it in calificados:
                    tit = escape(simplify_activity_title(it["title"]))
                    nota = escape(it["calificacion"])
                    pond = escape(it.get("ponderacion", "-"))
                    lines.append(f"  • {tit}: <b>{nota}</b> (Pond: {pond})")
            else:
                lines.append("  • <i>Sin evaluaciones calificadas aún</i>")
            lines.append("")
        self.send_message(chat_id, "\n".join(lines).strip())

    def handle_command_vencidas(self, chat_id):
        self.ensure_fresh_state()
        lines = ["⚠️ <b>ACTIVIDADES VENCIDAS (NO ENTREGADAS):</b>\n"]
        total = 0
        for c in self.state.get("courses", []):
            cname = c["name"]
            vencidas = [a for a in c.get("activities", []) if not a.get("es_realizada") and a.get("es_atrasada")]
            if not vencidas:
                continue
            total += len(vencidas)
            lines.append(f"📚 <b>{escape(cname)}</b>")
            for v in vencidas:
                titulo = escape(simplify_activity_title(v["title"]))
                m = re.search(r'(\d+\s*d[ií]as?(?:\s*\d+\s*horas?)?)', v.get("tiempo", ""))
                tiempo_txt = f"hace {m.group(1)}" if m else v.get("tiempo", "vencida")
                lines.append(f"• <a href=\"{v['link']}\">{titulo}</a> — 🔴 <i>{escape(tiempo_txt)}</i>")
            lines.append("")

        if total == 0:
            lines.append("✨ <b>¡Excelente! No tienes actividades atrasadas.</b>")
        else:
            lines.append(f"⚠️ <b>Total vencidas:</b> {total}")
        self.send_message(chat_id, "\n".join(lines).strip())

    def get_materias_keyboard(self):
        keyboard = [
            [{"text": SUBJECT_BUTTONS[0][0], "callback_data": SUBJECT_BUTTONS[0][1]},
             {"text": SUBJECT_BUTTONS[1][0], "callback_data": SUBJECT_BUTTONS[1][1]}],
            [{"text": SUBJECT_BUTTONS[2][0], "callback_data": SUBJECT_BUTTONS[2][1]},
             {"text": SUBJECT_BUTTONS[3][0], "callback_data": SUBJECT_BUTTONS[3][1]}],
            [{"text": SUBJECT_BUTTONS[4][0], "callback_data": SUBJECT_BUTTONS[4][1]},
             {"text": SUBJECT_BUTTONS[5][0], "callback_data": SUBJECT_BUTTONS[5][1]}],
        ]
        return {"inline_keyboard": keyboard}

    def handle_command_materia(self, chat_id):
        msg = "📚 <b>Selecciona la materia que deseas consultar:</b>"
        self.send_message(chat_id, msg, reply_markup=self.get_materias_keyboard())

    def handle_callback_materia(self, chat_id, message_id, callback_data):
        cid = callback_data.replace("mat_", "")
        course = None
        for c in self.state.get("courses", []):
            if c["id"] == cid:
                course = c
                break

        if not course:
            self.edit_message(chat_id, message_id, "❌ Materia no encontrada.")
            return

        cname = escape(course["name"])
        total = escape(course.get("total", "Sin calificar"))

        lines = []
        lines.append(f"📘 <b>{cname}</b> (ID: <code>{cid}</code>)\n")
        lines.append(f"🎯 <b>Nota Acumulada:</b> <code>{total}</code>\n")

        pends = [a for a in course.get("activities", []) if not a.get("es_realizada") and not a.get("es_atrasada")]
        lines.append(f"⏳ <b>Pendientes Activas ({len(pends)}):</b>")
        if pends:
            for p in pends:
                tit = escape(simplify_activity_title(p["title"]))
                f = format_date_compact(p.get("fecha_calendario"), p.get("tiempo"))
                lines.append(f"• <a href=\"{p['link']}\">{tit}</a> — {f}")
        else:
            lines.append("• <i>No hay entregas pendientes activas.</i>")
        lines.append("")

        vencs = [a for a in course.get("activities", []) if not a.get("es_realizada") and a.get("es_atrasada")]
        if vencs:
            lines.append(f"⚠️ <b>Vencidas ({len(vencs)}):</b>")
            for v in vencs:
                tit = escape(simplify_activity_title(v["title"]))
                lines.append(f"• <a href=\"{v['link']}\">{tit}</a> — 🔴 <i>{escape(v.get('tiempo', 'Atrasada'))}</i>")
            lines.append("")

        lines.append(f"🔗 <a href=\"{BASE_URL}/course/view.php?id={cid}\">Aula Virtual</a> · <a href=\"{BASE_URL}/grade/report/user/index.php?id={cid}\">Libro de Notas</a>")

        reply_markup = {
            "inline_keyboard": [
                [{"text": "⬅️ Consultar otra materia", "callback_data": "menu_materias"}]
            ]
        }
        self.edit_message(chat_id, message_id, "\n".join(lines), reply_markup=reply_markup)

    def handle_command_cookie(self, chat_id, text):
        parts = text.strip().split()
        if len(parts) < 2:
            msg = (
                "🔑 <b>Renovación de sesión de SAIA</b>\n\n"
                "💡 <b>Sugerencia rápida:</b>\n"
                "Toca el siguiente comando para copiarlo a tu portapapeles y pega tu cookie al final:\n\n"
                "<code>/cookie </code>\n\n"
                "<i>Ejemplo:</i>\n"
                "<code>/cookie 8aumev6pno5o099bk1v6bpfruf</code>\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "📌 <b>¿Cómo obtener tu cookie en 15 segundos?</b>\n"
                "1. Abre <b>saia2.psm.edu.ve</b> e inicia sesión en tu navegador.\n"
                "2. Presiona <b>F12</b> (o Inspeccionar) ➔ Pestaña <b>Aplicación</b> (o <i>Almacenamiento</i>).\n"
                "3. En el menú izquierdo ve a <b>Cookies</b> ➔ <code>https://saia2.psm.edu.ve</code>.\n"
                "4. Copia el valor de <b>MoodleSession</b> (26 letras/números).\n\n"
                "✨ <i>Atajo: También puedes simplemente pegar la clave aquí directamente en el chat y la detectaré automáticamente.</i>"
            )
            self.send_message(chat_id, msg)
            return

        new_cookie = parts[1].strip()
        self.send_message(chat_id, "🔍 <b>Validando cookie con el servidor de SAIA...</b>")

        if not self.scraper.verify_session(new_cookie):
            self.send_message(
                chat_id,
                "❌ <b>Error:</b> La cookie proporcionada no es válida o ya caducó en SAIA.\n"
                "Inicia sesión en tu navegador y copia el valor exacto de <code>MoodleSession</code>."
            )
            return

        self.scraper.update_cookie(new_cookie)

        cfg = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except Exception:
                pass
        cfg["moodle_session"] = new_cookie
        cfg["telegram_bot_token"] = self.token
        cfg["telegram_chat_id"] = self.chat_id
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

        self.send_message(
            chat_id,
            "✅ <b>¡Sesión de SAIA actualizada con éxito!</b>\n\n"
            "🔄 Sincronizando datos de las materias..."
        )
        self.handle_command_actualizar(chat_id)

    def handle_command_actualizar(self, chat_id):
        mid = self.send_message(
            chat_id,
            "🔄 <b>Conectando con el servidor de SAIA...</b>\n"
            "<i>Consultando las 6 materias y el calendario en tiempo real...</i>"
        )
        t0 = time.time()
        new_state = self.scraper.scrape_all()
        elapsed = time.time() - t0
        with self.state_lock:
            self.state = new_state

        if not self.state.get("courses") or all(len(c.get("activities", [])) == 0 and c.get("total") == "Sin calificar" for c in self.state.get("courses", [])):
            if not self.scraper.verify_session():
                msg = (
                    "⚠️ <b>Sesión de SAIA caducada</b>\n\n"
                    "La cookie actual ha expirado en el servidor universitario.\n"
                    "Por favor copia tu nueva cookie de SAIA y envíala con:\n"
                    "<code>/cookie tu_nueva_cookie</code>"
                )
                if mid:
                    self.edit_message(chat_id, mid, msg)
                else:
                    self.send_message(chat_id, msg)
                return

        lines = [f"✅ <b>¡Sincronizado con éxito en {elapsed:.1f}s!</b>\n\n⏳ <b>ACTIVIDADES PENDIENTES VIGENTES:</b>\n"]
        total = 0
        for c in self.state.get("courses", []):
            cname = c["name"]
            pendientes = [a for a in c.get("activities", []) if not a.get("es_realizada") and not a.get("es_atrasada")]
            if not pendientes:
                continue
            total += len(pendientes)
            lines.append(f"📚 <b>{escape(cname)}</b>")
            for p in pendientes:
                titulo = escape(simplify_activity_title(p["title"]))
                fecha = format_date_compact(p.get("fecha_calendario"), p.get("tiempo"))
                lines.append(f"• <a href=\"{p['link']}\">{titulo}</a> — {fecha}")
            lines.append("")

        if total == 0:
            lines.append("🎉 <b>¡Al día! No tienes actividades pendientes por entregar.</b>")
        else:
            lines.append(f"📊 <b>Total por entregar:</b> {total}")

        res_text = "\n".join(lines).strip()
        if mid:
            self.edit_message(chat_id, mid, res_text)
        else:
            self.send_message(chat_id, res_text)

    def handle_command_url(self, chat_id):
        render_url = os.getenv("RENDER_EXTERNAL_URL")
        if render_url:
            msg = (
                f"🌐 <b>Tu URL en Render es:</b>\n<code>{render_url}</code>\n\n"
                f"<i>Ruta de sincronización para Obsidian:</i>\n"
                f"<code>{render_url.rstrip('/')}/get-cookie?token={self.token}</code>"
            )
        else:
            msg = (
                "ℹ️ <b>Modo local detectado.</b>\n"
                "Para obtener tu URL en la nube, ejecuta este comando en el bot de Render o cópiala del dashboard de render.com."
            )
        self.send_message(chat_id, msg)

    def process_updates(self):
        url = f"{self.api_url}/getUpdates?offset={self.last_update_id + 1}&timeout=15"
        try:
            res = self.tg_client.get(url)
            if res.status_code != 200:
                return
            data = res.json()
            for update in data.get("result", []):
                self.last_update_id = update["update_id"]

                if "callback_query" in update:
                    cb = update["callback_query"]
                    cb_id = cb["id"]
                    cb_data = cb.get("data", "")
                    cid = str(cb["message"]["chat"]["id"])
                    mid = cb["message"]["message_id"]

                    self.answer_callback(cb_id)
                    print(f"[Botón presionado]: {cb_data}", flush=True)

                    if cb_data.startswith("mat_"):
                        self.handle_callback_materia(cid, mid, cb_data)
                    elif cb_data == "menu_materias":
                        msg = "📚 <b>Selecciona la materia que deseas consultar:</b>"
                        self.edit_message(cid, mid, msg, reply_markup=self.get_materias_keyboard())

                elif "message" in update and "text" in update["message"]:
                    text = update["message"]["text"].strip()
                    cid = str(update["message"]["chat"]["id"])
                    print(f"[Comando]: {text}", flush=True)

                    cmd = text.split()[0].lower()
                    if cmd in ["/start", "/help"]:
                        self.handle_command_start(cid)
                    elif cmd == "/pendientes":
                        self.handle_command_pendientes(cid)
                    elif cmd == "/calificaciones":
                        self.handle_command_calificaciones(cid)
                    elif cmd == "/vencidas":
                        self.handle_command_vencidas(cid)
                    elif cmd == "/materia":
                        self.handle_command_materia(cid)
                    elif cmd == "/actualizar":
                        self.handle_command_actualizar(cid)
                    elif cmd == "/reporte":
                        self.handle_command_reporte(cid)
                    elif cmd == "/cookie":
                        self.handle_command_cookie(cid, text)
                    elif cmd == "/url":
                        self.handle_command_url(cid)
                    elif re.fullmatch(r'[a-z0-9]{20,35}', text):
                        self.send_message(cid, "🔍 <i>Detecté una cookie de SAIA. Validando tu nueva sesión...</i>")
                        self.handle_command_cookie(cid, f"/cookie {text}")
        except Exception as e:
            time.sleep(1)

    def run(self):
        print("="*60, flush=True)
        print("  BOT INTERACTIVO ULTRA-RÁPIDO INICIADO", flush=True)
        print("  Heartbeat activo cada 25-35 min con detección de nuevas actividades", flush=True)
        print("  Programador diario 8:00 AM / 8:00 PM activo", flush=True)
        print("="*60, flush=True)

        while True:
            self.process_updates()
            time.sleep(0.1)

if __name__ == "__main__":
    bot = InteractiveBot()
    bot.run()
