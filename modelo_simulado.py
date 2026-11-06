"""Modelo simulado para correr el agente sin API key (python main.py --sin-api).

Imita lo que hace un LLM con tool calling: lee el historial y devuelve un AIMessage que pide
una herramienta (tool_calls) o que responde con texto. Decide con reglas simples, así que solo
entiende preguntas parecidas a las de la demo. Sirve para probar el grafo, las herramientas,
el reintento y la memoria sin gastar tokens; no reemplaza a un modelo real.
"""
import json
import re
import uuid
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from base_datos import normalizar

NOMBRE = re.compile(r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+)+")
NUMERO_CLIENTE = re.compile(r"cliente\s+(?:n[°º.]?\s*)?(\d+)", re.IGNORECASE)


def _leer(contenido: Any) -> Any:
    try:
        return json.loads(contenido)
    except (TypeError, json.JSONDecodeError):
        return contenido


def _pesos(monto: int) -> str:
    return "$" + f"{monto:,}".replace(",", ".")


def _fecha(iso: str) -> str:
    anio, mes, dia = iso.split("-")
    return f"{dia}/{mes}/{anio}"


def _pide_envio(texto: str) -> bool:
    texto = normalizar(texto)
    return any(p in texto for p in ("envio", "llega", "donde esta", "seguimiento"))


def _pide_ultimo(texto: str) -> bool:
    return "ultimo" in normalizar(texto)


def _llamar(herramienta: str, **argumentos: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": herramienta, "args": argumentos,
                                              "id": f"call_{uuid.uuid4().hex[:12]}", "type": "tool_call"}])


def _responder(texto: str) -> AIMessage:
    return AIMessage(content=texto)


def _describir_pedido(cliente: str, pedido: dict[str, Any]) -> str:
    return (f"El último pedido de {cliente} es el #{pedido['id']}, del {_fecha(pedido['fecha'])}, "
            f"por {_pesos(pedido['total'])}. Estado: {pedido['estado'].replace('_', ' ')}.")


class ModeloSimulado(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "simulado-sin-api"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ModeloSimulado":
        return self   # las reglas ya conocen las tres herramientas

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None,
                  **kwargs: Any) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._decidir(messages))])

    def _decidir(self, mensajes: list[BaseMessage]) -> AIMessage:
        humanos = [n for n, m in enumerate(mensajes) if isinstance(m, HumanMessage)]
        i = humanos[-1]
        pregunta = mensajes[i].text
        # Si el agente había preguntado algo, la respuesta del usuario completa la consulta anterior
        intencion = pregunta
        if len(humanos) > 1 and isinstance(mensajes[i - 1], AIMessage) and mensajes[i - 1].text.rstrip().endswith("?"):
            intencion = f"{mensajes[humanos[-2]].text} {pregunta}"

        turno = mensajes[i + 1:]
        observaciones = [(m.name, _leer(m.content)) for m in turno if isinstance(m, ToolMessage)]
        if observaciones:
            return self._seguir(intencion, turno, observaciones)
        return self._empezar(pregunta, intencion, mensajes[:i])

    def _empezar(self, pregunta: str, intencion: str, anteriores: list[BaseMessage]) -> AIMessage:
        previas = [_leer(m.content) for m in anteriores if isinstance(m, ToolMessage)]
        ultima = previas[-1] if previas else None

        # El usuario está aclarando a cuál de varios clientes se refería
        if isinstance(ultima, dict) and ultima.get("coincidencias", 0) > 1:
            elegido = next((c for c in ultima["clientes"] if normalizar(c["ciudad"]) in normalizar(pregunta)), None)
            if elegido:
                return _llamar("buscar_pedidos", cliente_id=elegido["id"])

        if numero := NUMERO_CLIENTE.search(pregunta):
            return _llamar("buscar_pedidos", cliente_id=int(numero[1]))
        if nombre := NOMBRE.search(pregunta):
            return _llamar("buscar_cliente", nombre=nombre[0])

        # Sin datos nuevos en la pregunta: usa lo que quedó en la conversación (memoria del thread)
        historial = next((d for d in reversed(previas) if isinstance(d, dict) and d.get("pedidos")), None)
        if historial:
            ultimo = historial["pedidos"][0]
            if _pide_envio(intencion):
                return _llamar("consultar_envio", pedido_id=ultimo["id"])
            if _pide_ultimo(intencion):
                return _responder(_describir_pedido(historial["cliente"], ultimo))
        return _responder("¿De qué cliente o pedido me hablás? Pasame el nombre o el número de cliente.")

    def _seguir(self, intencion: str, turno: list[BaseMessage], observaciones: list[tuple[str, Any]]) -> AIMessage:
        herramienta, dato = observaciones[-1]

        if isinstance(dato, dict) and str(dato.get("error", "")).startswith("TEMPORAL"):
            fallas = sum(1 for _, d in observaciones if isinstance(d, dict) and str(d.get("error", "")).startswith("TEMPORAL"))
            if fallas >= 2:
                return _responder("El servicio de seguimiento no está respondiendo. Probá de nuevo en unos minutos.")
            pedido = next(m for m in reversed(turno) if isinstance(m, AIMessage) and m.tool_calls).tool_calls[-1]
            return _llamar(pedido["name"], **pedido["args"])   # mismo pedido: segundo intento

        if not isinstance(dato, dict):
            return _responder(f"La herramienta rechazó los datos: {dato}")
        if "error" in dato:
            return _responder(dato["error"])

        if herramienta == "buscar_cliente":
            clientes = dato["clientes"]
            if len(clientes) > 1:
                opciones = " y ".join(f"una de {c['ciudad']} (cliente {c['id']})" for c in clientes)
                return _responder(f"Encontré {len(clientes)} clientes llamados {clientes[0]['nombre']}: {opciones}. ¿De cuál me hablás?")
            return _llamar("buscar_pedidos", cliente_id=clientes[0]["id"])

        if herramienta == "buscar_pedidos":
            if not dato["pedidos"]:
                return _responder(f"{dato['cliente']} todavía no hizo pedidos.")
            ultimo = dato["pedidos"][0]
            if _pide_envio(intencion):
                return _llamar("consultar_envio", pedido_id=ultimo["id"])
            if _pide_ultimo(intencion):
                return _responder(_describir_pedido(dato["cliente"], ultimo))
            return _responder(f"El cliente {dato['cliente_id']} ({dato['cliente']}) tuvo {dato['cantidad_pedidos']} "
                              f"pedidos por un total de {_pesos(dato['total_gastado'])}.")

        # consultar_envio
        if dato.get("aviso"):
            historial = next((d for n, d in reversed(observaciones) if n == "buscar_pedidos"), None)
            pedido = next((p for p in historial["pedidos"] if p["id"] == dato["pedido_id"]), None) if historial else None
            if pedido:
                return _responder(f"El último pedido de {historial['cliente']} es el #{pedido['id']}, del "
                                  f"{_fecha(pedido['fecha'])}, por {_pesos(pedido['total'])}. {dato['aviso']}")
            return _responder(f"Pedido #{dato['pedido_id']}: {dato['aviso']}")
        texto = (f"El pedido #{dato['pedido_id']} va por {dato['empresa']} (seguimiento {dato['codigo_seguimiento']}). "
                 f"Estado: {dato['estado'].replace('_', ' ')}. Última novedad: {dato['ultima_novedad']}.")
        if dato["entrega_estimada"]:
            texto += f" Entrega estimada: {_fecha(dato['entrega_estimada'])}."
        return _responder(texto)
