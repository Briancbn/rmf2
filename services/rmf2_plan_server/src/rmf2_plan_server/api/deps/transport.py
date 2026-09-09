from typing import Annotated

from fastapi import Depends, Request

from rmf2_plan_server.transport.amqp import AmqpServerTransport


def get_transport(request: Request) -> AmqpServerTransport:
    return request.app.state.transport


TransportDeps = Annotated[AmqpServerTransport, Depends(get_transport)]
