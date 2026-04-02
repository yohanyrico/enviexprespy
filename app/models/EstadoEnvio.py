# app/models/estado_envio.py

from enum import Enum


class EstadoEnvio(Enum):
    REGISTRADO = "Registrado"
    EN_BODEGA = "En Bodega"
    EN_RUTA = "En Ruta"
    EN_DESTINO = "En Destino"
    ENTREGADO = "Entregado"
    FALLIDO = "Fallido"

    def get_display_name(self):
        return self.value