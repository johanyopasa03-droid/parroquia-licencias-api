from http.server import BaseHTTPRequestHandler
import json
import os
import datetime
import urllib.parse

# ── Supabase client (httpx-free, usa urllib) ──────────────────────────────────
import urllib.request
import urllib.error

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")


def _sb_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _sb_get(table: str, params: dict = None) -> list:
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_sb_headers())
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())


def _sb_post(table: str, data: dict) -> dict:
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{table}",
        data=body, headers=_sb_headers(), method="POST"
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        result = r.read().decode()
        return json.loads(result)[0] if result.strip().startswith("[") else json.loads(result)


def _sb_patch(table: str, filter_param: str, data: dict):
    body = json.dumps(data).encode()
    url = f"{SUPABASE_URL}/rest/v1/{table}?{filter_param}"
    req = urllib.request.Request(url, data=body, headers=_sb_headers(), method="PATCH")
    with urllib.request.urlopen(req, timeout=8) as r:
        return r.read().decode()


def _sb_delete(table: str, filter_param: str):
    url = f"{SUPABASE_URL}/rest/v1/{table}?{filter_param}"
    req = urllib.request.Request(url, headers=_sb_headers(), method="DELETE")
    with urllib.request.urlopen(req, timeout=8) as r:
        return r.read().decode()


# ── Handler principal ─────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):

    def _send(self, status: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _is_admin(self) -> bool:
        return self.headers.get("x-api-key", "") == ADMIN_API_KEY

    # ── Routing ───────────────────────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "x-api-key, Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")

        # Health check
        if path in ("/api", "/api/health", "/api/index"):
            self._send(200, {"status": "ok", "ts": datetime.datetime.utcnow().isoformat()})
            return

        # GET /api/licencias  — lista todas (admin)
        if path == "/api/licencias":
            if not self._is_admin():
                self._send(403, {"error": "No autorizado"}); return
            try:
                rows = _sb_get("licencias", {"order": "cliente_nombre"})
                self._send(200, {"licencias": rows, "total": len(rows)})
            except Exception as ex:
                self._send(500, {"error": str(ex)})
            return

        # GET /api/licencia/{installation_id}
        if path.startswith("/api/licencia/"):
            iid = path[len("/api/licencia/"):]
            if not iid:
                self._send(400, {"error": "installation_id requerido"}); return
            try:
                rows = _sb_get("licencias", {
                    "installation_id": f"eq.{iid}",
                    "select": "*",
                    "limit": "1",
                })
                if not rows:
                    self._send(404, {"error": "Instalación no registrada"}); return

                lic = rows[0]
                fecha_str = lic["fecha_vigencia"]
                fecha_venc = datetime.date.fromisoformat(fecha_str)
                hoy = datetime.date.today()
                dias = (fecha_venc - hoy).days
                activa = dias >= 0

                # Actualizar ultima_consulta
                try:
                    _sb_patch("licencias",
                              f"installation_id=eq.{iid}",
                              {"ultima_consulta": datetime.datetime.utcnow().isoformat()})
                except Exception:
                    pass

                self._send(200, {
                    "installation_id": iid,
                    "cliente_nombre":  lic.get("cliente_nombre", ""),
                    "activa":          activa,
                    "fecha_vigencia":  fecha_str,
                    "dias_restantes":  dias,
                    "mensaje": (
                        f"Licencia válida — vence el {fecha_str} ({dias} día(s) restantes)"
                        if activa else
                        f"Licencia expirada hace {abs(dias)} día(s)"
                    ),
                    "sincronizado_en": datetime.datetime.utcnow().isoformat(),
                })
            except Exception as ex:
                self._send(500, {"error": str(ex)})
            return

        self._send(404, {"error": "Endpoint no encontrado"})

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")

        if path == "/api/licencia":
            if not self._is_admin():
                self._send(403, {"error": "No autorizado"}); return
            body = self._body()
            iid    = body.get("installation_id", "").strip()
            nombre = body.get("cliente_nombre", "").strip()
            fecha  = body.get("fecha_vigencia", "").strip()
            notas  = body.get("notas", "")
            if not iid or not nombre or not fecha:
                self._send(400, {"error": "installation_id, cliente_nombre y fecha_vigencia son obligatorios"}); return
            try:
                datetime.date.fromisoformat(fecha)
            except ValueError:
                self._send(400, {"error": "Formato de fecha inválido (YYYY-MM-DD)"}); return
            try:
                existing = _sb_get("licencias", {"installation_id": f"eq.{iid}", "select": "id"})
                if existing:
                    self._send(409, {"error": "installation_id ya existe, usa PUT para actualizar"}); return
                _sb_post("licencias", {
                    "installation_id": iid,
                    "cliente_nombre":  nombre,
                    "fecha_vigencia":  fecha,
                    "notas":           notas,
                })
                self._send(201, {"ok": True, "mensaje": f"Licencia creada para '{nombre}'"})
            except Exception as ex:
                self._send(500, {"error": str(ex)})
            return

        self._send(404, {"error": "Endpoint no encontrado"})

    def do_PUT(self):
        path = self.path.split("?")[0].rstrip("/")

        if path.startswith("/api/licencia/"):
            if not self._is_admin():
                self._send(403, {"error": "No autorizado"}); return
            iid = path[len("/api/licencia/"):]
            body = self._body()
            fecha = body.get("fecha_vigencia", "").strip()
            notas = body.get("notas", "")
            if not fecha:
                self._send(400, {"error": "fecha_vigencia es obligatoria"}); return
            try:
                datetime.date.fromisoformat(fecha)
            except ValueError:
                self._send(400, {"error": "Formato de fecha inválido (YYYY-MM-DD)"}); return
            try:
                existing = _sb_get("licencias", {"installation_id": f"eq.{iid}", "select": "id"})
                if not existing:
                    self._send(404, {"error": "Instalación no encontrada"}); return
                _sb_patch("licencias", f"installation_id=eq.{iid}", {
                    "fecha_vigencia": fecha,
                    "notas": notas,
                    "actualizado_en": datetime.datetime.utcnow().isoformat(),
                })
                self._send(200, {"ok": True, "mensaje": "Licencia actualizada"})
            except Exception as ex:
                self._send(500, {"error": str(ex)})
            return

        self._send(404, {"error": "Endpoint no encontrado"})

    def do_DELETE(self):
        path = self.path.split("?")[0].rstrip("/")

        if path.startswith("/api/licencia/"):
            if not self._is_admin():
                self._send(403, {"error": "No autorizado"}); return
            iid = path[len("/api/licencia/"):]
            try:
                _sb_delete("licencias", f"installation_id=eq.{iid}")
                self._send(200, {"ok": True, "mensaje": "Licencia revocada"})
            except Exception as ex:
                self._send(500, {"error": str(ex)})
            return

        self._send(404, {"error": "Endpoint no encontrado"})

    def log_message(self, format, *args):
        pass  # silenciar logs de acceso
