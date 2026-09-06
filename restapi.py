#!/usr/bin/env python3
#
# responder.py: A simple OBD responder running on Linux SocketCAN/ISOTP.
#
# License:
#   Apache License, Version 2.0
# History:
#   * 2026/09/06 v0.2 Add REST API mock server for online control
# Author:
#   Masanori Itoh <masanori.itoh@gmail.com>
# TODO:
#   * Implement
from fastapi import FastAPI
from fastapi import APIRouter, Request, HTTPException, status
import uvicorn

import logging

logger = logging.getLogger(__name__)

app = FastAPI()

router = APIRouter()

methods = ['GET', 'DELETE', 'POST', 'PUT']

@router.api_route('', methods=methods)
@router.api_route('/', methods=methods)
def handle_root(request: Request):
    logger.debug('handle_root() {request}')
    #return {'item': []}
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail='Not Implemented (yet).'
    )    

@router.api_route('/{resource:path}', methods=methods)
@router.api_route('/{resource:path}/', methods=methods)
def handle_resource(request: Request, resource: str):
    logger.debug('handle_resource() {request.resource}')
    #return {'item': []}
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail='Not Implemented (yet).'
    )    

def run_api_server():
    logger.debug('run_api_server()')
    uvicorn.run(app, host='0.0.0.0', port=18082)

app.include_router(router, prefix='/admin')
