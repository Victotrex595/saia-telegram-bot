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

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

import urllib.parse

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

# Iniciar servidor web de salud en segundo plano para Render / Koyeb
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

def format_date_compact(date_str, tiempo_str):
    if date_str:
        m = re.search(r'(\d+)\s+(?:de\s+)?([a-zA-Z]{3})[a-zA-Z]*(?:[^\d]*\d{4})?(?:[^\d]*(\d{2}:\d{2}))?', date_str, re.I)
        if m:
            dia = m.group(1)
            mes = m.group(2).lower()
            hora = f", {m.group(3)}" if m.group(3) else ""
            return f"📅 <b>{dia} {mes}{hora}</b>"
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

    # Alertas o Sin Cambios
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
        # Filtrar: SOLO actividades NO realizadas y NO vencidas/atrasadas
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
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
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
        # Reusar el cliente existente para aprovechar Keep-Alive y no pagar coste de handshake SSL
        c = self.client if (cookie is None) else httpx.Client(
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            cookies={"MoodleSession": chk_cookie},
            follow_redirects=False,
            timeout=25.0
        )
        should_close = (cookie is not None)
        try:
            r = c.get(f"{BASE_URL}/my/")
            # 200 OK: Sesión perfectamente viva
            if r.status_code == 200 and "login" not in r.text.lower()[:300]:
                return True
            # 303 Redirect a login: Sesión definitivamente caducada
            loc = r.headers.get("location", "").lower()
            if r.status_code == 303 or "login" in loc:
                return False
            return True
        except (httpx.TimeoutException, httpx.NetworkError):
            # Si solo hubo lag o lentitud internacional con el servidor del PSM, NO marcar como caducada
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
        cal_events = self.get_calendar()
        
        def scrape_single_course(cid):
            cname_raw, total, grades = self.get_course_grades(cid)
            cname = sanitize_course_name(cname_raw)
            acts = self.get_course_activities(cid, cal_events.get(cid, []))
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
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return state

    def get_calendar(self):
        url = f"{BASE_URL}/calendar/view.php?view=upcoming"
        events = {}
        try:
            res = self.client.get(url)
            if res.status_code == 200:
                blocks = re.findall(r'<div[^>]*data-type=\"event\"[^>]*data-course-id=\"(\d+)\"[^>]*>(.*?)</div>\s*</div>\s*</div>', res.text, re.S)
                for cid, block in blocks:
                    title_m = re.search(r'data-event-title=\"([^\"]*)\"', block)
                    if not title_m:
                        title_m = re.search(r'<h3[^>]*class=\"[^\"]*name[^\"]*\"[^>]*>(.*?)</h3>', block, re.S)
                    title = clean_text(title_m.group(1)) if title_m else "Evento"
                    date_m = re.search(r'<span[^>]*class=\"[^\"]*date\b[^\"]*\"[^>]*>(.*?)</span>', block, re.S)
                    date_str = clean_text(date_m.group(1)) if date_m else ""
                    link_m = re.search(r'<a[^>]*href=\"(https://saia2\.psm\.edu\.ve/mod/(?:assign|quiz)/view\.php\?id=\d+[^\"]*)\"', block)
                    link = link_m.group(1).replace("&amp;", "&") if link_m else ""
                    if cid not in events:
                        events[cid] = []
                    events[cid].append({"title": title, "date": date_str, "link": link})
        except Exception as e:
            print(f"Error consultando calendario: {e}", flush=True)
        return events

    def get_course_grades(self, cid):
        url = f"{BASE_URL}/grade/report/user/index.php?id={cid}"
        try:
            res = self.client.get(url)
            if res.status_code != 200:
                return f"Curso {cid}", "Sin calificar", []
            html = res.text
            h1_m = re.search(r"class=\"page-header-headings\"[^>]*>.*?<h1>(.*?)</h1>", html, re.S)
            if not h1_m:
                h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
            cname = clean_text(h1_m.group(1)) if h1_m else f"Curso {cid}"

            items = []
            course_total = "Sin calificar"
            table_m = re.search(r"<table[^>]*class=\"[^\"]*user-grade[^\"]*\"[^>]*>(.*?)</table>", html, re.S)
            if table_m:
                rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_m.group(1), re.S)
                for r in rows:
                    r_clean = re.sub(r'<div[^>]*class=\"[^\"]*action-menu[^\"]*\"[^>]*>.*?</div>', '', r, flags=re.S)
                    if "total" in r_clean.lower() and "itemname" in r_clean:
                        tds = re.findall(r"<td[^>]*>(.*?)</td>", r_clean, re.S)
                        clean_tds = [clean_text(td) for td in tds]
                        if len(clean_tds) >= 3:
                            nota = clean_tds[1] if clean_tds[1] and clean_tds[1] != "-" else "Sin calificar"
                            rango = clean_tds[2] if clean_tds[2] else ""
                            course_total = f"{nota} / {rango.split('–')[-1].split('-')[-1].strip()}" if (rango and nota != "Sin calificar") else nota
                    item_m = re.search(r"<th[^>]*class=\"[^\"]*item\b[^\"]*\"[^>]*>(.*?)</th>", r_clean, re.S)
                    if item_m:
                        item_title = clean_text(item_m.group(1))
                        for prefix in ['Tarea', 'Cuestionario', 'Foro']:
                            if item_title.startswith(prefix):
                                item_title = item_title[len(prefix):].strip()
                        tds = re.findall(r"<td[^>]*>(.*?)</td>", r_clean, re.S)
                        clean_tds = [clean_text(td) for td in tds]
                        pond = clean_tds[0] if len(clean_tds) > 0 else "-"
                        calif = clean_tds[1] if len(clean_tds) > 1 else "-"
                        items.append({"title": item_title, "ponderacion": pond, "calificacion": calif})
            return cname, course_total, items
        except Exception as e:
            print(f"Error en notas {cid}: {e}", flush=True)
            return f"Curso {cid}", "Sin calificar", []

    def get_course_activities(self, cid, cal_events):
        url = f"{BASE_URL}/course/view.php?id={cid}"
        try:
            res = self.client.get(url)
            if res.status_code != 200:
                return []
            matches = re.findall(r'<a[^>]*href=\"(https://saia2\.psm\.edu\.ve/mod/(assign|quiz)/view\.php\?id=\d+)\"[^>]*>(.*?)</a>', res.text, re.S)
            activities = []
            seen = set()
            for link, mod_type, raw_title in matches:
                if link in seen:
                    continue
                seen.add(link)
                title = clean_text(raw_title)
                for suffix in ['Tarea', 'Cuestionario']:
                    if title.endswith(suffix):
                        title = title[:-len(suffix)].strip()
                detail = self.check_activity_detail(link, mod_type)
                
                # Extraer ID numérico de módulo de la actividad (ej: 2022447)
                act_id_m = re.search(r'[?&]id=(\d+)', link)
                act_id = act_id_m.group(1) if act_id_m else ""

                matched_date = None
                for ev in cal_events:
                    ev_link = ev.get("link", "")
                    ev_id_m = re.search(r'[?&]id=(\d+)', ev_link)
                    ev_id = ev_id_m.group(1) if ev_id_m else ""
                    
                    # 1. Coincidencia EXACTA por ID de módulo en el enlace
                    if act_id and ev_id and act_id == ev_id:
                        matched_date = ev["date"]
                        break
                    
                    # 2. Coincidencia por URL completa
                    if link and ev_link and link == ev_link:
                        matched_date = ev["date"]
                        break

                    # 3. Coincidencia estricta por título NORMALIZADO (evita replicación por palabras comunes)
                    clean_act = re.sub(r'[^a-z0-9]', '', simplify_activity_title(title).lower())
                    clean_ev = re.sub(r'[^a-z0-9]', '', simplify_activity_title(ev.get("title", "")).lower())
                    if clean_act and clean_ev and (clean_act == clean_ev or clean_act in clean_ev):
                        matched_date = ev["date"]
                        break

                # Preferir la fecha obtenida directamente de la actividad; de lo contrario, la del calendario
                fecha_final = detail.get("fecha_entrega") or matched_date

                activities.append({
                    "title": title,
                    "type": "Tarea" if mod_type == "assign" else "Cuestionario",
                    "link": link,
                    "fecha_calendario": fecha_final,
                    **detail
                })
            return activities
        except Exception as e:
            print(f"Error en actividades {cid}: {e}", flush=True)
            return []

    def check_activity_detail(self, link, mod_type):
        try:
            res = self.client.get(link)
            if res.status_code != 200:
                return {"estado": "Sin datos", "tiempo": "-", "fecha_entrega": None, "es_realizada": False, "es_atrasada": False}
            html = res.text
            
            if mod_type == "assign":
                entrega_m = re.search(r'<th[^>]*>Estado de la entrega</th>\s*<td[^>]*>(.*?)</td>', html, re.S | re.I)
                calif_m = re.search(r'<th[^>]*>Estado de la calificaci[^\"]*</th>\s*<td[^>]*>(.*?)</td>', html, re.S | re.I)
                tiempo_m = re.search(r'<th[^>]*>Tiempo restante</th>\s*<td[^>]*>(.*?)</td>', html, re.S | re.I)
                fecha_m = re.search(r'<th[^>]*>Fecha de entrega</th>\s*<td[^>]*>(.*?)</td>', html, re.S | re.I)
                
                estado = clean_text(entrega_m.group(1)) if entrega_m else "Sin envíos"
                calif_est = clean_text(calif_m.group(1)) if calif_m else "-"
                tiempo = clean_text(tiempo_m.group(1)) if tiempo_m else "-"
                fecha_entrega = clean_text(fecha_m.group(1)) if fecha_m else None
                
                if not fecha_entrega:
                    f_alt = re.search(r'(?:Fecha de entrega|Cierre)[^\.\n<]*?:\s*([^\n<]+)', html, re.I)
                    if f_alt:
                        fecha_entrega = clean_text(f_alt.group(1))

                es_realizada = any(x in estado.lower() for x in ["enviado para calificar", "entregado"]) or "calificado" in calif_est.lower()
                es_atrasada = "retrasada" in tiempo.lower() or "overdue" in tiempo.lower()
                return {
                    "estado": estado,
                    "tiempo": tiempo,
                    "fecha_entrega": fecha_entrega,
                    "es_realizada": es_realizada,
                    "es_atrasada": es_atrasada
                }
            else:
                # Cuestionario (quiz)
                html_lower = html.lower()
                es_realizada = (
                    "reintentar el cuestionario" in html_lower
                    or "resumen de sus intentos anteriores" in html_lower
                    or "calificación más alta" in html_lower
                    or ("revisión" in html_lower and "finalizado" in html_lower)
                )

                fecha_cierre = None
                es_atrasada = False

                # 1. Comprobar si ya cerró ("Cerró:", "se cerró el", "cerrado el")
                cierre_pasado_m = re.search(r'(?:Cerró|se cerró el|cerrado el)[^\.\n<]*?:\s*([^\n<]+)', html, re.I)
                if not cierre_pasado_m:
                    cierre_pasado_m = re.search(r'Este cuestionario se cerr[oó] el\s*([^<\.]+)', html, re.I)

                if cierre_pasado_m:
                    fecha_cierre = clean_text(cierre_pasado_m.group(1))
                    if not es_realizada:
                        es_atrasada = True
                    tiempo = f"Cerró: {fecha_cierre}"
                else:
                    # 2. Comprobar si cerrará en el futuro ("Cierra:", "se cerrará el", "Cierre:")
                    cierre_futuro_m = re.search(r'(?:Cierra|se cerrar[aá] el|Cierre)[^\.\n<]*?:\s*([^\n<]+)', html, re.I)
                    if not cierre_futuro_m:
                        cierre_futuro_m = re.search(r'Este cuestionario se cerrar[aá] el\s*([^<\.]+)', html, re.I)

                    if cierre_futuro_m:
                        fecha_cierre = clean_text(cierre_futuro_m.group(1))
                        es_atrasada = False
                        tiempo = f"Cierra: {fecha_cierre}"
                    else:
                        if "este cuestionario está cerrado" in html_lower or "cuestionario cerrado" in html_lower:
                            if not es_realizada:
                                es_atrasada = True
                            tiempo = "Cuestionario cerrado"
                        else:
                            tiempo = "-"

                estado = "Realizado" if es_realizada else ("Vencido" if es_atrasada else "Pendiente")
                return {
                    "estado": estado,
                    "tiempo": tiempo,
                    "fecha_entrega": fecha_cierre,
                    "es_realizada": es_realizada,
                    "es_atrasada": es_atrasada
                }
        except Exception:
            return {"estado": "Error", "tiempo": "-", "fecha_entrega": None, "es_realizada": False, "es_atrasada": False}

