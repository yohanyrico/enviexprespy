# app/controllers/EnvioController.py
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, Form
from fastapi.responses import RedirectResponse, HTMLResponse, StreamingResponse, JSONResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import text
from datetime import datetime
from decimal import Decimal
from typing import Optional
import io
import pandas as pd
from fpdf import FPDF

# Librería para el Mapa (Geocoding)
from geopy.geocoders import Nominatim

from app.config.database import get_db
from app.models.Envio import Envio
from app.models.Lugar import Lugar
from app.models.Usuario import Usuario
from app.models.Transaccion import Transaccion 
from app.models.Tarifa import Tarifa
from app.security.SecurityConfig import get_current_user, require_admin, require_admin_or_mensajero
import app.repositories.EnvioRepository as envio_repo
import app.repositories.UsuarioRepository as usuario_repo
import app.repositories.VehiculoRepository as vehiculo_repo
import app.repositories.TarifaRepository as tarifa_repo
import app.repositories.RutaRepository as ruta_repo
import app.repositories.LugarRepository as lugar_repo
from app.config.templates import templates

router = APIRouter(prefix="/envios", tags=["Envíos"])

# --- CLASE PDF PARA REPORTES ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'ENVIEXPRESS S.A.S - REPORTE OPERATIVO', 0, 1, 'C')
        self.set_font('Arial', 'I', 10)
        self.cell(0, 10, f'Generado el: {datetime.now().strftime("%d/%m/%Y %H:%M")}', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Página {self.page_no()}', 0, 0, 'C')

# --- FUNCIÓN DE CONSECUTIVO PROFESIONAL ---
def generar_nuevo_consecutivo(db: Session):
    try:
        res = db.execute(text("SELECT ultimo_consecutivo FROM configuracion WHERE id = 1 FOR UPDATE")).fetchone()
        if not res:
            nuevo_numero = 1
            db.execute(text("INSERT INTO configuracion (id, ultimo_consecutivo) VALUES (1, 1)"))
        else:
            nuevo_numero = res[0] + 1
            db.execute(text("UPDATE configuracion SET ultimo_consecutivo = :num WHERE id = 1"), {"num": nuevo_numero})
        return f"ENV-{nuevo_numero:05d}"
    except Exception as e:
        print(f"Error consecutivo: {e}")
        return f"ENV-{datetime.now().strftime('%M%S')}"

# --- FUNCIÓN AUXILIAR GPS ---
def obtener_coordenadas(direccion, ciudad):
    try:
        geolocator = Nominatim(user_agent="enviexpress_bogota_v2")
        query = f"{direccion}, {ciudad}, Colombia"
        location = geolocator.geocode(query, timeout=10)
        if location:
            return location.latitude, location.longitude
    except Exception as e:
        print(f"Log Error GPS: {e}")
    return None, None

# --- LISTADO PRINCIPAL (ADMIN) ---
@router.get("/")
def listar(request: Request, db: Session = Depends(get_db)):
    query = db.query(Envio).options(
        joinedload(Envio.cliente),
        joinedload(Envio.mensajero),
        joinedload(Envio.tarifa),
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega)
    )
    envios = query.all()
    mensajeros = db.query(Usuario).filter(Usuario.rol == "MENSAJERO").all()
    
    return templates.TemplateResponse("envios.html", {
        "request": request,
        "envios": envios,
        "mensajeros": mensajeros,
        "rol": "ADMIN"
    })

# --- LISTADO FILTRADO DINÁMICO ---
@router.get("/mis-guias")
def listar_mis_guias(request: Request, db: Session = Depends(get_db)):
    user_id = request.session.get("user_id")
    if not user_id:
        return RedirectResponse(url="/login?error=expired")

    usuario = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
    if not usuario:
        return RedirectResponse(url="/login")

    mis_envios = db.query(Envio).filter(Envio.usuario_cliente_id == usuario.id_usuario).options(
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega),
        joinedload(Envio.tarifa)
    ).all()

    historial_pagos = db.query(Transaccion).filter(
        Transaccion.usuario_id == usuario.id_usuario
    ).order_by(Transaccion.fecha_creacion.desc()).limit(10).all()

    return templates.TemplateResponse("envios_cliente.html", {
        "request": request,
        "envios": mis_envios,
        "transacciones": historial_pagos,
        "username": usuario.user_name,
        "rol": usuario.rol,
        "current_user": usuario 
    })

