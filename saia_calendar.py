"""
saia_calendar.py
Módulo generador de feed iCalendar (.ics) para el bot de SAIA.
Convierte las actividades de saia_state.json en eventos de calendario compatibles
con Google Calendar, Apple Calendar y Outlook.
"""

import os
import re
import json
import hashlib
from datetime import datetime, timezone, timedelta

TZ_VZLA = timezone(timedelta(hours=-4))

MESES = {
    "enero": 1, "ene": 1, "feb": 2, "febrero": 2, "mar": 3, "marzo": 3,
    "abr": 4, "abril": 4, "may": 5, "mayo": 5, "jun": 6, "junio": 6,
    "jul": 7, "julio": 7, "ago": 8, "agosto": 8, "sep": 9, "sept": 9, "septiembre": 9,
    "oct": 10, "octubre": 10, "nov": 11, "noviembre": 11, "dic": 12, "diciembre": 12
}

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
    now = datetime.now(TZ_VZLA)
    year = int(year_str) if year_str else now.year
    hour = int(m.group(4)) if m.group(4) else 23
    minute = int(m.group(5)) if m.group(5) else 59
    try:
        return datetime(year, month, day, hour, minute, tzinfo=TZ_VZLA)
    except Exception:
        return None

def parse_relative_time(tiempo_str, ref_dt=None):
    if not tiempo_str or tiempo_str == "-" or tiempo_str.startswith("//"):
        return None
    ref_dt = ref_dt or datetime.now(TZ_VZLA)
    
    # Caso restante: "5 días 2 horas restante"
    m_rest = re.search(r'(\d+)\s*d[ií]as?(?:[^\d]*(\d+)\s*horas?)?.*restante', tiempo_str, re.I)
    if m_rest:
        days = int(m_rest.group(1))
        hours = int(m_rest.group(2)) if m_rest.group(2) else 0
        return ref_dt + timedelta(days=days, hours=hours)
        
    m_rest_hours = re.search(r'(\d+)\s*horas?.*restante', tiempo_str, re.I)
    if m_rest_hours:
        hours = int(m_rest_hours.group(1))
        return ref_dt + timedelta(hours=hours)

    # Caso retrasada: "La Tarea está retrasada por: 2 días 20 horas"
    m_past = re.search(r'retrasada por:\s*(\d+)\s*d[ií]as?(?:[^\d]*(\d+)\s*horas?)?', tiempo_str, re.I)
    if m_past:
        days = int(m_past.group(1))
        hours = int(m_past.group(2)) if m_past.group(2) else 0
        return ref_dt - timedelta(days=days, hours=hours)

    return None

def format_ical_dt(dt):
    # Formato UTC: YYYYMMDDTHHMMSSZ
    utc_dt = dt.astimezone(timezone.utc)
    return utc_dt.strftime("%Y%m%dT%H%M%SZ")

def clean_summary_title(title):
    t = re.sub(r'I+ERA\s+ACTIVIDAD\s+EVALUATIVA\s+CORRESPONDIENTE\s+AL\s+\w+\s+CORTE\s*[\.\-:]*\s*', '', title, flags=re.I)
    t = re.sub(r'ACTIVIDAD\s+EVALUATIVA\s*[\.\-:]*\s*', '', t, flags=re.I)
    t = re.sub(r'\s+', ' ', t).strip(' .:-')
    return t

def escape_ical_text(text):
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    text = text.replace(";", "\\;")
    text = text.replace(",", "\\,")
    text = text.replace("\n", "\\n")
    return text

