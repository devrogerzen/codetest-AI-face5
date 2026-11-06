"""Prueba de ejecución del agente: una conversación armada para mostrar el razonamiento multi-paso,
el reintento ante errores, el pedido de aclaraciones y la memoria por thread_id.

Guarda la traza en trazas/ como .json y .log.

Uso:
    python demo.py              # con el LLM del .env  -> trazas/demo.json y trazas/demo.log
    python demo.py --sin-api    # modelo simulado      -> trazas/demo_sin_api.json y .log
"""
import argparse
import asyncio
import sys

from dotenv import load_dotenv

from agente import abrir_agente, guardar_traza
from config import TRAZAS, resumir_error
from herramientas import reiniciar_fallas

# (thread_id, pregunta). Los threads se repiten a propósito para probar la memoria.
CONVERSACION = [
    # Pedidos y total de un cliente (el ejemplo de la consigna) + seguimiento con contexto
    ("pedidos-102", "¿Cuántos pedidos tuvo el cliente 102 y cuál fue el total?"),
    ("pedidos-102", "¿Y el último?"),
    ("pedidos-102", "¿En qué estado está el envío de ese pedido?"),
    # Multi-paso en una sola pregunta: cliente -> pedidos -> envío
    ("envio-julian", "¿Dónde está el último pedido de Julián Pereyra y cuándo llega?"),
    # Nombre ambiguo: el agente pregunta y sigue con la aclaración
    ("envio-lucia", "¿En qué estado está el envío del último pedido de Lucía Fernández?"),
    ("envio-lucia", "La de Mendoza"),
    # Thread nuevo: no sabe de qué le hablan
    ("thread-nuevo", "¿Y el último?"),
]


async def main(sin_api: bool) -> None:
    reiniciar_fallas()
    async with abrir_agente(sin_api=sin_api) as agente:
        for thread_id in {t for t, _ in CONVERSACION}:
            await agente.olvidar(thread_id)   # cada corrida de la demo arranca de cero

        print(f"Modelo: {agente.modelo} · recursion_limit={agente.recursion_limit}\n")
        turnos = []
        for thread_id, pregunta in CONVERSACION:
            turnos.append(await agente.preguntar(pregunta, thread_id))
            print()

    destino = TRAZAS / ("demo_sin_api" if sin_api else "demo")
    guardar_traza(turnos, destino, agente.modelo, agente.recursion_limit)
    llamadas = sum(len(t.llamadas) for t in turnos)
    print(f"{len(turnos)} turnos, {llamadas} llamadas a herramientas. Traza en {destino.with_suffix('.json').name} "
          f"y {destino.with_suffix('.log').name}")


if __name__ == "__main__":
    load_dotenv()
    sys.stdout.reconfigure(encoding="utf-8")
    argumentos = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    argumentos.add_argument("--sin-api", action="store_true", help="usa el modelo simulado, sin keys")
    try:
        asyncio.run(main(argumentos.parse_args().sin_api))
    except Exception as e:
        print(f"Error de {resumir_error(e)}")
