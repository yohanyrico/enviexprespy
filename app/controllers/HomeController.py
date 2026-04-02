from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from app.security.SecurityConfig import get_current_user
from app.config.templates import templates

router = APIRouter(tags=["Home"])


@router.get("/home")
def home(request: Request, current_user=Depends(get_current_user)):
    if current_user.rol == "ADMIN":
        return templates.TemplateResponse("home.html", {
            "request": request,
            "rol": current_user.rol
        })
    elif current_user.rol == "MENSAJERO":
        return templates.TemplateResponse("home_mensajero.html", {
            "request": request,
            "rol": current_user.rol
        })
    return templates.TemplateResponse("home_cliente.html", {
        "request": request,
        "username": current_user.user_name,
        "rol": current_user.rol
    })

@router.get("/home_cliente")
def home_cliente(request: Request, current_user=Depends(get_current_user)):
    return templates.TemplateResponse("home_cliente.html", {
        "request": request,
        "username": current_user.user_name,
        "rol": current_user.rol
    })