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
SECRET_KEY = "tu_clave_secreta_super_segura_2026" # Cambia esto por algo único
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 1 día de duración

# Esto permite que Swagger y FastAPI lean el token de la cabecera Authorization
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/login", auto_error=False)

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

# --- NUEVA FUNCIÓN: CREAR TOKEN JWT ---

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# --- FUNCIÓN CORREGIDA: OBTENER USUARIO ACTUAL (SOPORTA SESIÓN Y TOKEN) ---

def get_current_user(
    request: Request, 
    db: Session = Depends(get_db), 
    token: str = Depends(oauth2_scheme)
) -> Usuario:
    username = None
    
    # 1. Intentar por Sesión (Navegador Web)
    username = request.session.get("username")
    
    # 2. Si no hay sesión, intentar por Token (App Flutter)
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

# --- FUNCIONES DE ROLES ---

def require_admin(usuario: Usuario):
    if usuario.rol != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Se requiere rol ADMIN"
        )

def require_admin_or_mensajero(usuario: Usuario):
    if usuario.rol not in ["ADMIN", "MENSAJERO"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado"
        )