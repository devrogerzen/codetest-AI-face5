"""Agente listo para usar: grafo + memoria persistente en SQLite + traza del razonamiento.

Uso:
    async with abrir_agente() as agente:
        turno = await agente.preguntar("¿Cuántos pedidos tuvo el cliente 102?", thread_id="soporte-1")
"""
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph

from config import MEMORIA, RECURSION_LIMIT, crear_llm, nombre_modelo
from grafo import construir_grafo


def _leer(contenido: str) -> Any:
    try:
        return json.loads(contenido)
    except (TypeError, json.JSONDecodeError):
        return contenido   # p. ej. el mensaje de error de validación de Pydantic


def _argumentos(args: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


@dataclass
class Turno:
    thread_id: str
    pregunta: str
    pasos: list[dict[str, Any]] = field(default_factory=list)
    respuesta: str = ""

    @property
    def llamadas(self) -> list[dict[str, Any]]:
        return [p for p in self.pasos if p["tipo"] == "accion"]

    def a_dict(self) -> dict[str, Any]:
        return {"thread_id": self.thread_id, "pregunta": self.pregunta,
                "llamadas_a_herramientas": len(self.llamadas), "pasos": self.pasos,
                "respuesta": self.respuesta}

    def lineas(self) -> list[str]:
        """La traza en el formato de la consigna: decisión, observación, respuesta."""
        lineas = [f'[{self.thread_id}] Usuario: "{self.pregunta}"']
        for paso in self.pasos:
            if paso["tipo"] == "accion":
                lineas.append(f"  → El agente decide usar: {paso['herramienta']}({_argumentos(paso['argumentos'])})")
            else:
                resultado = json.dumps(paso["resultado"], ensure_ascii=False)
                lineas.append(f"  → {paso['herramienta']} devuelve: {resultado}")
        lineas.append(f'  Respuesta: "{self.respuesta}"')
        return lineas


@dataclass
class Agente:
    app: CompiledStateGraph
    memoria: AsyncSqliteSaver
    modelo: str
    recursion_limit: int = RECURSION_LIMIT

    async def preguntar(self, pregunta: str, thread_id: str, mostrar: bool = True) -> Turno:
        """Corre una vuelta completa del ciclo ReAct y devuelve los pasos que dio el agente.

        Con el mismo thread_id el checkpointer recupera la conversación anterior; con otro, arranca de cero.
        """
        turno = Turno(thread_id, pregunta)
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": self.recursion_limit}
        if mostrar:
            print(turno.lineas()[0])
        mostrados = 0
        try:
            # stream_mode="updates" entrega lo que devuelve cada nodo apenas termina
            async for actualizacion in self.app.astream({"messages": [HumanMessage(pregunta)]}, config,
                                                         stream_mode="updates"):
                for cambios in actualizacion.values():
                    for mensaje in (cambios or {}).get("messages", []):
                        self._registrar(turno, mensaje)
                if mostrar:   # una línea por paso nuevo, a medida que el agente avanza
                    for linea in turno.lineas()[1 + mostrados:-1]:
                        print(linea)
                    mostrados = len(turno.pasos)
        except GraphRecursionError:
            turno.respuesta = (f"Corté la ejecución: el agente superó el límite de {self.recursion_limit} pasos "
                               "sin llegar a una respuesta.")
        if mostrar:
            print(turno.lineas()[-1])
        return turno

    @staticmethod
    def _registrar(turno: Turno, mensaje: Any) -> None:
        if isinstance(mensaje, AIMessage) and mensaje.tool_calls:
            for llamada in mensaje.tool_calls:
                turno.pasos.append({"tipo": "accion", "herramienta": llamada["name"], "argumentos": llamada["args"]})
        elif isinstance(mensaje, ToolMessage):
            turno.pasos.append({"tipo": "observacion", "herramienta": mensaje.name, "resultado": _leer(mensaje.content)})
        elif isinstance(mensaje, AIMessage):
            turno.respuesta = mensaje.text

    async def historial(self, thread_id: str) -> list[Any]:
        estado = await self.app.aget_state({"configurable": {"thread_id": thread_id}})
        return estado.values.get("messages", [])

    async def olvidar(self, thread_id: str) -> None:
        await self.memoria.adelete_thread(thread_id)


@asynccontextmanager
async def abrir_agente(sin_api: bool = False, ruta_memoria: Path = MEMORIA,
                       recursion_limit: int = RECURSION_LIMIT) -> AsyncIterator[Agente]:
    """Abre la memoria en SQLite y compila el grafo. Con sin_api=True usa el modelo simulado."""
    if sin_api:
        from modelo_simulado import ModeloSimulado
        modelo = ModeloSimulado()
    else:
        modelo = crear_llm()
    # AsyncSqliteSaver es la versión asíncrona de SqliteSaver: el grafo corre con astream/ainvoke
    async with AsyncSqliteSaver.from_conn_string(str(ruta_memoria)) as memoria:
        await memoria.setup()   # crea las tablas si es la primera vez
        yield Agente(construir_grafo(modelo, memoria), memoria, nombre_modelo(modelo), recursion_limit)


def guardar_traza(turnos: list[Turno], destino: Path, modelo: str, recursion_limit: int) -> None:
    """Escribe la traza en dos formatos: .json (para leer con código) y .log (para leer a ojo)."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    datos = {
        "generado": datetime.now().isoformat(timespec="seconds"),
        "modelo": modelo,
        "recursion_limit": recursion_limit,
        "turnos": [t.a_dict() for t in turnos],
    }
    destino.with_suffix(".json").write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    encabezado = [f"# Traza ReAct · modelo: {modelo} · recursion_limit={recursion_limit} · {datos['generado']}", ""]
    cuerpo = [linea for t in turnos for linea in (*t.lineas(), "")]
    destino.with_suffix(".log").write_text("\n".join(encabezado + cuerpo), encoding="utf-8")
