from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from datetime import datetime
from zoneinfo import ZoneInfo
import os

def ahora_mexico():
    return datetime.now(ZoneInfo("America/Mexico_City"))

app = Flask(__name__)
CORS(app)

# =========================
# CONFIGURACIÓN DE MONGODB
# =========================
MONGO_URI = os.environ.get("MONGO_URI")

cliente = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = cliente["Estacionamiento"]

usuarios = db["usuarios"]
entrada = db["entrada"]
ia = db["ia"]

TOTAL_LUGARES = 20

try:
    usuarios.create_index("correo", unique=True)
    print("Conexión a MongoDB exitosa ✅")
except Exception as e:
    print("Error Mongo:", e)

# =========================
# API
# =========================
@app.route("/", methods=["GET"])
def inicio():
    return jsonify({"mensaje": "API funcionando 🔥"})

# --- REGISTRO ---
@app.route("/usuarios", methods=["POST"])
def crear_usuario():
    try:
        datos = request.json
        nombre = datos.get("nombre")
        correo = datos.get("correo")
        password = datos.get("password")
        rol = datos.get("rol", "usuario") # Permite enviar rol desde el JSON

        if not nombre or not correo or not password:
            return jsonify({"success": False, "mensaje": "Faltan datos"}), 400

        if usuarios.find_one({"correo": correo}):
            return jsonify({"success": False, "mensaje": "El correo ya existe"}), 409

        if usuarios.find_one({"nombre": nombre}):
            return jsonify({"success": False, "mensaje": "El nombre de usuario ya existe"}), 409
            
        nuevo_usuario = {
            "nombre": nombre,
            "correo": correo,
            "password": password, # Se guarda como texto normal
            "rol": rol,
            "fecha_registro": ahora_mexico()
        }

        usuarios.insert_one(nuevo_usuario)
        return jsonify({"success": True, "mensaje": "Usuario creado correctamente"}), 201
    except Exception as e:
        return jsonify({"success": False, "mensaje": str(e)}), 500

# =========================
# LOGIN
# =========================
@app.route("/login", methods=["POST"])
def login():

    datos = request.json
    correo = datos.get("correo")
    password = datos.get("password")

    usuario = usuarios.find_one({
        "correo": correo,
        "password": password
    })

    if usuario:
        return jsonify({
            "success": True,
            "usuario": {
                "id": str(usuario["_id"]),
                "nombre": usuario["nombre"],
                "correo": usuario["correo"],
                "rol": usuario.get("rol", "usuario")
            }
        })

    return jsonify({"success": False}), 401


# =========================
# VERIFICAR ESPACIO
# =========================
@app.route("/contador-entrada", methods=["POST"])
def contador_entrada():

    ocupados = ia.count_documents({"estado": "Entrada"})

    if ocupados >= TOTAL_LUGARES:
        return jsonify({
            "success": False,
            "message": "🚫 Estacionamiento lleno"
        }), 403

    return jsonify({
        "success": True,
        "ocupados": ocupados
    })


# =========================
# ENTRADA MANUAL
# =========================
@app.route("/entrada-manual", methods=["POST"])
def entrada_manual():

    ocupados = ia.count_documents({"estado": "Entrada"})

    if ocupados >= TOTAL_LUGARES:
        return jsonify({
            "success": False,
            "message": "🚫 Estacionamiento lleno"
        }), 403

    datos = request.json
    placa = datos.get("placa")

    if not placa:
        return jsonify({
            "success": False,
            "message": "Placa requerida"
        }), 400

    import uuid
    token = str(uuid.uuid4())  # 🔥 GENERAMOS QR TAMBIÉN PARA MANUAL

    nuevo = {
        "qrToken": token,              # 🔥 CLAVE
        "placa": placa,
        "horaEntrada": ahora_mexico()
        "horaSalida": None,
        "estado": "dentro",
        "precio": 0,
        "pagado": False,
        "metodoPago": None,
        "tipo": "manual"
    }

    entrada.insert_one(nuevo)

    return jsonify({
        "success": True,
        "qrToken": token,  # 🔥 opcional, por si luego quieres mostrarlo
        "message": "Vehículo registrado correctamente"
    })

# =========================
# CREAR QR (APP)
# =========================
@app.route("/crear-qr", methods=["POST"])
def crear_qr():

    datos = request.json or {}
    placa = datos.get("placa", "N/A")

    import uuid
    token = str(uuid.uuid4())

    nuevo = {
        "qrToken": token,
        "placa": placa,
        "horaEntrada": ahora_mexico()
        "horaSalida": None,
        "estado": "pendiente",  # 🔥 IMPORTANTE
        "precio": 0,
        "pagado": False,
        "tipo": "app"
    }

    entrada.insert_one(nuevo)

    return jsonify({
        "success": True,
        "qrToken": token,
        "horaEntrada": str(nuevo["horaEntrada"])
    })


# =========================
# SALIDA (COBRO)
# =========================
@app.route("/salida", methods=["POST"])
def salida():

    datos = request.json
    token = datos.get("qrToken")

    registro = entrada.find_one({
        "qrToken": token,
        "estado": "dentro"
    })

    if not registro:
        return jsonify({"success": False}), 404

    hora_salida = ahora_mexico()

    # 🔥 COBRO PARA DEMO → 20 pesos cada 5 segundos
    segundos = (hora_salida - registro["horaEntrada"]).total_seconds()
    precio = round((segundos / 5) * 20, 2)

    entrada.update_one(
        {"_id": registro["_id"]},
        {
            "$set": {
                "horaSalida": hora_salida,
                "estado": "salida",
                "precio": precio
            }
        }
    )

    return jsonify({
        "success": True,
        "precio": precio
    })


