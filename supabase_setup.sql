-- Ejecuta esto en el SQL Editor de Supabase (https://app.supabase.com)
-- Dashboard → SQL Editor → New Query → pegar y ejecutar

CREATE TABLE IF NOT EXISTS licencias (
    id               SERIAL PRIMARY KEY,
    installation_id  TEXT UNIQUE NOT NULL,   -- UUID generado por la app al instalar
    cliente_nombre   TEXT NOT NULL,           -- Nombre descriptivo: "Parroquia San Pedro"
    fecha_vigencia   DATE NOT NULL,           -- Fecha hasta la que es válida
    notas            TEXT DEFAULT '',
    creado_en        TIMESTAMPTZ DEFAULT NOW(),
    actualizado_en   TIMESTAMPTZ,
    ultima_consulta  TIMESTAMPTZ              -- Última vez que la app sincronizó
);

-- Índice para búsquedas por installation_id
CREATE INDEX IF NOT EXISTS idx_licencias_installation_id ON licencias(installation_id);

-- Deshabilitar RLS (la API usa service_key, acceso controlado por ADMIN_API_KEY)
ALTER TABLE licencias DISABLE ROW LEVEL SECURITY;
