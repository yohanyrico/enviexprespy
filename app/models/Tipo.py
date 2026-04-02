# app/models/Tipo.py

from enum import Enum


class Tipo(Enum):
    MOTO = "Moto"
    CARRO = "Carro"
    CAMIONETA = "Camioneta"
    CAMION = "Camión"
    VAN = "Van"