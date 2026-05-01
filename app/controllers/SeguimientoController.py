from fastapi import APIRouter, Query, Request, Depends, Form
from fastapi.templating import Jinja2Templates
from typing import Optional
from sqlalchemy.orm import Session
from app.config.database import get_db
import app.repositories.EnvioRepository as envio_repo
from app.config.templates import templates

router = APIRouter(tags=["Seguimiento"])


@router.get("/seguimiento")
def seguimiento(request: Request, numero_guia: Optional[str] = Query(None), db: Session = Depends(get_db)):
    if numero_guia and numero_guia.strip():
        return _buscar(request, numero_guia, db)
    return templates.TemplateResponse("seguimiento.html", {
        "request": request,
        "encontrado": None
    })


def _buscar(request, numero_guia, db):
    # Normalizar: quitar espacios, mayúsculas, reemplazar guiones raros
    guia_limpia = (
        numero_guia
        .strip()
        .upper()
        .replace("–", "-")   # guión largo
        .replace("—", "-")   # guión em
        .replace(" ", "")    # espacios internos
    )

    envio = envio_repo.find_by_numero_guia(db, guia_limpia)
    if envio:
        return templates.TemplateResponse("seguimiento.html", {
            "request": request,
            "envio": envio,
            "encontrado": True
        })
    return templates.TemplateResponse("seguimiento.html", {
        "request": request,
        "encontrado": False,
        "mensaje": f"No se encontró ningún envío con el número de guía: {numero_guia}"
    })