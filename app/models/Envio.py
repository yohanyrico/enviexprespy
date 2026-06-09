from sqlalchemy import Column, BigInteger, String, Numeric, Text, DateTime, Enum, ForeignKey, func, Boolean
from sqlalchemy.orm import relationship, Session
from app.config.database import Base
from datetime import datetime

from app.models.Seguimiento import Seguimiento
from app.models.EnvioItemInventario import EnvioItemInventario
class Envio(Base):
    __tablename__ = "envios"

    envio_id = Column(BigInteger, primary_key=True, autoincrement=True)
    numero_guia = Column(String(20), unique=True, index=True)

    usuario_cliente_id = Column(BigInteger, ForeignKey("usuario.id_usuario"), nullable=False)
    usuario_mensajero_id = Column(BigInteger, ForeignKey("usuario.id_usuario"), nullable=True)
    usuario_mensajero_entrega_id = Column(BigInteger, ForeignKey("usuario.id_usuario"), nullable=True)

    # Relaciones mapeadas bidireccionalmente de forma exacta con Usuario.py
    cliente = relationship("Usuario", foreign_keys=[usuario_cliente_id], back_populates="envios_como_cliente")
    mensajero = relationship("Usuario", foreign_keys=[usuario_mensajero_id], back_populates="envios_como_mensajero")
    mensajero_entrega = relationship("Usuario", foreign_keys=[usuario_mensajero_entrega_id], back_populates="envios_como_mensajero_entrega")

    lugar_recogida_id = Column(BigInteger, ForeignKey("lugares.lugar_id"), nullable=True)
    lugar_entrega_id  = Column(BigInteger, ForeignKey("lugares.lugar_id"), nullable=True)

    lugar_recogida = relationship("Lugar", foreign_keys=[lugar_recogida_id], back_populates="envios_recogida")
    lugar_entrega  = relationship("Lugar", foreign_keys=[lugar_entrega_id],  back_populates="envios_entrega")

    peso        = Column(Numeric(10, 2), nullable=False, default=0.00)
    costo_envio = Column(Numeric(10, 2), default=0.00)
    instrucciones = Column(Text, nullable=True)
    fecha_creacion = Column(DateTime, nullable=False, default=datetime.now)

    # Fotos de evidencia para el seguimiento en Bogotá
    foto_recogida = Column(String(255), nullable=True)   # Foto al recoger el paquete
    foto_entrega  = Column(String(255), nullable=True)   # Foto al entregar el paquete
    fecha_en_bodega = db.Column(db.DateTime, nullable=True)  # 👈 AGREGAR

    es_cod         = Column(Boolean, default=False)
    valor_a_cobrar = Column(Numeric(12, 2), default=0.00)

    tipo_servicio = Column(
        Enum("BASICA", "EXPRESS", "NACIONAL", name="tiposervicio", native_enum=False),
        nullable=False, default="BASICA"
    )

    # Estado principal del envío — flujo completo
    estado = Column(
        Enum(
            "Registrado",
            "Pendiente_Recoger",
            "Colectado",
            "C-Colectado",
            "Pendiente_Verificar",
            "En_Bodega",
            "En_Ruta",
            "En_Destino",
            "Entregado",
            "Cancelado",
            "Devolucion",
            "Retorno",
            "Rechazado",
            "Fallido",
            name="estadoenvio", native_enum=False
        ),
        nullable=False, default="Registrado"
    )

    # Estados independientes por punto (recogida y entrega)
    estado_recogida = Column(
        Enum("Pendiente", "En_Ruta", "Colectado", "Cancelado",
             name="estadorecogida", native_enum=False),
        nullable=False, default="Pendiente"
    )
    estado_entrega = Column(
        Enum("Pendiente", "En_Ruta", "En_Destino", "Entregado", "Cancelado",
             name="estadoentrega", native_enum=False),
        nullable=False, default="Pendiente"
    )

    tarifa_id = Column(BigInteger, ForeignKey("tarifas.id"), nullable=True)
    tarifa = relationship("Tarifa", back_populates="envios")

    ruta_id = Column(BigInteger, ForeignKey("rutas.ruta_id"), nullable=True)
    ruta = relationship("Ruta", back_populates="envios", foreign_keys=[ruta_id])

    vehiculo_id = Column(BigInteger, ForeignKey("vehiculo.vehiculo_id"), nullable=True)
    vehiculo = relationship("Vehiculo", back_populates="envios")

    # 👇 Ya mapeado correctamente, ahora sí encuentra la clase 'Seguimiento'
    seguimientos = relationship(
        "Seguimiento",
        back_populates="envio",
        cascade="all, delete-orphan"
    )
    
    # 👇 Ya mapeado correctamente, ahora sí encuentra la clase 'EnvioItemInventario'
    items_inventario = relationship(
        "EnvioItemInventario",
        back_populates="envio",
        cascade="all, delete-orphan"
    )

    @classmethod
    def generar_numero_guia(cls, db: Session) -> str:
        ultima_guia = (
            db.query(cls.numero_guia)
            .filter(cls.numero_guia.isnot(None))
            .order_by(cls.envio_id.desc())
            .first()
        )
        if ultima_guia and ultima_guia[0]:
            try:
                texto_guia = ultima_guia[0]
                numero_str = "".join(filter(str.isdigit, texto_guia))
                ultimo_numero = int(numero_str)
                nuevo_numero = ultimo_numero + 1
                return f"ENV{nuevo_numero:05d}"
            except (ValueError, IndexError):
                pass
        return "ENV00001"

    @classmethod
    def obtener_datos_reporte(cls, db: Session, ids: list = None):
        query = db.query(cls)
        if ids:
            query = query.filter(cls.envio_id.in_(ids))
        return query.all()

    @classmethod
    def obtener_reporte_usuarios(cls, db: Session):
        from app.models.Usuario import Usuario
        return db.query(Usuario).all()

    @classmethod
    def obtener_metricas_totales(cls, db: Session, ids: list = None):
        query = db.query(func.sum(cls.costo_envio))
        if ids:
            query = query.filter(cls.envio_id.in_(ids))
        resultado = query.scalar()
        return float(resultado) if resultado else 0.00