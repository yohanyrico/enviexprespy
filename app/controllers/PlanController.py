# app/controllers/PlanController.py

import os
import uuid
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.templates import templates
from app.models.Tarifa import Tarifa
from app.models.Transaccion import Transaccion
from app.models.Usuario import Usuario

router = APIRouter(prefix="/planes", tags=["Planes"])

# ─── Vista: pantalla de pago para un plan específico ─────────────────────────
@router.get("/pago/{nombre}")
def vista_pago(nombre: str, request: Request, db: Session = Depends(get_db)):
    tarifa = db.query(Tarifa).filter(Tarifa.nombre == nombre).first()
    if not tarifa:
        return JSONResponse({"error": "Plan no encontrado"}, status_code=404)
    
    precio = tarifa.precio_plan
    cuota = tarifa.cuota  # Assuming Tarifa has a cuota field
    referencia = str(uuid.uuid4())
    
    key = os.getenv("WOMPI_PUBLIC_KEY")
    
    # 🚨 PRUEBA DE CONTROL: Si esto sale None en la consola, el .env no carga.
    print(f"DEBUG: La llave recuperada es -> {key}")
    
    # Si sale None, fuerza la llave manualmente solo para probar:
    if not key:
        key = "pub_prod_JWQ3KBYPCQXmfIdC6Frk7767EQY9XWzE" # Pon tu llave real aquí

    return templates.TemplateResponse("pago.html", {
        "request": request,
        "plan": tarifa.nombre,
        "precio": f"{precio:,}".replace(",", "."),
        "cuota": f"{cuota:,}".replace(",", "."),
        "precio_centavos": precio * 100,
        "referencia": referencia,
        "wompi_public_key": key, # Asegúrate de que este nombre coincida con el HTML
    })


# ─── POST: confirmación desde el widget de Wompi ─────────────────────────────
@router.post("/confirmar-wompi")
async def confirmar_wompi(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    transaction_id = body.get("transaction_id")
    referencia     = body.get("referencia")
    plan_nombre    = body.get("plan")
    status         = body.get("status")

    if status != "APPROVED":
        return JSONResponse({"ok": False, "mensaje": f"Estado: {status}"})

    user_id = request.session.get("user_id")
    if not user_id:
        return JSONResponse({"ok": False, "mensaje": "Sesión expirada"})

    tarifa  = db.query(Tarifa).filter(Tarifa.nombre == plan_nombre).first()
    usuario = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()

    if not tarifa or not usuario:
        return JSONResponse({"ok": False, "mensaje": "Datos no encontrados"})

    monto = tarifa.precio_plan or 0
    usuario.saldo_plan = (usuario.saldo_plan or 0) + monto

    transaccion = Transaccion(
        usuario_id=user_id,
        monto=monto,
        tipo_movimiento="CARGA",
        concepto=f"Compra plan {plan_nombre} - TX Wompi {transaction_id}",
    )
    db.add(transaccion)
    db.commit()

    return JSONResponse({"ok": True, "mensaje": "Plan activado correctamente"})


# ─── GET: página de resultado tras el pago ───────────────────────────────────
@router.get("/resultado-pago")
def resultado_pago(request: Request, status: str = "UNKNOWN", ref: str = ""):
    return templates.TemplateResponse("resultado_pago.html", {
        "request": request,
        "status": status,
        "referencia": ref,
        "aprobado": status == "APPROVED",
    })