"""Prueba sin API key de las herramientas, el grafo, el ciclo ReAct, la persistencia con SQLite
y el límite de recursión. El LLM se reemplaza por el modelo simulado.

Uso:
    python prueba_sin_api.py
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import ValidationError

from agente import abrir_agente, guardar_traza
from base_datos import crear_base
from grafo import construir_grafo, recortar
from herramientas import buscar_cliente, buscar_pedidos, consultar_envio, reiniciar_fallas
from modelo_simulado import ModeloSimulado

resultados: list[bool] = []


def chequear(descripcion: str, condicion: bool, detalle: str = "") -> None:
    resultados.append(condicion)
    print(f"  {'OK   ' if condicion else 'FALLA'} {descripcion}{f'  ({detalle})' if detalle else ''}")


class ModeloTerco(ModeloSimulado):
    """Pide una herramienta en cada vuelta y nunca responde: sirve para probar recursion_limit."""
    def _decidir(self, mensajes: list[BaseMessage]) -> AIMessage:
        return AIMessage(content="", tool_calls=[{"name": "buscar_cliente", "args": {"nombre": "Pereyra"},
                                                  "id": f"call_{len(mensajes)}", "type": "tool_call"}])


async def main() -> None:
    crear_base(reiniciar=True)
    reiniciar_fallas()

    print("\n> Herramientas (contrato y datos)")
    r = await buscar_cliente.ainvoke({"nombre": "julian pereyra"})
    chequear("buscar_cliente ignora mayúsculas y acentos", r["clientes"][0]["id"] == 102, str(r["clientes"][0]))
    r = await buscar_cliente.ainvoke({"nombre": "Lucía Fernández"})
    chequear("con un nombre repetido devuelve todas las coincidencias", r["coincidencias"] == 2)
    r = await buscar_pedidos.ainvoke({"cliente_id": 102})
    chequear("cliente 102: 3 pedidos por $14.500 (el ejemplo de la consigna)",
             (r["cantidad_pedidos"], r["total_gastado"]) == (3, 14500))
    chequear("los pedidos vienen del más nuevo al más viejo",
             [p["id"] for p in r["pedidos"]] == [5012, 5007, 5001])
    r = await buscar_pedidos.ainvoke({"cliente_id": 101})
    chequear("el total no cuenta los pedidos cancelados", r["total_gastado"] == 12990)
    r = await buscar_pedidos.ainvoke({"cliente_id": 999})
    chequear("un cliente inexistente devuelve un error legible (no una excepción)", "error" in r)
    try:
        await buscar_pedidos.ainvoke({"cliente_id": 0})
        chequear("Pydantic rechaza cliente_id=0", False)
    except ValidationError:
        chequear("Pydantic rechaza cliente_id=0", True)
    primero = await consultar_envio.ainvoke({"pedido_id": 5012})
    segundo = await consultar_envio.ainvoke({"pedido_id": 5012})
    chequear("el servicio de envíos simula una falla TEMPORAL y después responde",
             primero["error"].startswith("TEMPORAL") and segundo["estado"] == "en_camino")
    r = await consultar_envio.ainvoke({"pedido_id": 5013})
    chequear("un pedido sin envío devuelve un aviso (información incompleta)", r["envio"] is None and "aviso" in r)

    print("\n> Estructura del grafo")
    grafo = construir_grafo(ModeloSimulado()).get_graph()
    aristas = {(a.source, a.target, a.conditional) for a in grafo.edges}
    chequear("tiene los nodos agente y herramientas", {"agente", "herramientas"} <= set(grafo.nodes))
    chequear("agente -> herramientas y agente -> END son aristas condicionales (tools_condition)",
             {("agente", "herramientas", True), ("agente", "__end__", True)} <= aristas)
    chequear("herramientas -> agente cierra el ciclo ReAct", ("herramientas", "agente", False) in aristas)

    reiniciar_fallas()
    with tempfile.TemporaryDirectory() as carpeta:
        memoria = Path(carpeta) / "memoria.sqlite"

        print("\n> Razonamiento multi-paso y ciclo de retorno")
        async with abrir_agente(sin_api=True, ruta_memoria=memoria) as agente:
            t = await agente.preguntar("¿Dónde está el último pedido de Julián Pereyra y cuándo llega?",
                                       "multi", mostrar=False)
            usadas = [p["herramienta"] for p in t.llamadas]
            chequear("una sola pregunta encadena las 3 herramientas (cliente -> pedidos -> envío)",
                     usadas[:3] == ["buscar_cliente", "buscar_pedidos", "consultar_envio"], " -> ".join(usadas))
            chequear("ante el error TEMPORAL reintenta la misma herramienta", usadas[3:] == ["consultar_envio"])
            chequear("la respuesta final usa el dato observado", "08/11/2026" in t.respuesta, t.respuesta)

            t = await agente.preguntar("¿En qué estado está el envío del último pedido de Lucía Fernández?",
                                       "lucia", mostrar=False)
            chequear("si el cliente es ambiguo pregunta en vez de adivinar",
                     t.respuesta.endswith("?") and len(t.llamadas) == 1, t.respuesta[:60] + "...")
            t = await agente.preguntar("La de Mendoza", "lucia", mostrar=False)
            chequear("con la aclaración retoma la consulta original",
                     [p["herramienta"] for p in t.llamadas] == ["buscar_pedidos", "consultar_envio"])

            print("\n> Memoria con SqliteSaver + thread_id")
            await agente.preguntar("¿Cuántos pedidos tuvo el cliente 102 y cuál fue el total?", "memoria", mostrar=False)
            t = await agente.preguntar("¿Y el último?", "memoria", mostrar=False)
            chequear("con el mismo thread_id recuerda el contexto", "#5012" in t.respuesta, t.respuesta[:60] + "...")
            t = await agente.preguntar("¿Y el último?", "otro-thread", mostrar=False)
            chequear("con otro thread_id no sabe de qué le hablan", "#5012" not in t.respuesta)

        # Se cierra la conexión y se abre otra: simula cortar el programa y volver a ejecutarlo
        async with abrir_agente(sin_api=True, ruta_memoria=memoria) as agente:
            historial = await agente.historial("memoria")
            chequear("el historial sobrevive al reinicio (queda en el archivo SQLite)", len(historial) >= 4,
                     f"{len(historial)} mensajes")
            t = await agente.preguntar("¿En qué estado está el envío de ese pedido?", "memoria", mostrar=False)
            chequear("después del reinicio sigue la conversación", "Correo Argentino" in t.respuesta)
            await agente.olvidar("memoria")
            chequear("olvidar() borra el thread", not await agente.historial("memoria"))

            print("\n> Límite de recursión y traza")
            terco = abrir_agente(sin_api=True, ruta_memoria=memoria, recursion_limit=4)
            async with terco as agente_terco:
                agente_terco.app = construir_grafo(ModeloTerco(), agente_terco.memoria)
                t = await agente_terco.preguntar("Buscá a Pereyra", "terco", mostrar=False)
            chequear("recursion_limit corta un agente que no termina nunca", "límite de 4 pasos" in t.respuesta,
                     f"{len(t.llamadas)} llamadas antes de cortar")

            destino = Path(carpeta) / "traza"
            guardar_traza([t], destino, agente.modelo, agente.recursion_limit)
            datos = json.loads(destino.with_suffix(".json").read_text(encoding="utf-8"))
            chequear("la traza .json y .log se generan", destino.with_suffix(".log").exists()
                     and datos["turnos"][0]["llamadas_a_herramientas"] == len(t.llamadas))

    print("\n> Recorte del historial")
    largos = [m for i in range(40) for m in (HumanMessage(f"pregunta {i}"), AIMessage(f"respuesta {i}"))]
    recortados = recortar(largos)
    chequear("al modelo le llegan como máximo 30 mensajes, empezando por uno del usuario",
             len(recortados) <= 30 and isinstance(recortados[0], HumanMessage), f"{len(recortados)} de {len(largos)}")

    print(f"\n{sum(resultados)}/{len(resultados)} chequeos correctos")
    raise SystemExit(0 if all(resultados) else 1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
