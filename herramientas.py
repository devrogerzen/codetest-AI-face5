"""Herramientas del agente. Cada una tiene un contrato de entrada validado con Pydantic y un
docstring pensado para el LLM: es lo único que lee para decidir cuándo usarla.

Las herramientas no lanzan excepciones por datos inexistentes: devuelven un dict con "error" o
"aviso" para que el modelo pueda corregir el pedido, reintentar o preguntarle al usuario.
"""
from typing import Any

from langchain_core.tools import tool
from pydantic import BaseModel, Field

import config
from base_datos import consultar, normalizar


class BuscarClienteInput(BaseModel):
    nombre: str = Field(min_length=2, description="Nombre y/o apellido del cliente, por ejemplo 'Julián Pereyra' o 'Pereyra'")


class BuscarPedidosInput(BaseModel):
    cliente_id: int = Field(ge=1, description="Número de cliente, por ejemplo 102. Si solo tenés el nombre, usá antes buscar_cliente")
    limite: int = Field(default=10, ge=1, le=50, description="Cantidad máxima de pedidos a listar, del más nuevo al más viejo")


class ConsultarEnvioInput(BaseModel):
    pedido_id: int = Field(ge=1, description="Número de pedido, por ejemplo 5012 (lo devuelve buscar_pedidos)")


@tool(args_schema=BuscarClienteInput)
async def buscar_cliente(nombre: str) -> dict[str, Any]:
    """Busca clientes de Colibrí por nombre y/o apellido (no distingue mayúsculas ni acentos).

    Usala cuando el usuario mencione a un cliente por su nombre y necesites su cliente_id para
    consultar pedidos o envíos. Devuelve el id, el nombre completo y la ciudad de cada coincidencia.
    Si hay más de una coincidencia NO elijas vos: preguntale al usuario cuál es (por ejemplo, por la ciudad).
    """
    palabras = normalizar(nombre).split()
    condiciones = " AND ".join("normalizar(nombre) LIKE ?" for _ in palabras)
    clientes = await consultar(f"SELECT id, nombre, ciudad FROM clientes WHERE {condiciones} ORDER BY id",
                               tuple(f"%{p}%" for p in palabras))
    if not clientes:
        return {"error": f"No hay clientes que coincidan con '{nombre}'. Pedile al usuario el nombre completo o el número de cliente."}
    return {"coincidencias": len(clientes), "clientes": clientes}


@tool(args_schema=BuscarPedidosInput)
async def buscar_pedidos(cliente_id: int, limite: int = 10) -> dict[str, Any]:
    """Devuelve el historial de compras de un cliente de Colibrí: cantidad de pedidos, total gastado en
    pesos (sin contar los cancelados) y la lista de pedidos del más reciente al más antiguo, con id,
    fecha, total y estado (preparando, en_camino, entregado o cancelado).

    Usala para preguntas sobre cuántos pedidos hizo un cliente, cuánto gastó o cuál fue su último pedido.
    Necesita el cliente_id: si no lo tenés, conseguilo primero con buscar_cliente.
    """
    cliente = await consultar("SELECT id, nombre FROM clientes WHERE id = ?", (cliente_id,))
    if not cliente:
        return {"error": f"No existe el cliente {cliente_id}. Verificá el número o buscalo por nombre con buscar_cliente."}
    resumen = await consultar(
        "SELECT COUNT(*) AS cantidad, COALESCE(SUM(CASE WHEN estado != 'cancelado' THEN total END), 0) AS total "
        "FROM pedidos WHERE cliente_id = ?", (cliente_id,))
    pedidos = await consultar(
        "SELECT id, fecha, total, estado FROM pedidos WHERE cliente_id = ? ORDER BY fecha DESC LIMIT ?",
        (cliente_id, limite))
    return {
        "cliente_id": cliente_id,
        "cliente": cliente[0]["nombre"],
        "cantidad_pedidos": resumen[0]["cantidad"],
        "total_gastado": resumen[0]["total"],
        "pedidos": pedidos,
    }


# Pedidos que ya se consultaron en este proceso: el servicio simulado solo falla la primera vez
_envios_consultados: set[int] = set()


def reiniciar_fallas() -> None:
    _envios_consultados.clear()


@tool(args_schema=ConsultarEnvioInput)
async def consultar_envio(pedido_id: int) -> dict[str, Any]:
    """Consulta el seguimiento del envío de un pedido de Colibrí en la empresa de logística: empresa,
    código de seguimiento, estado del envío, última novedad y fecha estimada de entrega.

    Usala cuando pregunten dónde está un pedido, cuándo llega o en qué estado está el envío.
    Si devuelve un error que empieza con "TEMPORAL", el servicio de logística no respondió:
    reintentá la misma consulta. Si devuelve un "aviso", el pedido todavía no tiene envío.
    """
    filas = await consultar(
        "SELECT p.estado AS estado_pedido, e.empresa, e.codigo, e.estado, e.ultima_novedad, e.entrega_estimada "
        "FROM pedidos p LEFT JOIN envios e ON e.pedido_id = p.id WHERE p.id = ?", (pedido_id,))
    if not filas:
        return {"error": f"No existe el pedido {pedido_id}. Revisá el número con buscar_pedidos."}
    envio = filas[0]
    if envio["empresa"] is None:
        motivo = "fue cancelado" if envio["estado_pedido"] == "cancelado" else "todavía se está preparando"
        return {"pedido_id": pedido_id, "estado_pedido": envio["estado_pedido"], "envio": None,
                "aviso": f"El pedido {motivo} y no tiene envío asignado."}

    if config.SIMULAR_FALLAS and envio["empresa"] in config.EMPRESAS_INESTABLES and pedido_id not in _envios_consultados:
        _envios_consultados.add(pedido_id)
        return {"error": f"TEMPORAL: el servicio de seguimiento de {envio['empresa']} no respondió (timeout). Reintentá la consulta."}

    return {
        "pedido_id": pedido_id,
        "empresa": envio["empresa"],
        "codigo_seguimiento": envio["codigo"],
        "estado": envio["estado"],
        "ultima_novedad": envio["ultima_novedad"],
        "entrega_estimada": envio["entrega_estimada"],
    }


HERRAMIENTAS = [buscar_cliente, buscar_pedidos, consultar_envio]
