# app/security/user_details_service.py

from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from app.models.Usuario import Usuario
import app.repositories.UsuarioRepository as usuario_repo


def load_user_by_username(db: Session, username: str) -> dict:
    # Equivalente a usuarioRepository.findByUserName(username)
    # .orElseThrow(() -> new UsernameNotFoundException(...))
    usuario = usuario_repo.find_by_user_name(db, username)

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Usuario no encontrado: {username}"
        )

    if not usuario.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inactivo"
        )

    # Equivalente a new SimpleGrantedAuthority("ROLE_" + usuario.getRol())
    return {
        "username": usuario.user_name,
        "password": usuario.password,
        "rol": usuario.rol,
        "authority": f"ROLE_{usuario.rol}"
    }