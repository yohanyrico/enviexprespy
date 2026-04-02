# app/config/DataInitializer.py

import bcrypt
from sqlalchemy.orm import Session
from app.models.Usuario import Usuario
from datetime import datetime


def init_database(db: Session):
    admin = db.query(Usuario).filter(Usuario.user_name == "admin").first()

    if not admin:
        hashed = bcrypt.hashpw("123".encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        admin = Usuario(
            user_name="admin",
            password=hashed,
            rol="ADMIN",
            nombre="Administrador",
            apellido="Principal",
            correo="admin@correo.com",
            activo=True,
            fecha_creacion=datetime.now(),
            telefono="3244434432"
        )
        db.add(admin)
        db.commit()
        print("✅ Usuario admin creado con éxito")
    else:
        print("ℹ️ Usuario admin ya existe")