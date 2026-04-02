# app/models/Envio.py

from sqlalchemy import Column, BigInteger, String, Numeric, Text, DateTime, Enum, ForeignKey, func
from sqlalchemy.orm import relationship, Session
from app.config.database import Base
from datetime import datetime

class Envio(Base):
    __tablename__ = "envios"

    # --- IDENTIFICADORES ---
    envio_id = Column(BigInteger, primary_key=True, autoincrement=True)
    numero_guia = Column(String(20), unique=True, index=True)

    # --- USUARIOS VINCULADOS ---
    usuario_cliente_id = Column(BigInteger, ForeignKey("usuario.id_usuario"), nullable=False)
    usuario_mensajero_id = Column(BigInteger, ForeignKey("usuario.id_usuario"), nullable=True)

    cliente = relationship("Usuario", foreign_keys=[usuario_cliente_id], back_populates="envios_como_cliente")
    mensajero = relationship("Usuario", foreign_keys=[usuario_mensajero_id], back_populates="envios_como_mensajero")

    # --- DIRECCIONES / LUGARES ---
    lugar_recogida_id = Column(BigInteger, ForeignKey("lugares.lugar_id"), nullable=True)
    lugar_entrega_id = Column(BigInteger, ForeignKey("lugares.lugar_id"), nullable=True)

    lugar_recogida = relationship("Lugar", foreign_keys=[lugar_recogida_id], back_populates="envios_recogida")
    lugar_entrega = relationship("Lugar", foreign_keys=[lugar_entrega_id], back_populates="envios_entrega")

    # --- DATOS TÉCNICOS ---
    peso = Column(Numeric(10, 2), nullable=False, default=0.00)
    costo_envio = Column(Numeric(10, 2), default=0.00)
    instrucciones = Column(Text, nullable=True)
    fecha_creacion = Column(DateTime, nullable=False, default=datetime.now)

    tipo_servicio = Column(
        Enum("BASICA", "EXPRESS", name="tiposervicio", native_enum=False),
        nullable=False,
        default="BASICA"
    )
    
    estado = Column(
        Enum("Registrado", "En_Bodega", "En_Ruta", "En_Destino", "Entregado", "Fallido",
            name="estadoenvio", native_enum=False),
        nullable=False,
        default="Registrado"
    )

    # --- RELACIONES EXTERNAS ---
    tarifa_id = Column(BigInteger, ForeignKey("tarifas.id"), nullable=True)
    tarifa = relationship("Tarifa", back_populates="envios") 

    ruta_id = Column(BigInteger, ForeignKey("rutas.ruta_id"), nullable=True)
    ruta = relationship("Ruta", back_populates="envios")

    vehiculo_id = Column(BigInteger, ForeignKey("vehiculo.vehiculo_id"), nullable=True)
    vehiculo = relationship("Vehiculo", back_populates="envios")

    seguimientos = relationship(
        "Seguimiento", 
        back_populates="envio", 
        cascade="all, delete-orphan"
    )

    # --- FUNCIONES DE REPORTE (LÓGICA DE NEGOCIO) ---

    @classmethod
    def obtener_datos_reporte(cls, db: Session, ids: list = None):
        """
        Retorna los registros para el reporte de envíos. 
        Si se pasan IDs, filtra por selección, sino trae todos.
        """
        query = db.query(cls)
        if ids:
            query = query.filter(cls.envio_id.in_(ids))
        return query.all()

    @classmethod
    def obtener_reporte_usuarios(cls, db: Session):
        """
        Extrae la lista de usuarios del sistema para el reporte de directorio.
        Utiliza importación local para evitar errores de importación circular.
        """
        from app.models.Usuario import Usuario
        return db.query(Usuario).all()

    @classmethod
    def obtener_metricas_totales(cls, db: Session, ids: list = None):
        """
        Calcula la suma de costos para el cuadro 'Resumen' del reporte.
        """
        query = db.query(func.sum(cls.costo_envio))
        if ids:
            query = query.filter(cls.envio_id.in_(ids))
        
        resultado = query.scalar()
        return float(resultado) if resultado else 0.00