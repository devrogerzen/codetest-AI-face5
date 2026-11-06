"""Acceso a la base SQLite de Colibrí (clientes, pedidos y envíos).

sqlite3 es sincrónico, así que cada consulta corre en un hilo aparte con asyncio.to_thread
para no bloquear el event loop del agente.
"""
import asyncio
import sqlite3
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Any

from config import BASE_DATOS, SEMILLA


def normalizar(texto: str) -> str:
    """Minúsculas y sin acentos: 'Julián' y 'julian' tienen que encontrar al mismo cliente."""
    sin_acentos = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sin_acentos if not unicodedata.combining(c)).lower().strip()


def crear_base(ruta: Path = BASE_DATOS, reiniciar: bool = False) -> None:
    if reiniciar:
        ruta.unlink(missing_ok=True)
    if ruta.exists():
        return
    with closing(sqlite3.connect(ruta)) as conn:
        conn.executescript(SEMILLA.read_text(encoding="utf-8"))
        conn.commit()


def _consultar(sql: str, parametros: tuple[Any, ...]) -> list[dict[str, Any]]:
    crear_base()
    with closing(sqlite3.connect(BASE_DATOS)) as conn:
        conn.row_factory = sqlite3.Row
        conn.create_function("normalizar", 1, normalizar, deterministic=True)
        return [dict(fila) for fila in conn.execute(sql, parametros)]


async def consultar(sql: str, parametros: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    # Siempre con parámetros (?): el SQL lo escribimos nosotros, el LLM solo aporta valores
    return await asyncio.to_thread(_consultar, sql, parametros)
