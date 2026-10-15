import os
import re
import sys
import json
from datetime import datetime, timezone, timedelta
from html import escape, unescape
import httpx

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

def clean_text(text):
    if not text:
        return ""
    text = unescape(re.sub(r"<[^>]+>", " ", text))
    text = text.replace("\xa0", " ")
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
        self.client = httpx.Client(
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            },
            cookies={"MoodleSession": session_cookie},
            follow_redirects=True,
            timeout=25.0
        )

    def verify(self):
        try:
            res = self.client.get(f"{BASE_URL}/my/")
            return "login" not in str(res.url) and "login.php" not in res.text
        except Exception:
            return False

    def get_calendar(self):
        url = f"{BASE_URL}/calendar/view.php?view=upcoming"
        events_by_course = {}
        try:
            res = self.client.get(url)
            if res.status_code != 200:
                return {}
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

                if cid not in events_by_course:
                    events_by_course[cid] = []
                events_by_course[cid].append({"title": title, "date": date_str, "link": link})
        except Exception as e:
            print(f"Error consultando calendario: {e}")
        return events_by_course

    def get_course_grades(self, cid):
        url = f"{BASE_URL}/grade/report/user/index.php?id={cid}"
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

    def get_course_activities(self, cid, cal_events):
        url = f"{BASE_URL}/course/view.php?id={cid}"
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
            
            # Formato directo: • [Enlace Título] — [Fecha]
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
        msg = "⚠️ <b>ALERTA SAIA:</b> La sesión de <code>MoodleSession</code> ha caducado. Por favor actualízala en los Secrets para reanudar el monitoreo."
        send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg)
        print("[ERROR] Sesion caducada.")
        sys.exit(1)

    cal_events = scraper.get_calendar()
    
    courses_data = []
    for cid in COURSE_IDS:
        cname_raw, total, grades = scraper.get_course_grades(cid)
        cname = sanitize_course_name(cname_raw)
        acts = scraper.get_course_activities(cid, cal_events.get(cid, []))
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