# --- VISTA NUEVO ENVÍO ---
@router.get("/nuevo")
def nuevo(request: Request, db: Session = Depends(get_db)):
    try:
        username_session = request.session.get("username")
        usuario_actual = db.query(Usuario).filter(Usuario.user_name == username_session).first()
        
        if not usuario_actual:
            return RedirectResponse(url="/login")

        datos = _cargar_datos_formulario(db)
        
        if usuario_actual.rol != 'ADMIN':
            datos['clientes'] = [usuario_actual]
            plan_usuario = usuario_actual.rol.strip() 
            tarifa_filtrada = [t for t in datos['tarifas'] if t.nombre.strip() == plan_usuario]
            if tarifa_filtrada:
                datos['tarifas'] = tarifa_filtrada

        return templates.TemplateResponse("form-envio.html", {
            "request": request, 
            "envio": None, 
            "rol": usuario_actual.rol,
            "current_user": usuario_actual,
            **datos
        })
    except Exception as e:
        print(f"Error en /nuevo: {e}")
        raise HTTPException(status_code=500, detail="Error interno")

# --- GUARDAR / ACTUALIZAR ---
@router.post("/guardar")
async def guardar(request: Request, db: Session = Depends(get_db)):
    try:
        form = await request.form()
        envio_id = form.get("envio_id")
        es_nuevo = not (envio_id and envio_id.strip())
        
        username_session = request.session.get("username")
        cliente = db.query(Usuario).filter(Usuario.user_name == username_session).first()
        
        if not cliente:
            return RedirectResponse(url="/login")

        # --- LÓGICA COD ---
        es_cod = form.get("es_cod") == "on"
        valor_a_cobrar = Decimal(form.get("valor_a_cobrar") or "0") if es_cod else Decimal("0")

        depto_entrega = form.get("depto_entrega", "").upper()
        ciudad_entrega = form.get("ciudad_entrega", "").upper()
        es_bogota = "BOGOTÁ" in depto_entrega or "BOGOTÁ" in ciudad_entrega

        obs_cliente = form.get("instrucciones_especiales", "").strip()
        contenido = form.get("descripcion", "").strip()
        instrucciones_finales = f"CONTENIDO: {contenido} | OBS: {obs_cliente}"

        if es_nuevo:
            if not es_bogota:
                tarifa_nac = db.query(Tarifa).filter(Tarifa.nombre.ilike("%Nacional%") | Tarifa.nombre.ilike("%Raíces%")).first()
                costo = tarifa_nac.precio_kg if tarifa_nac else Decimal("17990")
                tar_id = tarifa_nac.id if tarifa_nac else None
            else:
                costo = cliente.cuota_fija
                tarifa_urb = db.query(Tarifa).filter(Tarifa.nombre.ilike(f"%{cliente.rol}%")).first()
                tar_id = tarifa_urb.id if tarifa_urb else None

            if cliente.saldo_plan < costo:
                return RedirectResponse(url="/envios/mis-guias?error=saldo_insuficiente", status_code=303)

            envio = Envio(
                numero_guia=generar_nuevo_consecutivo(db),
                usuario_cliente_id=cliente.id_usuario,
                fecha_creacion=datetime.now(),
                estado="Registrado",
                costo_envio=costo,
                tipo_servicio="EXPRESS" if es_bogota else "NACIONAL",
                instrucciones=instrucciones_finales,
                peso=Decimal(form.get("peso", "1.0")),
                tarifa_id=tar_id,
                es_cod=es_cod,
                valor_a_cobrar=valor_a_cobrar
            )
            
            cliente.saldo_plan -= costo
            db.add(envio); db.flush() 
            
            db.add(Transaccion(
                usuario_id=cliente.id_usuario,
                envio_id=envio.envio_id,
                tipo_movimiento='DESCUENTO',
                monto=-costo,
                concepto=f"Pago {'Nacional' if not es_bogota else 'Urbano'} Guía {envio.numero_guia}",
                fecha_creacion=datetime.now()
            ))
        else:
            envio = envio_repo.find_by_id(db, int(envio_id))
            envio.instrucciones = instrucciones_finales
            envio.es_cod = es_cod
            envio.valor_a_cobrar = valor_a_cobrar

        for tipo in ["recogida", "entrega"]:
            ciudad = form.get(f"ciudad_{tipo}", "")
            depto = form.get(f"depto_{tipo}", "")
            direccion = form.get(f"direccion_{tipo}", "").strip()
            telefono = form.get(f"telefono_{tipo}", "").strip()
            localidad = form.get(f"localidad_{tipo}", "").strip()

            if direccion:
                referencia_final = f"Localidad: {localidad} | Tel: {telefono}" if localidad else f"Tel: {telefono}"
                lat, lng = obtener_coordenadas(direccion, ciudad)

                lugar = Lugar(
                    direccion=direccion, 
                    ciudad=f"{ciudad} ({depto})", 
                    referencia=referencia_final,
                    latitud=lat,
                    longitud=lng
                )
                db.add(lugar); db.flush()
                
                if tipo == "recogida": 
                    envio.lugar_recogida_id = lugar.lugar_id
                else: 
                    envio.lugar_entrega_id = lugar.lugar_id

        db.commit()
        return RedirectResponse(url="/envios/mis-guias", status_code=302)

    except Exception as e:
        db.rollback()
        print(f"Error crítico en guardar: {e}")
        return RedirectResponse(url="/envios/mis-guias?error=error_proceso")

