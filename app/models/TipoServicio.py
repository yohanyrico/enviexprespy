# app/models/tipo_servicio.py

from enum import Enum


class TipoServicio(Enum):
    BASICA = "BASICA"
    EXPRESS = "EXPRESS"