class InteractiveBot:
    def __init__(self):
        global GLOBAL_BOT
        GLOBAL_BOT = self
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.scraper = SaiaEngine(MOODLE_SESSION)
        self.last_update_id = 0
        
        # Cliente persistente con HTTP Keep-Alive
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
            self.state = new_state
            
            # Verificar si expiró la sesión
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
                    # 8:00 AM (08:00) y 8:00 PM (20:00) hora de Venezuela
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
            # Pequeña espera inicial de 2 minutos antes del primer latido
            time.sleep(120)
            while True:
                # Intervalo aleatorio (Jitter humano) entre 22 y 38 minutos con segundos impredecibles
                wait_seconds = random.randint(22 * 60, 38 * 60) + random.randint(5, 55)
                mins = wait_seconds / 60.0
                try:
                    alive = self.scraper.verify_session()
                    now_str = datetime.now().strftime("%H:%M:%S")
                    if alive:
                        print(f"[{now_str}] [Heartbeat] Sesión SAIA activa y refrescada (200 OK). Próximo en ~{mins:.1f} min.", flush=True)
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
                    return
            except Exception:
                pass
        try:
            self.state = self.scraper.scrape_all()
        except Exception as e:
            print(f"Error cargando estado inicial: {e}", flush=True)
            self.state = {"timestamp": datetime.now().isoformat(), "courses": []}

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
        
        # Guardar en config.json
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
        self.state = self.scraper.scrape_all()
        elapsed = time.time() - t0
        
        # Verificar si vino vacío por sesión caducada
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
                
                # Clic en Botón (Callback Query)
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
                        
                # Mensaje de texto / comando
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
        print("  Heartbeat activo cada 20 min | Comando /cookie habilitado", flush=True)
        print("="*60, flush=True)
        
        while True:
            self.process_updates()
            time.sleep(0.1)

if __name__ == "__main__":
    bot = InteractiveBot()
    bot.run()
