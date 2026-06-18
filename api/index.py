"""
Parroquia App — API de Licencias
Desplegada en Vercel (serverless).
Base de datos: Supabase (PostgreSQL).

Endpoints:
  GET  /api/licencia/{installation_id}   → Consulta estado de licencia (la app cliente llama esto)
  POST /api/licencia                     → Crea o actualiza licencia (solo admin con API key)
  GET  /api/licencias                    → Lista todas las licencias (solo admin)
  DELETE /api/licencia/{installation_id} → Revoca una licencia (solo admin)
"""

import os
import datetime
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client

app = FastAPI(title="Parroquia Licencias API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)

# ── Supabase client ───────────────────────────────────────────────────────────

def get_supabase() -> Client:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise HTTPException(status_code=500, detail="Supabase no configurado en variables de entorno")
    return create_client(url, key)


# ── Auth admin ────────────────────────────────────────────────────────────────

ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")

def verificar_admin(x_api_key: str = Header(...)):
    if not ADMIN_API_KEY:
        raise HTTPException(status_code=500, detail="ADMIN_API_KEY no configurada")
    if x_api_key != ADMIN_API_KEY:
        raise HTTPException(status_code=403, detail="API key inválida")
    return True


# ── Modelos ───────────────────────────────────────────────────────────────────

class LicenciaCreate(BaseModel):
    installation_id: str          # UUID único de la instalación
    cliente_nombre: str           # Nombre descriptivo (ej: "Parroquia San Pedro")
    fecha_vigencia: str           # YYYY-MM-DD
    notas: str = ""               # Opcional


class LicenciaUpdate(BaseModel):
    fecha_vigencia: str
    notas: str = ""


# ── Endpoints cliente (sin auth, solo por installation_id) ───────────────────

@app.get("/api/licencia/{installation_id}")
async def consultar_licencia(installation_id: str):
    """
    La app cliente llama este endpoint al iniciar sesión.
    Devuelve el estado actual de la licencia para esa instalación.
    """
    supabase = get_supabase()

    result = supabase.table("licencias").select("*").eq(
        "installation_id", installation_id
    ).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Instalación no registrada")

    lic = result.data[0]
    fecha_str = lic["fecha_vigencia"]

    try:
        fecha_venc = datetime.date.fromisoformat(fecha_str)
    except ValueError:
        raise HTTPException(status_code=500, detail="Fecha de vigencia inválida en servidor")

    hoy = datetime.date.today()
    dias_restantes = (fecha_venc - hoy).days
    activa = dias_restantes >= 0

    # Actualizar última consulta
    supabase.table("licencias").update({
        "ultima_consulta": datetime.datetime.utcnow().isoformat()
    }).eq("installation_id", installation_id).execute()

    return {
        "installation_id": installation_id,
        "cliente_nombre":  lic.get("cliente_nombre", ""),
        "activa":          activa,
        "fecha_vigencia":  fecha_str,
        "dias_restantes":  dias_restantes,
        "mensaje": (
            f"Licencia válida — vence el {fecha_str} ({dias_restantes} día(s) restantes)"
            if activa else
            f"Licencia expirada hace {abs(dias_restantes)} día(s)"
        ),
        "sincronizado_en": datetime.datetime.utcnow().isoformat(),
    }


# ── Endpoints admin ───────────────────────────────────────────────────────────

@app.get("/api/licencias")
async def listar_licencias(_: bool = Depends(verificar_admin)):
    """Lista todas las licencias registradas."""
    supabase = get_supabase()
    result = supabase.table("licencias").select("*").order("cliente_nombre").execute()
    return {"licencias": result.data, "total": len(result.data)}


@app.post("/api/licencia", status_code=201)
async def crear_licencia(body: LicenciaCreate, _: bool = Depends(verificar_admin)):
    """Registra una nueva instalación con su fecha de vigencia."""
    supabase = get_supabase()

    # Validar fecha
    try:
        datetime.date.fromisoformat(body.fecha_vigencia)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido (usa YYYY-MM-DD)")

    # Verificar que no exista ya
    existing = supabase.table("licencias").select("installation_id").eq(
        "installation_id", body.installation_id
    ).execute()
    if existing.data:
        raise HTTPException(
            status_code=409,
            detail="Esta installation_id ya existe. Usa PUT para actualizar."
        )

    supabase.table("licencias").insert({
        "installation_id": body.installation_id,
        "cliente_nombre":  body.cliente_nombre,
        "fecha_vigencia":  body.fecha_vigencia,
        "notas":           body.notas,
        "creado_en":       datetime.datetime.utcnow().isoformat(),
        "ultima_consulta": None,
    }).execute()

    return {"ok": True, "mensaje": f"Licencia creada para '{body.cliente_nombre}'"}


@app.put("/api/licencia/{installation_id}")
async def actualizar_licencia(
    installation_id: str,
    body: LicenciaUpdate,
    _: bool = Depends(verificar_admin),
):
    """Actualiza la fecha de vigencia de una instalación existente."""
    supabase = get_supabase()

    try:
        datetime.date.fromisoformat(body.fecha_vigencia)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido (usa YYYY-MM-DD)")

    existing = supabase.table("licencias").select("installation_id").eq(
        "installation_id", installation_id
    ).execute()
    if not existing.data:
        raise HTTPException(status_code=404, detail="Instalación no encontrada")

    supabase.table("licencias").update({
        "fecha_vigencia": body.fecha_vigencia,
        "notas":          body.notas,
        "actualizado_en": datetime.datetime.utcnow().isoformat(),
    }).eq("installation_id", installation_id).execute()

    return {"ok": True, "mensaje": "Licencia actualizada"}


@app.delete("/api/licencia/{installation_id}")
async def revocar_licencia(installation_id: str, _: bool = Depends(verificar_admin)):
    """Revoca (elimina) una licencia. La app quedará bloqueada en la próxima sincronización."""
    supabase = get_supabase()
    supabase.table("licencias").delete().eq("installation_id", installation_id).execute()
    return {"ok": True, "mensaje": "Licencia revocada"}


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "ts": datetime.datetime.utcnow().isoformat()}