# --- ELIMINAR ---
@router.get("/eliminar/{id}")
def eliminar(id: int, db: Session = Depends(get_db)):
    try:
        envio = envio_repo.find_by_id(db, id)
        cliente = db.query(Usuario).filter(Usuario.id_usuario == envio.usuario_cliente_id).first()
        if cliente and envio.costo_envio > 0:
            cliente.saldo_plan += envio.costo_envio
            db.add(Transaccion(usuario_id=cliente.id_usuario, tipo_movimiento='REEMBOLSO', monto=envio.costo_envio, concepto=f"Reembolso Guía {envio.numero_guia}", fecha_creacion=datetime.now()))
        db.delete(envio); db.commit() 
        return RedirectResponse(url="/envios/mis-guias", status_code=303)
    except Exception as e:
        db.rollback(); return RedirectResponse(url="/envios/mis-guias?error=db_error")

# --- IMPRESIÓN ---
@router.get("/imprimir/{id}")
def imprimir_guia(id: int, request: Request, db: Session = Depends(get_db)):
    envio = db.query(Envio).options(
        joinedload(Envio.lugar_recogida),
        joinedload(Envio.lugar_entrega),
        joinedload(Envio.cliente)
    ).filter(Envio.envio_id == id).first()

    if not envio:
        raise HTTPException(status_code=404, detail="Guía no encontrada")

    return templates.TemplateResponse("imprimir_guia.html", {
        "request": request,
        "envio": envio,
        "fecha_actual": datetime.now().strftime("%d/%m/%Y %H:%M")
    })

