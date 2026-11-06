"""El grafo ReAct del agente.

    START -> agente --(tools_condition)--> herramientas -> agente   (ciclo)
                    `--> END  (cuando el modelo responde sin pedir herramientas)

No hay if/else que elija herramientas: el modelo decide en cada vuelta si llama a alguna
(y a cuál) o si ya puede responder. El grafo solo sigue esa decisión.
"""
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, SystemMessage, trim_messages
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from config import MAX_MENSAJES
from herramientas import HERRAMIENTAS

PROMPT = """Sos el asistente de soporte interno de Colibrí, una tienda online. Respondés consultas \
del equipo sobre clientes, pedidos y envíos.

Reglas:
- Sacá los datos de las herramientas. Nunca inventes ids, montos, fechas ni estados.
- Si te falta un dato para usar una herramienta (por ejemplo el cliente_id), conseguilo con otra herramienta.
- Si una herramienta devuelve un error que empieza con "TEMPORAL", reintentá la misma llamada. \
Si falla dos veces seguidas, avisá que el servicio no está respondiendo.
- Si hay más de un cliente posible o falta información, preguntale al usuario en vez de adivinar.
- Usá el contexto de la conversación: "el último", "ese pedido" o "y el envío?" se refieren a lo que ya se habló.
- Respondé en español, en pocas líneas, con montos en pesos con punto de miles ($14.500) y fechas dd/mm/aaaa."""


class EstadoAgente(MessagesState):
    """Hereda `messages: Annotated[list[AnyMessage], add_messages]` de MessagesState.

    El reducer add_messages hace que cada nodo agregue mensajes al historial en lugar de
    pisarlo, y el checkpointer guarda ese historial por thread_id.
    """


def recortar(mensajes: list[AnyMessage]) -> list[AnyMessage]:
    """Últimos MAX_MENSAJES mensajes, empezando siempre en un mensaje del usuario.

    Empezar en un HumanMessage evita mandarle al modelo un resultado de herramienta
    sin el pedido (tool_call) que lo generó, que la API rechaza.
    """
    return trim_messages(mensajes, max_tokens=MAX_MENSAJES, token_counter=len,
                         strategy="last", start_on="human")


def construir_grafo(modelo: BaseChatModel, checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    modelo_con_herramientas = modelo.bind_tools(HERRAMIENTAS)

    async def agente(state: EstadoAgente) -> dict:
        mensajes = [SystemMessage(PROMPT), *recortar(state["messages"])]
        respuesta = await modelo_con_herramientas.ainvoke(mensajes)
        return {"messages": [respuesta]}

    grafo = StateGraph(EstadoAgente)
    grafo.add_node("agente", agente)
    grafo.add_node("herramientas", ToolNode(HERRAMIENTAS))

    grafo.add_edge(START, "agente")
    # tools_condition mira el último mensaje: si trae tool_calls devuelve "tools", si no END
    grafo.add_conditional_edges("agente", tools_condition, {"tools": "herramientas", END: END})
    grafo.add_edge("herramientas", "agente")   # la observación vuelve al modelo: el ciclo ReAct

    return grafo.compile(checkpointer=checkpointer)
