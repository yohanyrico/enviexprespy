# app/controllers/PlanController.py

import os
import uuid
import hashlib
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.config.templates import templates
from app.models.Tarifa import Tarifa
from app.models.Transaccion import Transaccion
from app.models.Usuario import Usuario

router = APIRouter(prefix="/planes", tags=["Planes"])


# ─── Función auxiliar: genera la firma de integridad exigida por Wompi ───────
def generar_firma_integridad(referencia: str, monto_centavos: int, moneda: str) -> str:
    llave_secreta = os.getenv("WOMPI_INTEGRITY_SECRET")

    # 🚨 PRUEBA DE CONTROL: si sale None, la variable de entorno no está configurada en Render.
    print(f"DEBUG: WOMPI_INTEGRITY_SECRET recuperada -> {llave_secreta}")

    if not llave_secreta:
        # ⚠️ SOLO para pruebas locales. En Render, configura WOMPI_INTEGRITY_SECRET
        # en Environment Variables con tu llave real (una sola, sin mezclar prefijos).
        llave_secreta = "prod_integrity_1xyEKwVbwNOm87RjTkRRVTnGqnMXv2Dr"
        print("⚠️ ADVERTENCIA: usando llave secreta de respaldo hardcodeada. Configura WOMPI_INTEGRITY_SECRET en Render.")

    cadena = f"{referencia}{monto_centavos}{moneda}{llave_secreta}"
    firma = hashlib.sha256(cadena.encode("utf-8")).hexdigest()

    print(f"DEBUG: Cadena firmada -> {cadena}")
    print(f"DEBUG: Firma generada -> {firma}")

    return firma


# ─── Vista: pantalla de pago para un plan específico ─────────────────────────
@router.get("/pago/{nombre}")
def vista_pago(nombre: str, request: Request, db: Session = Depends(get_db)):
    tarifa = db.query(Tarifa).filter(Tarifa.nombre == nombre).first()
    if not tarifa:
        return JSONResponse({"error": "Plan no encontrado"}, status_code=404)

    precio = tarifa.precio_plan
    cuota = tarifa.cuota  # Assuming Tarifa has a cuota field
    referencia = str(uuid.uuid4())
    precio_centavos = int(precio * 100)

    key = os.getenv("WOMPI_PUBLIC_KEY")

    # 🚨 PRUEBA DE CONTROL: Si esto sale None en la consola, el .env no carga.
    print(f"DEBUG: La llave pública recuperada es -> {key}")

    if not key:
        key = "pub_test_7dp1Bc4HwBDy0I6MGSKhD5FTZX6deV8q"  # Pon tu llave real aquí

    firma_integridad = generar_firma_integridad(
        referencia=referencia,
        monto_centavos=precio_centavos,
        moneda="COP",
    )

    # 🚨 Verificación de seguridad: si por algún motivo la firma sale vacía,
    # lo vemos en los logs de inmediato en vez de fallar silenciosamente en el navegador.
    if not firma_integridad:
        print("❌ ERROR CRÍTICO: firma_integridad salió vacía antes de renderizar el template.")

    return templates.TemplateResponse("pago.html", {
        "request": request,
        "plan": tarifa.nombre,
        "precio": f"{precio:,}".replace(",", "."),
        "cuota": f"{cuota:,}".replace(",", "."),
        "precio_centavos": precio_centavos,
        "referencia": referencia,
        "wompi_public_key": key,
        "firma_integridad": firma_integridad,
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