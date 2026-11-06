"""Configuración compartida: rutas, límites del agente y creación del LLM."""
import os
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

BASE = Path(__file__).parent
SEMILLA = BASE / "data" / "semilla.sql"
BASE_DATOS = BASE / "data" / "colibri.db"   # se genera desde la semilla (no se sube)
MEMORIA = BASE / "memoria.sqlite"           # checkpoints del agente (SqliteSaver)
TRAZAS = BASE / "trazas"

# Techo de pasos por invocación del grafo. Cada ida y vuelta agente -> herramientas son 2 pasos,
# así que 10 alcanza para 4 llamadas a herramientas más la respuesta final.
RECURSION_LIMIT = int(os.getenv("RECURSION_LIMIT", "10"))

# Cuántos mensajes del historial se le mandan al modelo. El checkpoint guarda todo,
# pero al LLM solo le llegan los últimos para que el contexto no crezca sin límite.
MAX_MENSAJES = 30

# El servicio de seguimiento de envíos simula una caída en la primera consulta de cada pedido
# (solo para estas empresas), para probar que el agente reintenta.
EMPRESAS_INESTABLES = {"Correo Argentino"}
SIMULAR_FALLAS = os.getenv("SIMULAR_FALLAS", "1") == "1"


def env(nombre: str, default: str | None = None, requerida: bool = False) -> str | None:
    valor = os.getenv(nombre) or default
    if requerida and not valor:
        raise ValueError(f"Falta {nombre} en el .env")
    return valor


def resumir_error(e: Exception) -> str:
    lineas = [linea.strip() for linea in str(e).splitlines() if linea.strip()][:2]
    return f"{type(e).__name__}: {' '.join(lineas)[:250]}"


def crear_llm() -> BaseChatModel:
    """ChatOpenAI o ChatAnthropic según LLM_PROVIDER (la misma idea que el Módulo 1)."""
    provider = env("LLM_PROVIDER", "openai").lower()
    if provider == "openai":
        env("OPENAI_API_KEY", requerida=True)
        # OPENAI_BASE_URL permite usar cualquier API compatible con OpenAI
        return ChatOpenAI(model=env("OPENAI_MODEL", "gpt-4o-mini"), temperature=0,
                          base_url=env("OPENAI_BASE_URL"), timeout=30, max_retries=2)
    if provider == "anthropic":
        env("ANTHROPIC_API_KEY", requerida=True)
        # Sin temperature: el SDK actual de Anthropic ya no la acepta
        return ChatAnthropic(model=env("ANTHROPIC_MODEL", "claude-haiku-4-5"),
                             max_tokens=1024, timeout=30, max_retries=2)
    raise ValueError(f"LLM_PROVIDER no soportado: {provider!r} (usá openai o anthropic)")


def nombre_modelo(modelo: BaseChatModel) -> str:
    return getattr(modelo, "model_name", None) or getattr(modelo, "model", None) or modelo._llm_type