# =========================
# STATS (INGRESOS)
# =========================
@app.get("/stats")
def get_stats():

    total_spaces = TOTAL_LUGARES

    occupied = ia.count_documents({
        "estado": "Entrada"
    })

    if occupied > total_spaces:
        occupied = total_spaces

    available = total_spaces - occupied
    if available < 0:
        available = 0

    # 💰 INGRESOS DEL DÍA
    hoy = ahora_mexico().date()

    ingresos = entrada.aggregate([
        {
            "$match": {
                "estado": "salida",
                "horaSalida": {
                    "$gte": datetime.combine(hoy, datetime.min.time(), tzinfo=ZoneInfo("America/Mexico_City"))
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "total": {"$sum": "$precio"}
            }
        }
    ])

    total_income = 0
    for i in ingresos:
        total_income = round(i["total"], 2)

    return {
        "totalSpaces": total_spaces,
        "occupiedSpaces": occupied,
        "availableSpaces": available,
        "dailyIncome": total_income
    }


# =========================
# VEHÍCULOS
# =========================
@app.route("/vehicles", methods=["GET"])
def vehicles():

    lista = list(entrada.find().sort("_id", -1).limit(20))

    resultado = []

    for v in lista:

        estado = v.get("estado")

        # 🔥 manejar correctamente los estados
        if estado == "dentro":
            status = "Dentro"
        elif estado == "pendiente":
            status = "Pendiente"
        else:
            status = "Salida"

        resultado.append({
            "id": str(v["_id"]),
            "plate": v.get("placa") or "N/A",
            "status": status,
            "entryTime": v.get("horaEntrada").isoformat() if v.get("horaEntrada") else None,
            "exitTime": v.get("horaSalida").isoformat() if v.get("horaSalida") else None,
            "qrToken": v.get("qrToken"),
            "price": v.get("precio", 0)
        })

    return jsonify(resultado)


# =========================
# ALERTAS
# =========================
@app.route("/alerts", methods=["GET"])
def alerts():
    return jsonify([])

# =========================
# VALIDAR QR (ADMIN)
# =========================
@app.route("/validar-qr", methods=["POST"])
def validar_qr():

    datos = request.json
    token = datos.get("qrToken")

    registro = entrada.find_one({
        "qrToken": token
    })

    if not registro:
        return jsonify({
            "success": False,
            "message": "QR no encontrado"
        }), 404

    return jsonify({
        "success": True,
        "data": {
            "id": str(registro["_id"]),
            "placa": registro.get("placa", "N/A"),
            "horaEntrada": str(registro.get("horaEntrada")),
            "estado": registro.get("estado")
        }
    })

# =========================
# ACEPTAR QR (ENTRADA REAL)
# =========================
@app.route("/aceptar-qr", methods=["POST"])
def aceptar_qr():

    datos = request.json
    token = datos.get("qrToken")

    registro = entrada.find_one({
        "qrToken": token,
        "estado": "pendiente"
    })

    if not registro:
        return jsonify({
            "success": False,
            "message": "QR inválido o ya usado"
        }), 400

    entrada.update_one(
        {"_id": registro["_id"]},
        {
            "$set": {
                "estado": "dentro",
                "horaEntrada": ahora_mexico()  # 🔥 aquí inicia el conteo REAL
            }
        }
    )

    return jsonify({
        "success": True
    })

# =========================
# PREVIEW DE PAGO (NO COBRA)
# =========================
@app.route("/preview-pago", methods=["POST"])
def preview_pago():

    datos = request.json
    token = datos.get("qrToken")

    registro = entrada.find_one({
        "qrToken": token,
        "estado": "dentro"
    })

    if not registro:
        return jsonify({
            "success": False,
            "message": "Vehículo no válido"
        }), 404

    # 🔥 SI YA EXISTE PRECIO → NO RECALCULAR
    if registro.get("precio", 0) > 0:
        return jsonify({
            "success": True,
            "data": {
                "placa": registro.get("placa", "N/A"),
                "horaEntrada": str(registro["horaEntrada"]),
                "precio": registro["precio"]
            }
        })

    # 🔥 SI NO EXISTE → CALCULAR Y GUARDAR
    ahora = ahora_mexico()

    segundos = (ahora - registro["horaEntrada"]).total_seconds()
    precio = round((segundos / 5) * 20, 2)

    entrada.update_one(
        {"_id": registro["_id"]},
        {
            "$set": {
                "precio": precio
            }
        }
    )

    return jsonify({
        "success": True,
        "data": {
            "placa": registro.get("placa", "N/A"),
            "horaEntrada": str(registro["horaEntrada"]),
            "precio": precio
        }
    })

# =========================
# CONFIRMAR PAGO
# =========================
@app.route("/confirmar-pago", methods=["POST"])
def confirmar_pago():

    datos = request.json
    token = datos.get("qrToken")
    metodo = datos.get("metodo")

    registro = entrada.find_one({
        "qrToken": token,
        "estado": "dentro"
    })

    if not registro:
        return jsonify({
            "success": False,
            "message": "No válido"
        }), 404

    # 🔥 USAR PRECIO YA GUARDADO
    precio = registro.get("precio", 0)

    ahora = ahora_mexico()

    entrada.update_one(
        {"_id": registro["_id"]},
        {
            "$set": {
                "horaSalida": ahora,
                "estado": "salida",
                "precio": precio,
                "metodoPago": metodo,
                "pagado": True
            }
        }
    )

    return jsonify({
        "success": True,
        "precio": precio
    })

    

# =========================
# RUN
# =========================
if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port
    )