"""Chat por consola con el agente de soporte de Colibrí. La conversación queda guardada en
memoria.sqlite por thread_id, así que se puede cortar el programa y retomarla después.

Uso:
    python main.py --thread soporte-1                                   # chat interactivo
    python main.py "¿Cuántos pedidos tuvo el cliente 102?" --thread soporte-1
    python main.py "¿Y el último?" --thread soporte-1                   # otra ejecución: recuerda la anterior
    python main.py --thread soporte-1 --historial                       # muestra lo guardado en ese thread
    python main.py --sin-api ...                                        # modelo simulado, sin keys
"""
import argparse
import asyncio
import logging
import sys

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agente import Agente, abrir_agente
from config import resumir_error


async def mostrar_historial(agente: Agente, thread_id: str) -> None:
    mensajes = await agente.historial(thread_id)
    if not mensajes:
        print(f"El thread '{thread_id}' no tiene mensajes guardados.")
        return
    for m in mensajes:
        if isinstance(m, HumanMessage):
            print(f"Usuario: {m.text}")
        elif isinstance(m, AIMessage) and m.tool_calls:
            print(f"  [herramienta] {', '.join(llamada['name'] for llamada in m.tool_calls)}")
        elif isinstance(m, ToolMessage):
            continue
        else:
            print(f"Agente: {m.text}")


async def main(pregunta: str | None, thread_id: str, sin_api: bool, historial: bool) -> None:
    async with abrir_agente(sin_api=sin_api) as agente:
        print(f"Modelo: {agente.modelo} · thread: {thread_id}\n")
        if historial:
            await mostrar_historial(agente, thread_id)
        elif pregunta:
            await agente.preguntar(pregunta, thread_id)
        else:
            print("Escribí tu consulta (enter vacío para salir).")
            while texto := input("\n> ").strip():
                try:
                    await agente.preguntar(texto, thread_id)
                except Exception as e:   # un error del LLM no corta la conversación
                    print(f"Error de {resumir_error(e)}")


if __name__ == "__main__":
    load_dotenv()
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)-7s %(name)s: %(message)s")
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("pregunta", nargs="?")
    argumentos.add_argument("--thread", default="soporte-1", help="id de la conversación (default soporte-1)")
    argumentos.add_argument("--sin-api", action="store_true", help="usa el modelo simulado, sin keys")
    argumentos.add_argument("--historial", action="store_true", help="muestra la conversación guardada")
    a = argumentos.parse_args()
    try:
        asyncio.run(main(a.pregunta, a.thread, a.sin_api, a.historial))
    except KeyboardInterrupt:
        pass
    except Exception as e:  # key faltante o inválida, sin saldo, sin red...
        print(f"Error de {resumir_error(e)}")
