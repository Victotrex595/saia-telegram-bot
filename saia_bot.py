import os
import re
import sys
import json
from datetime import datetime, timezone, timedelta
from html import escape, unescape
import httpx

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# Configuracion base
COURSE_IDS = ["27752", "27753", "27604", "27611", "27755", "26639"]
BASE_URL = "https://saia2.psm.edu.ve"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "saia_state.json")

def get_env_or_config(key, default=None):
    val = os.getenv(key)
    if val:
        return val.strip()
    local_cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if os.path.exists(local_cfg):
        try:
            with open(local_cfg, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get(key.lower(), default)
        except Exception:
            pass
    return default

MOODLE_SESSION = get_env_or_config("MOODLE_SESSION", "a98fbkev364chb1s4d9qfv0pir")
TELEGRAM_BOT_TOKEN = get_env_or_config("TELEGRAM_BOT_TOKEN", "8916730385:AAEvY26U3Mkc5vDq2XBgJNXpbJAU6Ej-e4o")
TELEGRAM_CHAT_ID = get_env_or_config("TELEGRAM_CHAT_ID", "1452296186")

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

def send_telegram_message(token, chat_id, text_html):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = []
    if len(text_html) <= 4000:
        chunks.append(text_html)
    else:
        parts = text_html.split("\n\n")
        current_chunk = ""
        for p in parts:
            if len(current_chunk) + len(p) + 2 > 3800:
                chunks.append(current_chunk)
                current_chunk = p
            else:
                current_chunk = (current_chunk + "\n\n" + p).strip()
        if current_chunk:
            chunks.append(current_chunk)

    with httpx.Client(timeout=15.0) as client:
        for ch in chunks:
            res = client.post(url, json={
                "chat_id": chat_id,
                "text": ch,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            })
            if res.status_code != 200:
                print(f"Error enviando mensaje a Telegram: {res.status_code} - {res.text}")
            else:
                print("Mensaje enviado exitosamente a Telegram.")

class SaiaScraper:
    def __init__(self, session_cookie):
        self.session_cookie = session_cookie
        self.client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            cookies={"MoodleSession": session_cookie},
            follow_redirects=False,
            timeout=25.0
        )

    def verify(self):
        try:
            r = self.client.get(f"{BASE_URL}/my/")
            if r.status_code == 200 and "login" not in r.text.lower()[:300]:
                return True
            loc = r.headers.get("location", "").lower()
            if r.status_code == 303 or "login" in loc:
                return False
            return True
        except Exception:
            return False

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
                print(f"Error consultando calendario ({view_param}): {e}")
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
            print(f"Error en notas {cid}: {e}")
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
            print(f"Error cargando curso {cid}: {e}")

        # 1b. Pestañas / secciones separadas del curso (&section=1, &section=2, etc.)
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

        # 2. Índices nativos de Moodle
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

        activities = []
        default_forums = ["avisos", "cartelera informativa", "café virtual", "cafe virtual", "alguna duda", "foro de dudas", "dudas", "preguntas al profesor"]

        for m_id, act_info in discovered_links.items():
            mod_type = act_info["type"]
            title = act_info["title"]
            link = act_info["link"]

            for sfx in ["Tarea", "Cuestionario", "Foro", "Taller"]:
                if title.endswith(sfx):
                    title = title[:-len(sfx)].strip()

            if mod_type == "forum":
                t_lower = title.lower()
                is_default_forum = any(df in t_lower for df in default_forums)
                is_in_gradebook = any(gi.get("act_id") == m_id for gi in grade_items)
                if is_default_forum and not is_in_gradebook:
                    continue

            is_graded = False
            for gi in grade_items:
                if gi.get("act_id") == m_id and gi.get("is_graded"):
                    is_graded = True
                    break

            detail = self.check_activity_detail(link, mod_type, is_graded=is_graded)

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

            if not cal_deadline:
                norm_act = re.sub(r'[^a-z0-9]', '', simplify_activity_title(title).lower())
                for ev in cal_events:
                    norm_ev = re.sub(r'[^a-z0-9]', '', simplify_activity_title(ev.get("clean_title", "")).lower())
                    if norm_act and norm_ev and (norm_act == norm_ev):
                        if ev.get("event_type") in ["close", "due"]:
                            cal_deadline = ev["date"]
                            break

            fecha_final = detail.get("fecha_entrega") or cal_deadline or cal_open

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

        if cur["total"] != old.get("total") and cur["total"] != "Sin calificar":
            alerts.append(f"🎯 <b>Nota final en {escape(cname)}:</b> <code>{escape(cur['total'])}</code>")

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

def main():
    print("Iniciando revision de SAIA para Telegram...")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[ERROR] Falta configurar TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID.")
        sys.exit(1)

    scraper = SaiaScraper(MOODLE_SESSION)
    if not scraper.verify():
        msg = (
            "⚠️ <b>ALERTA SAIA:</b> La sesión de <code>MoodleSession</code> ha caducado en la universidad.\n\n"
            "Para renovarla de inmediato, envía a tu bot en Telegram:\n"
            "<code>/cookie tu_nueva_cookie</code>"
        )
        send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg)
        print("[ERROR] Sesion caducada.")
        sys.exit(1)

    cal_events = scraper.get_calendar()

    courses_data = []
    for cid in COURSE_IDS:
        cname_raw, total, grades = scraper.get_course_grades(cid)
        cname = sanitize_course_name(cname_raw)
        acts = scraper.get_course_activities(cid, cal_events.get(cid, []), grades)
        courses_data.append({
            "id": cid,
            "name": cname,
            "total": total,
            "grades": grades,
            "activities": acts
        })

    current_state = {
        "timestamp": datetime.now().isoformat(),
        "courses": courses_data
    }

    old_state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                old_state = json.load(f)
        except Exception:
            pass

    alerts = detect_changes(old_state, current_state)
    mensaje = format_telegram_message_clean(current_state, alerts)
    send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, mensaje)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(current_state, f, ensure_ascii=False, indent=2)
    print("[OK] Estado actualizado y guardado en saia_state.json.")

if __name__ == "__main__":
    main()