def generate_ics_content(state_data):
    """
    Genera el contenido RFC 5545 iCalendar a partir del JSON de saia_state.
    """
    now = datetime.now(timezone.utc)
    now_str = now.strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SAIA Moodle Telegram Bot//Actividades PSM//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:SAIA (PSM) - Entregas y Actividades",
        "X-WR-CALDESC:Calendario sincronizado automáticamente con la plataforma SAIA del Politécnico Santiago Mariño.",
        "X-WR-TIMEZONE:America/Caracas",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]

    # Timestamp del estado para calcular fechas relativas con precisión
    state_ts_raw = state_data.get("timestamp")
    ref_dt = None
    if state_ts_raw:
        try:
            ref_dt = datetime.fromisoformat(state_ts_raw)
            if ref_dt.tzinfo is None:
                ref_dt = ref_dt.replace(tzinfo=TZ_VZLA)
        except Exception:
            ref_dt = datetime.now(TZ_VZLA)
    else:
        ref_dt = datetime.now(TZ_VZLA)

    events_count = 0
    courses = state_data.get("courses", [])

    for course in courses:
        cname = course.get("name", "Materia").strip()
        # Nombre corto de la materia para el título
        short_cname = cname.split("/")[0].strip()
        activities = course.get("activities", [])

        for act in activities:
            title = act.get("title", "Actividad").strip()
            clean_t = clean_summary_title(title)
            link = act.get("link", "")
            mod_type = act.get("type", "Tarea")
            es_realizada = act.get("es_realizada", False)
            es_atrasada = act.get("es_atrasada", False)
            estado = act.get("estado", "Sin datos")
            tiempo = act.get("tiempo", "-")
            fecha_cal = act.get("fecha_calendario")

            # Determinar fecha límite del evento
            due_dt = parse_spanish_date(fecha_cal)
            if not due_dt:
                due_dt = parse_relative_time(tiempo, ref_dt=ref_dt)

            if not due_dt:
                # Si no tiene ninguna fecha detectable, no podemos crear un evento temporal
                continue

            # Generar UID estable basado en link o ID de actividad
            act_id_m = re.search(r'id=(\d+)', link)
            act_id = act_id_m.group(1) if act_id_m else hashlib.md5(f"{cname}_{title}".encode()).hexdigest()[:12]
            uid = f"saia-{act_id}@psm.edu.ve"

            # Prefijo e iconos según estado
            if es_realizada:
                icon = "✅"
                status_prefix = "[Entregada]"
            elif es_atrasada:
                icon = "⚠️"
                status_prefix = "[Atrasada]"
            else:
                icon = "⏳" if "cuestionario" in mod_type.lower() else "📝"
                status_prefix = "[Pendiente]"

            summary = f"{icon} {status_prefix} [{short_cname}] {clean_t}"
            
            # Duración del evento: 30 minutos antes de la hora límite
            start_dt = due_dt - timedelta(minutes=30)
            dt_start_str = format_ical_dt(start_dt)
            dt_end_str = format_ical_dt(due_dt)

            desc = (
                f"Materia: {cname}\\n"
                f"Actividad: {title}\\n"
                f"Tipo: {mod_type}\\n"
                f"Estado: {estado}\\n"
                f"Tiempo: {tiempo}\\n"
                f"Enlace SAIA: {link}"
            )

            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{now_str}",
                f"DTSTART:{dt_start_str}",
                f"DTEND:{dt_end_str}",
                f"SUMMARY:{escape_ical_text(summary)}",
                f"DESCRIPTION:{desc}",
                f"URL:{link}",
                "STATUS:CONFIRMED",
                "TRANSP:TRANSPARENT",  # No bloquea tu calendario como "ocupado"
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:Entrega próxima: {escape_ical_text(clean_t)}",
                "TRIGGER:-P1D",  # Alarma 1 día antes
                "END:VALARM",
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:Entrega en 2 horas: {escape_ical_text(clean_t)}",
                "TRIGGER:-PT2H",  # Alarma 2 horas antes
                "END:VALARM",
                "END:VEVENT"
            ])
            events_count += 1

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines), events_count

def export_local_ics(state_file_path=None, output_ics_path=None):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    state_file = state_file_path or os.path.join(script_dir, "saia_state.json")
    output_file = output_ics_path or os.path.join(script_dir, "saia_calendario.ics")

    if not os.path.exists(state_file):
        print(f"[ERROR] No se encontró el archivo: {state_file}")
        return False

    with open(state_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    ics_content, count = generate_ics_content(data)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(ics_content)

    print(f"[OK] Archivo iCalendar generado con {count} actividades:")
    print(f" -> {output_file}")
    return True

if __name__ == "__main__":
    export_local_ics()
