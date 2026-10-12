# 🤖 Bot de Notificaciones SAIA para Telegram (GitHub Actions)

Este repositorio ejecuta un bot en la nube (100% gratuito con **GitHub Actions**) que monitorea periódicamente la plataforma **SAIA** y envía un reporte detallado con las actividades pendientes y alertas de cambios a tu cuenta de **Telegram**.

---

## ⏰ Horarios de Notificación

El bot está configurado para ejecutarse automáticamente dos veces al día:
* 🌅 **8:00 AM** (Hora de Venezuela / UTC-4)
* 🌙 **8:00 PM** (Hora de Venezuela / UTC-4)

También puedes presionar el botón **"Run workflow"** en la pestaña **Actions** para recibir un reporte al instante en cualquier momento.

---

## 📋 ¿Qué incluye cada notificación?

1. **🚨 Alertas y Cambios:**
   - Nuevas tareas publicadas por los profesores.
   - Nuevas notas registradas en el libro de calificaciones.
   - Cambios de ponderación o fechas de entrega.
   - *Si no hay cambios*, muestra el aviso: `ℹ️ Sin cambios ni novedades en SAIA desde la última revisión.`
2. **⏳ Lista Exclusiva de Actividades Pendientes:**
   - Agrupadas por materia.
   - Identificación de entregas atrasadas (`⚠️`) y próximas entregas con su fecha límite.
   - Enlace directo con un clic a la página de entrega de SAIA.

---

## 🚀 Guía de Instalación y Despliegue en GitHub

### Paso 1: Crear el repositorio en GitHub
1. Entra a tu cuenta en [github.com/new](https://github.com/new).
2. Nómbralo (por ejemplo: `saia-telegram-bot`).
3. **IMPORTANTE:** Selecciona la opción **Private** (Privado) para proteger tu información.
4. Haz clic en **Create repository**.

### Paso 2: Subir los archivos
Sube todos los archivos de esta carpeta a tu repositorio:
- `saia_bot.py`
- `requirements.txt`
- `.github/workflows/saia_schedule.yml`

*(Puedes subirlos usando Git o directamente desde la web de GitHub arrastrando los archivos).*

### Paso 3: Configurar los Secretos (Credenciales)
1. En tu repositorio de GitHub, ve a **Settings** (Ajustes) ➔ Menú izquierdo **Secrets and variables** ➔ **Actions**.
2. Pulsa en **New repository secret** y añade los siguientes 3 secretos:

| Nombre del Secreto | Valor |
| :--- | :--- |
| `MOODLE_SESSION` | Tu cookie `MoodleSession` de SAIA |
| `TELEGRAM_BOT_TOKEN` | El token que te dio `@BotFather` |
| `TELEGRAM_CHAT_ID` | Tu Chat ID personal de Telegram |

### Paso 4: Habilitar permisos de escritura en GitHub Actions
Para que el bot pueda guardar el archivo de comparación (`saia_state.json`):
1. En tu repositorio, ve a **Settings** ➔ **Actions** ➔ **General**.
2. Baja hasta **Workflow permissions**.
3. Selecciona **Read and write permissions**.
4. Pulsa **Save**.

### Paso 5: Probar el Bot
1. Ve a la pestaña **Actions** en tu repositorio.
2. En la lista izquierda, haz clic en **Notificador SAIA Telegram**.
3. Pulsa el botón **Run workflow** ➔ **Run workflow**.
4. En menos de un minuto recibirás la notificación completa en tu Telegram.
