import bcrypt
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.config.database import get_db
from app.models.Usuario import Usuario
import app.repositories.UsuarioRepository as usuario_repo

# --- CONFIGURACIÓN JWT ---
SECRET_KEY = "tu_clave_secreta_super_segura_2026"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 1 día

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login", auto_error=False)

# ─────────────────────────────────────────────
# ROLES DISPONIBLES EN EL SISTEMA
# ─────────────────────────────────────────────
# CEO          → Acceso total (finanzas + operativo + configuración)
# FACTURACION  → Acceso total igual que CEO (excepto gestión de otros CEO)
# ADMINISTRATIVO → Operativo sin módulo financiero
# CLIENTE      → Solo sus propios envíos y reporte financiero de su cuenta
# MENSAJERO    → App móvil + mapa operaciones
# ─────────────────────────────────────────────

ROLES_FINANCIEROS   = {"CEO", "FACTURACION"}
ROLES_OPERATIVOS    = {"CEO", "FACTURACION", "ADMINISTRATIVO"}
ROLES_SOLO_CEO      = {"CEO"}  # configuración del sistema, gestión de otros CEO


# --- FUNCIONES DE CONTRASEÑA ---

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

def authenticate_user(db: Session, user_name: str, password: str) -> Usuario | None:
    user = usuario_repo.find_by_user_name(db, user_name)
    if not user or not verify_password(password, user.password):
        return None
    return user


# --- TOKEN JWT ---

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# --- OBTENER USUARIO ACTUAL (sesión web + token Flutter) ---

def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> Usuario:
    username = request.session.get("username")

    if not username and token:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username = payload.get("sub")
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido o expirado"
            )

    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado"
        )

    user = usuario_repo.find_by_user_name(db, username)
    if not user or not user.activo:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario inactivo o no encontrado"
        )
    return user


# ─────────────────────────────────────────────
# FUNCIONES DE CONTROL DE ROLES
# ─────────────────────────────────────────────

def require_admin(usuario: Usuario):
    """
    Compatibilidad: acepta CEO, FACTURACION y ADMINISTRATIVO.
    Reemplaza todos los require_admin() anteriores que usaban 'ADMIN'.
    """
    if usuario.rol not in ROLES_OPERATIVOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Se requiere rol operativo."
        )

def require_financiero(usuario: Usuario):
    """Solo CEO y FACTURACION pueden acceder al módulo financiero."""
    if usuario.rol not in ROLES_FINANCIEROS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Se requiere rol CEO o FACTURACION."
        )

def require_ceo(usuario: Usuario):
    """Solo CEO puede acceder a configuración del sistema y gestión de otros CEO."""
    if usuario.rol not in ROLES_SOLO_CEO:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Se requiere rol CEO."
        )

def require_operativo(usuario: Usuario):
    """CEO, FACTURACION y ADMINISTRATIVO pueden acceder a operaciones."""
    if usuario.rol not in ROLES_OPERATIVOS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Se requiere rol operativo."
        )

def require_admin_or_mensajero(usuario: Usuario):
    """CEO, FACTURACION, ADMINISTRATIVO y MENSAJERO."""
    if usuario.rol not in {*ROLES_OPERATIVOS, "MENSAJERO"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado."
        )

def is_financiero(usuario: Usuario) -> bool:
    """Helper booleano para usar en templates o lógica condicional."""
    return usuario.rol in ROLES_FINANCIEROS

def is_operativo(usuario: Usuario) -> bool:
    """Helper booleano: True para CEO, FACTURACION, ADMINISTRATIVO."""
    return usuario.rol in ROLES_OPERATIVOS