# --- REPORTE (PDF/CSV) ---
@router.get("/reporte")
def generar_reporte(formato: str = Query("csv"), ids: Optional[str] = None, db: Session = Depends(get_db)):
    try:
        query = db.query(Envio).options(joinedload(Envio.cliente), joinedload(Envio.lugar_entrega))
        
        if ids:
            lista_ids = [int(i) for i in ids.split(",") if i.strip()]
            query = query.filter(Envio.envio_id.in_(lista_ids))
        
        envios = query.all()

        data = []
        for e in envios:
            ref = (e.lugar_entrega.referencia or "").upper()
            localidad = ref.split('LOCALIDAD:')[1].split('|')[0].strip() if 'LOCALIDAD:' in ref else "BOGOTÁ D.C."
            
            data.append({
                "Guia": str(e.numero_guia),
                "Fecha": e.fecha_creacion.strftime('%d/%m/%Y'),
                "Cliente": f"{e.cliente.nombre} {e.cliente.apellido}"[:30] if e.cliente else "N/A",
                "Localidad": localidad[:20],
                "Direccion": (e.lugar_entrega.direccion or "N/A")[:35],
                "Estado": str(e.estado),
                "Valor": f"{float(e.costo_envio):,.0f}"
            })

        if formato == "csv":
            df = pd.DataFrame(data)
            output = io.StringIO()
            df.to_csv(output, index=False, encoding='utf-8-sig')
            return Response(
                content=output.getvalue(),
                media_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=reporte_enviexpress.csv"}
            )

        elif formato == "pdf":
            pdf = PDF(orientation='L', unit='mm', format='A4')
            pdf.add_page()
            
            pdf.set_fill_color(255, 140, 0)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font('Arial', 'B', 10)
            
            cols = [("Guia", 30), ("Fecha", 25), ("Cliente", 50), ("Localidad", 40), ("Direccion", 70), ("Estado", 30), ("Valor", 30)]
            for col in cols:
                pdf.cell(col[1], 10, col[0], 1, 0, 'C', True)
            pdf.ln()
            
            pdf.set_text_color(0, 0, 0)
            pdf.set_font('Arial', '', 9)
            
            for row in data:
                pdf.cell(30, 8, row["Guia"].encode('latin-1', 'replace').decode('latin-1'), 1)
                pdf.cell(25, 8, row["Fecha"], 1)
                pdf.cell(50, 8, row["Cliente"].encode('latin-1', 'replace').decode('latin-1'), 1)
                pdf.cell(40, 8, row["Localidad"].encode('latin-1', 'replace').decode('latin-1'), 1)
                pdf.cell(70, 8, row["Direccion"].encode('latin-1', 'replace').decode('latin-1'), 1)
                pdf.cell(30, 8, row["Estado"], 1)
                pdf.cell(30, 8, f"$ {row['Valor']}", 1)
                pdf.ln()

            response_content = pdf.output(dest='S')
            return Response(
                content=bytes(response_content),
                media_type="application/pdf",
                headers={"Content-Disposition": "attachment; filename=reporte_enviexpress.pdf"}
            )

    except Exception as e:
        print(f"Error Crítico Reporte: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

# --- EDITAR ---
@router.get("/editar/{id}")
def editar(id: int, request: Request, db: Session = Depends(get_db)):
    envio = envio_repo.find_by_id(db, id)
    if not envio:
        raise HTTPException(status_code=404, detail="No existe")
    datos = _cargar_datos_formulario(db)
    user_id = request.session.get("user_id")
    usuario_actual = db.query(Usuario).filter(Usuario.id_usuario == user_id).first()
    return templates.TemplateResponse("form-envio.html", {
        "request": request, "envio": envio, "rol": usuario_actual.rol, "current_user": usuario_actual, **datos
    })

def _cargar_datos_formulario(db: Session):
    lista_clientes = db.query(Usuario).filter(Usuario.rol == "CLIENTE").all()
    print(f"DEBUG: Se encontraron {len(lista_clientes)} clientes en la base de datos.")
    
    return {
        "clientes": lista_clientes,
        "tarifas": db.query(Tarifa).all(),
        "estados": ["Registrado", "En_Bodega", "En_Ruta", "Entregado"]
    }   

@router.get("/puntos-mapa")
def obtener_puntos_mapa(db: Session = Depends(get_db)):
    envios = db.query(Envio).join(Envio.lugar_entrega).filter(
        Envio.ruta_id == None,
        Lugar.latitud != None,
        Lugar.longitud != None
    ).all()
    
    puntos = []
    for e in envios:
        puntos.append({
            "id": e.envio_id,
            "guia": e.numero_guia,
            "lat": float(e.lugar_entrega.latitud),
            "lng": float(e.lugar_entrega.longitud),
            "direccion": e.lugar_entrega.direccion,
            "cliente": f"{e.cliente.nombre} {e.cliente.apellido}"
        })
    return puntos

@router.get("/planificar-ruta")
def planificar_ruta(request: Request, db: Session = Depends(get_db)):
    try:
        envios = db.query(Envio).options(
            joinedload(Envio.tarifa),
            joinedload(Envio.lugar_recogida),
            joinedload(Envio.lugar_entrega),
            joinedload(Envio.cliente)
        ).filter(Envio.ruta_id == None).all()

        mensajeros = db.query(Usuario).filter(Usuario.rol == "MENSAJERO").all()
        rutas_activas = db.query(Usuario).filter(Usuario.rol == "MENSAJERO").all()

        return templates.TemplateResponse("mapa_operativo.html", {
            "request": request,
            "envios": envios,
            "mensajeros": mensajeros,
            "rutas_activas": rutas_activas,
            "rol": "ADMIN"
        })
    except Exception as e:
        print(f"Error cargando mapa: {e}")
        return RedirectResponse(url="/envios?error=mapa")

@router.post("/asignar-mensajero-masivo")
async def asignar_masivo(data: dict, db: Session = Depends(get_db)):
    return {"status": "ok"}